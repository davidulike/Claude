"""Shape of the JSON a TradingView alert sends to the webhook."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class Action(str, Enum):
    BUY = "buy"      # open / add to a long position
    SELL = "sell"    # reduce a long position (never opens a short)
    CLOSE = "close"  # flatten the position entirely


class Signal(BaseModel):
    secret: str
    symbol: str = Field(min_length=1, max_length=20)
    action: Action
    price: float = Field(gt=0, description="Reference price from TradingView ({{close}})")
    qty: float | None = Field(default=None, gt=0, description="Optional; otherwise sized by risk limits")
    signal_id: str | None = Field(default=None, max_length=128, description="Used to drop duplicate alerts")

    @field_validator("symbol")
    @classmethod
    def _normalize_symbol(cls, v: str) -> str:
        # TradingView may send "NASDAQ:AAPL"; brokers want "AAPL".
        return v.split(":")[-1].strip().upper()

    @field_validator("action", mode="before")
    @classmethod
    def _normalize_action(cls, v):
        if isinstance(v, str):
            v = v.strip().lower()
            # Common TradingView placeholder values
            return {"long": "buy", "exit": "close", "flat": "close"}.get(v, v)
        return v
