# TradingView Webhook Trading Bot

TradingView alert ──(webhook JSON)──▶ this bot ──▶ risk checks ──▶ broker (paper sim or Alpaca)

> **Read this first.** No bot can guarantee profit. This software places orders exactly as
> your TradingView strategy tells it to, and **a strategy can and will lose money**. The code is tested,
> but markets, brokers, networks and TradingView itself can fail. Start with `BROKER=paper`.
> Then use Alpaca *paper* for several weeks. Only use money you can afford to lose. This is not financial advice.

## What's included

| Path | What it does |
|---|---|
| `pine/ema_rsi_atr_strategy.pine` | Example TradingView strategy (EMA cross + RSI filter + ATR stop/target, long only) that sends webhook alerts |
| `bot/app.py` | Webhook server (`POST /webhook`, `GET /health`, `GET /status`) |
| `bot/risk.py` | Risk limits: max $ per position, daily loss limit, max trades/day, symbol allow-list, duplicate-alert filter, kill switch |
| `bot/brokers.py` | Built-in paper simulator and Alpaca (paper/live) connector |
| `journal/trades.jsonl` | Every signal and its result is appended here |

Safety behaviour:
- Wrong or missing secret → rejected (401), nothing traded.
- Malformed alert → rejected (400/422), nothing traded.
- Long only: `sell` never opens a short, and buys are capped at `MAX_POSITION_USD`.
- After the daily loss limit or the trade limit is hit, new **entries** are blocked. **Exits** always go through.
- Broker or network errors are caught, logged and journaled. The server keeps running.

## 1. Install and run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # then edit .env, at least WEBHOOK_SECRET
python -m pytest              # run the test suite
python -m bot.app             # serves on http://0.0.0.0:8000
```

Generate a secret: `python -c "import secrets; print(secrets.token_urlsafe(32))"`

Test it by hand:
```bash
curl -X POST localhost:8000/webhook -d '{"secret":"YOUR_SECRET","symbol":"SPY","action":"buy","price":500}'
```

## 2. Make it reachable from TradingView

TradingView webhooks need a public **HTTPS** URL on port 443 or 80 (TradingView also requires a paid plan with 2FA turned on for webhooks).
Options:
- Deploy to a small VPS or a service like Render, Railway or Fly.io. Start command: `python -m bot.app` (it honours `$PORT`).
- For quick testing: `ngrok http 8000`, then use the https URL it prints.

Your webhook URL is `https://<your-host>/webhook`.

## 3. Set up TradingView

1. Open a chart and the Pine Editor. Paste `pine/ema_rsi_atr_strategy.pine`, then **Add to chart**.
2. In the strategy settings, set **Webhook secret** to the same value as `WEBHOOK_SECRET`.
3. Check the **Strategy Tester** results. If the backtest is bad, don't trade it.
4. Create an alert: **Condition** = this strategy, select *"alert() function calls and order fills"* (or "Order fills only").
   Set **Message** to exactly: `{{strategy.order.alert_message}}`
   Under **Notifications**, tick **Webhook URL** and enter your URL.

### Using your own strategy or indicator
Any alert works if its message is JSON like this:
```json
{"secret":"YOUR_SECRET","symbol":"{{ticker}}","action":"buy","price":{{close}}}
```
- `action`: `buy` | `sell` | `close` (`long` maps to `buy`; `exit` and `flat` map to `close`).
- Optional: `"qty": 5` caps the size; it's still limited by `MAX_POSITION_USD`.
- Optional: `"signal_id": "..."` means a repeated alert with the same id is ignored.

## 4. Connect a real broker (Alpaca)

1. Create an account at alpaca.markets and generate **paper** API keys.
2. In `.env`: `BROKER=alpaca`, `ALPACA_API_KEY=...`, `ALPACA_API_SECRET=...`, `ALPACA_PAPER=true`.
3. Watch it trade on paper for weeks. Compare the fills with your TradingView backtest.
4. To go live, use live keys with `ALPACA_PAPER=false`. The log will print `LIVE TRADING WITH REAL MONEY IS ENABLED`.

Emergency stop: set `TRADING_ENABLED=false` and restart, or close positions in the Alpaca dashboard.

## Known limitations (be aware)
- The built-in `paper` broker keeps its state in memory, so it resets when the server restarts.
- Stop-loss and take-profit are run by TradingView alerts, not placed at the broker. If TradingView, your server or the
  network is down when a stop triggers, the position stays open. Watch your positions.
- Market orders fill at the market price, not the alert's `price`. Expect slippage.
- `GET /status` needs the header `X-Webhook-Secret: <secret>`.
