import json

import pytest

from bot.config import ConfigError, Settings

from .conftest import SECRET, sig


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["mode"] == "PAPER-SIM"


def test_buy_is_sized_by_max_position(client, broker):
    r = client.post("/webhook", json=sig(price=101.0))
    assert r.json()["status"] == "submitted"
    assert broker.positions["SPY"] == 9  # floor(1000 / 101)


def test_buy_respects_requested_qty_but_caps_it(client, broker):
    client.post("/webhook", json=sig(qty=2))
    assert broker.positions["SPY"] == 2
    client.post("/webhook", json=sig(qty=500))
    assert broker.positions["SPY"] == 10  # capped at $1000 total


def test_position_limit_blocks_further_buys(client, broker):
    client.post("/webhook", json=sig())
    r = client.post("/webhook", json=sig())
    assert r.json()["status"] == "rejected"
    assert broker.positions["SPY"] == 10


def test_close_flattens_and_realizes_pnl(client, broker):
    client.post("/webhook", json=sig(price=100))
    r = client.post("/webhook", json=sig("close", price=110))
    assert r.json()["status"] == "submitted"
    assert "SPY" not in broker.positions
    assert broker.cash == pytest.approx(10_100)


def test_partial_sell(client, broker):
    client.post("/webhook", json=sig())
    client.post("/webhook", json=sig("sell", qty=4))
    assert broker.positions["SPY"] == 6


def test_close_when_flat_is_ignored(client):
    assert client.post("/webhook", json=sig("close")).json()["status"] == "ignored"
    assert client.post("/webhook", json=sig("sell")).json()["status"] == "ignored"


def test_bad_secret(client, broker):
    r = client.post("/webhook", json={**sig(), "secret": "wrong"})
    assert r.status_code == 401 and not broker.positions
    r = client.post("/webhook", json={k: v for k, v in sig().items() if k != "secret"})
    assert r.status_code == 401


@pytest.mark.parametrize("body", ["not json", "[1,2]", ""])
def test_malformed_body(client, body):
    r = client.post("/webhook", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 400


@pytest.mark.parametrize("bad", [{"action": "moon"}, {"price": -1}, {"price": "abc"}, {"symbol": ""}])
def test_invalid_fields(client, bad):
    r = client.post("/webhook", json={**sig(), **bad})
    assert r.status_code == 422


def test_plain_text_body_from_tradingview(client, broker):
    # TradingView sends text/plain; the body must still parse.
    r = client.post("/webhook", content=json.dumps(sig()), headers={"content-type": "text/plain"})
    assert r.json()["status"] == "submitted"


def test_symbol_normalization(client, broker):
    client.post("/webhook", json=sig(symbol="amex:spy", action="LONG"))
    assert broker.positions["SPY"] == 10


def test_symbol_not_allowed(client):
    assert client.post("/webhook", json=sig(symbol="TSLA")).json()["status"] == "rejected"


def test_duplicate_signal_id_dropped(client, broker):
    client.post("/webhook", json=sig(qty=1, signal_id="abc"))
    r = client.post("/webhook", json=sig(qty=1, signal_id="abc"))
    assert r.json()["status"] == "rejected" and broker.positions["SPY"] == 1


def test_max_trades_per_day(client):
    for _ in range(3):
        assert client.post("/webhook", json=sig(qty=1)).json()["status"] == "submitted"
    assert client.post("/webhook", json=sig(qty=1)).json()["status"] == "rejected"
    # exits still allowed
    assert client.post("/webhook", json=sig("close")).json()["status"] == "submitted"


def test_daily_loss_limit_blocks_entries_but_not_exits(client, broker):
    client.post("/webhook", json=sig(symbol="AAPL", price=100))  # 10 shares
    client.post("/webhook", json=sig("sell", symbol="AAPL", price=80, qty=1))  # marks price down: -200
    r = client.post("/webhook", json=sig(price=50))
    assert r.json()["status"] == "rejected" and "daily loss" in r.json()["reason"]
    assert client.post("/webhook", json=sig("close", symbol="AAPL", price=80)).json()["status"] == "submitted"


def test_trading_disabled(settings, broker):
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from bot.app import create_app

    c = TestClient(create_app(replace(settings, trading_enabled=False), broker))
    assert c.post("/webhook", json=sig()).json()["status"] == "rejected"
    assert not broker.positions


def test_crypto_fractional(client, broker):
    client.post("/webhook", json=sig(symbol="BINANCE:BTCUSD", price=60_000))
    assert broker.positions["BTCUSD"] == pytest.approx(0.016666)


def test_journal_written_without_secret(client, settings):
    client.post("/webhook", json=sig())
    lines = open(settings.journal_path).read().splitlines()
    assert len(lines) == 1 and SECRET not in lines[0]


def test_status_requires_secret(client):
    assert client.get("/status").status_code == 401
    r = client.get("/status", headers={"x-webhook-secret": SECRET})
    assert r.status_code == 200 and r.json()["equity"] == 10_000


def test_broker_exception_does_not_crash(client, broker, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(broker, "get_account", boom)
    r = client.post("/webhook", json=sig())
    assert r.status_code == 200 and r.json()["status"] == "error"


def test_config_validation(monkeypatch):
    with pytest.raises(ConfigError):
        Settings(webhook_secret="change-me").validate()
    with pytest.raises(ConfigError):
        Settings(webhook_secret="x" * 20, broker="alpaca").validate()
    monkeypatch.setenv("WEBHOOK_SECRET", "x" * 20)
    monkeypatch.setenv("MAX_POSITION_USD", "lots")
    with pytest.raises(ConfigError):
        Settings.from_env(dotenv=None)


def test_stop_based_risk_sizing(settings, broker):
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from bot.app import create_app

    c = TestClient(create_app(replace(settings, max_position_usd=10_000), broker))
    # Video example: $10k account, risk 2% = $200, entry 100, stop 90 -> 20 shares
    r = c.post("/webhook", json=sig(price=100, stop=90))
    assert r.json()["status"] == "submitted"
    assert broker.positions["SPY"] == 20


def test_stop_sizing_still_capped_by_max_position(client, broker):
    client.post("/webhook", json=sig(price=100, stop=99))  # risk sizing says 200, cap says 10
    assert broker.positions["SPY"] == 10


def test_stop_above_price_rejected(client, broker):
    r = client.post("/webhook", json=sig(price=100, stop=105))
    assert r.json()["status"] == "rejected" and not broker.positions
