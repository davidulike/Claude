import json

import pytest
import requests

from bot.brokers import AlpacaBroker, BrokerError


class FakeResp:
    def __init__(self, status, data=None):
        self.status_code = status
        self._data = data
        self.content = json.dumps(data).encode() if data is not None else b""
        self.text = self.content.decode()

    def json(self):
        if self._data is None:
            raise ValueError
        return self._data


class FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.headers = {}
        self.calls = []

    def request(self, method, url, timeout=None, json=None):
        self.calls.append((method, url, json))
        r = self.routes.get((method, url.split(".markets", 1)[1]))
        if isinstance(r, Exception):
            raise r
        return r or FakeResp(404, {"message": "not found"})


def make(routes):
    s = FakeSession(routes)
    return AlpacaBroker("k", "s", paper=True, session=s), s


def test_uses_paper_url_and_auth_headers():
    b, s = make({})
    assert b.base_url == "https://paper-api.alpaca.markets"
    assert s.headers["APCA-API-KEY-ID"] == "k"


def test_account():
    b, _ = make({("GET", "/v2/account"): FakeResp(200, {"equity": "1000", "last_equity": "990",
                                                         "buying_power": "2000"})})
    a = b.get_account()
    assert (a.equity, a.start_of_day_equity, a.buying_power) == (1000, 990, 2000)


def test_blocked_account():
    b, _ = make({("GET", "/v2/account"): FakeResp(200, {"equity": "1", "last_equity": "1",
                                                         "buying_power": "1", "trading_blocked": True})})
    with pytest.raises(BrokerError):
        b.get_account()


def test_position_missing_is_zero():
    b, _ = make({})
    assert b.get_position_qty("SPY") == 0


def test_order_payload():
    b, s = make({("POST", "/v2/orders"): FakeResp(200, {"id": "o1", "symbol": "SPY", "side": "buy",
                                                         "qty": "3", "status": "accepted"})})
    o = b.submit_market_order("SPY", "buy", 3, 100)
    assert o.order_id == "o1"
    assert s.calls[-1][2] == {"symbol": "SPY", "qty": "3", "side": "buy", "type": "market",
                              "time_in_force": "day"}


def test_crypto_uses_gtc():
    b, s = make({("POST", "/v2/orders"): FakeResp(200, {"id": "o", "symbol": "BTCUSD", "side": "buy",
                                                         "qty": "0.1", "status": "accepted"})})
    b.submit_market_order("BTCUSD", "buy", 0.1, 1)
    assert s.calls[-1][2]["time_in_force"] == "gtc"


def test_api_error_raises():
    b, _ = make({("POST", "/v2/orders"): FakeResp(403, {"message": "insufficient buying power"})})
    with pytest.raises(BrokerError, match="insufficient buying power"):
        b.submit_market_order("SPY", "buy", 1, 1)


def test_network_error_raises_broker_error():
    b, _ = make({("GET", "/v2/account"): requests.ConnectionError("down")})
    with pytest.raises(BrokerError):
        b.get_account()


def test_close_missing_position_returns_none():
    b, _ = make({})
    assert b.close_position("SPY", 1) is None
