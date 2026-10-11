"""FastAPI webhook server that TradingView alerts POST to."""
from __future__ import annotations

import hmac
import json
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .brokers import AlpacaBroker, Broker, BrokerError, PaperBroker
from .config import Settings
from .engine import Engine
from .models import Signal
from .risk import RiskManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")


def build_broker(s: Settings) -> Broker:
    if s.broker == "alpaca":
        return AlpacaBroker(s.alpaca_api_key, s.alpaca_api_secret, paper=s.alpaca_paper)
    return PaperBroker(s.paper_starting_cash)


def create_app(settings: Settings | None = None, broker: Broker | None = None) -> FastAPI:
    s = settings or Settings.from_env()
    broker = broker or build_broker(s)
    engine = Engine(broker, RiskManager(s), s.journal_path)
    mode = "PAPER-SIM" if s.broker == "paper" else ("ALPACA-PAPER" if s.alpaca_paper else "ALPACA-LIVE")
    log.info("starting bot in %s mode, trading_enabled=%s", mode, s.trading_enabled)
    if mode == "ALPACA-LIVE":
        log.warning("LIVE TRADING WITH REAL MONEY IS ENABLED")

    app = FastAPI(title="TradingView Webhook Bot")
    app.state.engine = engine
    app.state.broker = broker

    @app.get("/health")
    def health():
        return {"ok": True, "mode": mode, "trading_enabled": s.trading_enabled}

    @app.post("/webhook")
    async def webhook(request: Request):
        body = await request.body()
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return JSONResponse({"status": "error", "reason": "body is not valid JSON"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"status": "error", "reason": "body must be a JSON object"}, status_code=400)

        secret = payload.get("secret")
        if not isinstance(secret, str) or not hmac.compare_digest(secret.encode(), s.webhook_secret.encode()):
            log.warning("rejected webhook with bad secret from %s", request.client.host if request.client else "?")
            return JSONResponse({"status": "error", "reason": "unauthorized"}, status_code=401)

        try:
            signal = Signal.model_validate(payload)
        except ValidationError as exc:
            errors = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
            return JSONResponse({"status": "error", "reason": "invalid signal", "details": errors},
                                status_code=422)

        # Engine is synchronous (blocking HTTP to the broker); run it off the event loop.
        result = await run_in_threadpool(engine.handle, signal)
        return JSONResponse(result, status_code=200)

    @app.get("/status")
    def status(request: Request):
        # Same secret, passed as a header, so account details aren't public.
        given = request.headers.get("x-webhook-secret", "")
        if not hmac.compare_digest(given.encode(), s.webhook_secret.encode()):
            return JSONResponse({"status": "error", "reason": "unauthorized"}, status_code=401)
        try:
            acct = broker.get_account()
        except BrokerError as exc:
            return JSONResponse({"status": "error", "reason": str(exc)}, status_code=502)
        return {"mode": mode, "equity": acct.equity, "start_of_day_equity": acct.start_of_day_equity,
                "buying_power": acct.buying_power}

    return app


def main() -> None:
    import os

    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
