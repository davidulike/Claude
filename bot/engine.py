"""Turns a validated Signal into (at most) one broker order and journals the outcome."""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from .brokers import Broker, BrokerError
from .models import Action, Signal
from .risk import RiskManager, RiskRejected

log = logging.getLogger("bot")


class Engine:
    def __init__(self, broker: Broker, risk: RiskManager, journal_path: str | None = None):
        self.broker = broker
        self.risk = risk
        self.journal_path = Path(journal_path) if journal_path else None
        # One signal at a time: avoids racing two alerts into double positions.
        self._lock = threading.Lock()

    def handle(self, signal: Signal) -> dict:
        with self._lock:
            try:
                result = self._execute(signal)
            except RiskRejected as exc:
                result = {"status": "rejected", "reason": str(exc)}
            except BrokerError as exc:
                result = {"status": "error", "reason": str(exc)}
            except Exception as exc:  # never let one bad alert kill the server
                log.exception("unexpected error handling signal")
                result = {"status": "error", "reason": f"unexpected: {exc}"}
        result.update(symbol=signal.symbol, action=signal.action.value, signal_id=signal.signal_id)
        self._journal(signal, result)
        log.info("signal %s %s -> %s", signal.action.value, signal.symbol, result)
        return result

    def _execute(self, signal: Signal) -> dict:
        self.risk.check_duplicate(signal)
        account = self.broker.get_account()
        self.risk.check_signal(signal, account)
        held = self.broker.get_position_qty(signal.symbol)

        if signal.action is Action.BUY:
            qty = self.risk.size_buy(signal, held, account)
            order = self.broker.submit_market_order(signal.symbol, "buy", qty, signal.price)
            self.risk.record_trade()
        elif signal.action is Action.SELL:
            if held <= 0:
                return {"status": "ignored", "reason": "no position to sell"}
            qty = min(signal.qty, held) if signal.qty else held
            if qty >= held:
                order = self.broker.close_position(signal.symbol, signal.price)
            else:
                order = self.broker.submit_market_order(signal.symbol, "sell", qty, signal.price)
        else:  # CLOSE
            if held <= 0:
                return {"status": "ignored", "reason": "already flat"}
            order = self.broker.close_position(signal.symbol, signal.price)

        if order is None:
            return {"status": "ignored", "reason": "no position"}
        return {"status": "submitted", "order_id": order.order_id, "side": order.side,
                "qty": order.qty, "order_status": order.status}

    def _journal(self, signal: Signal, result: dict) -> None:
        if not self.journal_path:
            return
        try:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "time": datetime.now(timezone.utc).isoformat(),
                "signal": signal.model_dump(mode="json", exclude={"secret"}),
                "result": result,
            }
            with self.journal_path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            log.exception("could not write journal")
