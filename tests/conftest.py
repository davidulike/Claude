import pytest
from fastapi.testclient import TestClient

from bot.app import create_app
from bot.brokers import PaperBroker
from bot.config import Settings

SECRET = "test-secret-0123456789"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        webhook_secret=SECRET,
        allowed_symbols=frozenset({"SPY", "AAPL", "BTCUSD"}),
        max_position_usd=1000,
        max_daily_loss_usd=100,
        max_trades_per_day=3,
        paper_starting_cash=10_000,
        journal_path=str(tmp_path / "journal.jsonl"),
    ).validate()


@pytest.fixture
def broker():
    return PaperBroker(10_000)


@pytest.fixture
def client(settings, broker):
    return TestClient(create_app(settings, broker))


def sig(action="buy", symbol="SPY", price=100.0, **extra):
    return {"secret": SECRET, "symbol": symbol, "action": action, "price": price, **extra}
