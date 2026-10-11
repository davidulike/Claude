"""Pre-trade risk checks. Every order must pass these before reaching the broker."""
from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import date

from .brokers import Account, floor_qty, is_crypto
from .config import Settings
from .models import Action, Signal


class RiskRejected(Exception):
    pass


class RiskManager:
    def __init__(self, settings: Settings):
        self.s = settings
        self._day = date.today()
        self._trades_today = 0
        self._seen_ids: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()

    def _roll_day(self) -> None:
        today = date.today()
        if today != self._day:
            self._day = today
            self._trades_today = 0

    def check_duplicate(self, signal: Signal) -> None:
        if not signal.signal_id:
            return
        with self._lock:
            if signal.signal_id in self._seen_ids:
                raise RiskRejected(f"duplicate signal_id {signal.signal_id!r}")
            self._seen_ids[signal.signal_id] = None
            while len(self._seen_ids) > 5000:
                self._seen_ids.popitem(last=False)

    def check_signal(self, signal: Signal, account: Account) -> None:
        if not self.s.trading_enabled:
            raise RiskRejected("trading disabled (TRADING_ENABLED=false)")
        if self.s.allowed_symbols and signal.symbol not in self.s.allowed_symbols:
            raise RiskRejected(f"symbol {signal.symbol} not in ALLOWED_SYMBOLS")
        # Exits are always allowed (they reduce risk); entries are gated.
        if signal.action is Action.BUY:
            with self._lock:
                self._roll_day()
                if self._trades_today >= self.s.max_trades_per_day:
                    raise RiskRejected(f"max trades per day ({self.s.max_trades_per_day}) reached")
            loss = account.start_of_day_equity - account.equity
            if loss >= self.s.max_daily_loss_usd:
                raise RiskRejected(
                    f"daily loss limit hit: down {loss:.2f} (limit {self.s.max_daily_loss_usd:.2f})"
                )

    def size_buy(self, signal: Signal, current_qty: float, account: Account) -> float:
        """Shares to buy so the position stays within MAX_POSITION_USD and buying power."""
        decimals = 6 if is_crypto(signal.symbol) else 0
        current_value = current_qty * signal.price
        room = min(self.s.max_position_usd - current_value, account.buying_power)
        max_qty = floor_qty(max(room, 0.0) / signal.price, decimals)
        qty = min(signal.qty, max_qty) if signal.qty else max_qty
        qty = floor_qty(qty, decimals)
        if qty <= 0:
            raise RiskRejected(
                f"position limit reached or price too high: room ${max(room, 0):.2f}, price {signal.price}"
            )
        return qty

    def record_trade(self) -> None:
        with self._lock:
            self._roll_day()
            self._trades_today += 1
