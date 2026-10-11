"""Broker adapters: a built-in paper simulator and Alpaca (paper or live)."""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import requests


class BrokerError(RuntimeError):
    pass


@dataclass
class Account:
    equity: float
    start_of_day_equity: float
    buying_power: float


@dataclass
class OrderResult:
    order_id: str
    symbol: str
    side: str
    qty: float
    status: str


class Broker(Protocol):
    def get_account(self) -> Account: ...
    def get_position_qty(self, symbol: str) -> float: ...
    def submit_market_order(self, symbol: str, side: str, qty: float, ref_price: float) -> OrderResult: ...
    def close_position(self, symbol: str, ref_price: float) -> OrderResult | None: ...


class PaperBroker:
    """In-memory simulator that fills market orders at the reference price."""

    def __init__(self, starting_cash: float = 10_000.0):
        self.cash = starting_cash
        self.positions: dict[str, float] = {}
        self.last_price: dict[str, float] = {}
        self._day = date.today()
        self._day_start_equity = starting_cash
        self._next_id = 1
        self._lock = threading.Lock()

    def _equity(self) -> float:
        return self.cash + sum(q * self.last_price.get(s, 0.0) for s, q in self.positions.items())

    def _roll_day(self) -> None:
        today = date.today()
        if today != self._day:
            self._day = today
            self._day_start_equity = self._equity()

    def get_account(self) -> Account:
        with self._lock:
            self._roll_day()
            eq = self._equity()
            return Account(equity=eq, start_of_day_equity=self._day_start_equity, buying_power=self.cash)

    def get_position_qty(self, symbol: str) -> float:
        with self._lock:
            return self.positions.get(symbol, 0.0)

    def submit_market_order(self, symbol: str, side: str, qty: float, ref_price: float) -> OrderResult:
        if qty <= 0:
            raise BrokerError("qty must be > 0")
        with self._lock:
            self._roll_day()
            self.last_price[symbol] = ref_price
            held = self.positions.get(symbol, 0.0)
            if side == "buy":
                cost = qty * ref_price
                if cost > self.cash + 1e-9:
                    raise BrokerError(f"insufficient cash: need {cost:.2f}, have {self.cash:.2f}")
                self.cash -= cost
                self.positions[symbol] = held + qty
            elif side == "sell":
                if qty > held + 1e-9:
                    raise BrokerError(f"cannot sell {qty}, only hold {held}")
                self.cash += qty * ref_price
                remaining = held - qty
                if remaining <= 1e-9:
                    self.positions.pop(symbol, None)
                else:
                    self.positions[symbol] = remaining
            else:
                raise BrokerError(f"unknown side {side!r}")
            oid = f"paper-{self._next_id}"
            self._next_id += 1
            return OrderResult(oid, symbol, side, qty, "filled")

    def close_position(self, symbol: str, ref_price: float) -> OrderResult | None:
        qty = self.get_position_qty(symbol)
        if qty <= 0:
            return None
        return self.submit_market_order(symbol, "sell", qty, ref_price)


class AlpacaBroker:
    """Alpaca Trading API v2 over REST. https://docs.alpaca.markets/reference"""

    PAPER_URL = "https://paper-api.alpaca.markets"
    LIVE_URL = "https://api.alpaca.markets"

    def __init__(self, key: str, secret: str, paper: bool = True, session: requests.Session | None = None,
                 timeout: float = 10.0):
        self.base_url = self.PAPER_URL if paper else self.LIVE_URL
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        try:
            resp = self.session.request(method, self.base_url + path, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise BrokerError(f"Alpaca request failed: {exc}") from exc
        return resp

    @staticmethod
    def _check(resp: requests.Response) -> dict:
        if resp.status_code >= 400:
            try:
                msg = resp.json().get("message", resp.text)
            except ValueError:
                msg = resp.text
            raise BrokerError(f"Alpaca error {resp.status_code}: {msg}")
        try:
            return resp.json() if resp.content else {}
        except ValueError as exc:
            raise BrokerError("Alpaca returned invalid JSON") from exc

    @staticmethod
    def _api_symbol(symbol: str) -> str:
        return symbol.replace("/", "")

    def get_account(self) -> Account:
        data = self._check(self._request("GET", "/v2/account"))
        if data.get("trading_blocked") or data.get("account_blocked"):
            raise BrokerError("Alpaca account is blocked from trading")
        return Account(
            equity=float(data["equity"]),
            start_of_day_equity=float(data["last_equity"]),
            buying_power=float(data["buying_power"]),
        )

    def get_position_qty(self, symbol: str) -> float:
        resp = self._request("GET", f"/v2/positions/{self._api_symbol(symbol)}")
        if resp.status_code == 404:
            return 0.0
        return float(self._check(resp)["qty"])

    def submit_market_order(self, symbol: str, side: str, qty: float, ref_price: float) -> OrderResult:
        crypto = is_crypto(symbol)
        body = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": "market",
            # Fractional stock orders must be DAY; crypto must be GTC/IOC.
            "time_in_force": "gtc" if crypto else "day",
        }
        data = self._check(self._request("POST", "/v2/orders", json=body))
        return OrderResult(data["id"], data["symbol"], data["side"], float(data["qty"]), data["status"])

    def close_position(self, symbol: str, ref_price: float) -> OrderResult | None:
        resp = self._request("DELETE", f"/v2/positions/{self._api_symbol(symbol)}")
        if resp.status_code == 404:
            return None
        data = self._check(resp)
        return OrderResult(data["id"], data["symbol"], data["side"], float(data.get("qty") or 0), data["status"])


def floor_qty(value: float, decimals: int) -> float:
    factor = 10 ** decimals
    return math.floor(value * factor) / factor


def is_crypto(symbol: str) -> bool:
    return "/" in symbol or (symbol.endswith("USD") and len(symbol) > 5)
