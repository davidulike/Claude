"""Settings loaded from environment variables (optionally via a .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, existing env vars win."""
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    webhook_secret: str
    broker: str = "paper"
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_paper: bool = True
    trading_enabled: bool = True
    allowed_symbols: frozenset[str] = field(default_factory=frozenset)
    max_position_usd: float = 1000.0
    max_daily_loss_usd: float = 100.0
    max_trades_per_day: int = 10
    paper_starting_cash: float = 10_000.0
    journal_path: str = "journal/trades.jsonl"

    def validate(self) -> "Settings":
        if not self.webhook_secret or self.webhook_secret == "change-me":
            raise ConfigError("WEBHOOK_SECRET must be set to a long random string")
        if len(self.webhook_secret) < 16:
            raise ConfigError("WEBHOOK_SECRET must be at least 16 characters")
        if self.broker not in {"paper", "alpaca"}:
            raise ConfigError("BROKER must be 'paper' or 'alpaca'")
        if self.broker == "alpaca" and not (self.alpaca_api_key and self.alpaca_api_secret):
            raise ConfigError("ALPACA_API_KEY and ALPACA_API_SECRET are required for BROKER=alpaca")
        if self.max_position_usd <= 0:
            raise ConfigError("MAX_POSITION_USD must be > 0")
        if self.max_daily_loss_usd <= 0:
            raise ConfigError("MAX_DAILY_LOSS_USD must be > 0")
        if self.max_trades_per_day <= 0:
            raise ConfigError("MAX_TRADES_PER_DAY must be > 0")
        return self

    @classmethod
    def from_env(cls, dotenv: str | None = ".env") -> "Settings":
        if dotenv:
            _load_dotenv(Path(dotenv))
        env = os.environ.get
        try:
            return cls(
                webhook_secret=env("WEBHOOK_SECRET", ""),
                broker=env("BROKER", "paper").strip().lower(),
                alpaca_api_key=env("ALPACA_API_KEY", ""),
                alpaca_api_secret=env("ALPACA_API_SECRET", ""),
                alpaca_paper=_bool(env("ALPACA_PAPER", "true")),
                trading_enabled=_bool(env("TRADING_ENABLED", "true")),
                allowed_symbols=frozenset(
                    s.strip().upper() for s in env("ALLOWED_SYMBOLS", "").split(",") if s.strip()
                ),
                max_position_usd=float(env("MAX_POSITION_USD", "1000")),
                max_daily_loss_usd=float(env("MAX_DAILY_LOSS_USD", "100")),
                max_trades_per_day=int(env("MAX_TRADES_PER_DAY", "10")),
                paper_starting_cash=float(env("PAPER_STARTING_CASH", "10000")),
                journal_path=env("JOURNAL_PATH", "journal/trades.jsonl"),
            ).validate()
        except ValueError as exc:
            if isinstance(exc, ConfigError):
                raise
            raise ConfigError(f"Invalid number in configuration: {exc}") from exc
