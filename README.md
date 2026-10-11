# TradingView Webhook Trading Bot

TradingView alert ──(webhook JSON)──▶ this bot ──▶ risk checks ──▶ broker (paper sim or Alpaca)

> **Read this first.** No bot can guarantee profit. This software places orders exactly as
> your TradingView strategy tells it to, and **a strategy can and will lose money**. The code is tested,
> but markets, brokers, networks and TradingView itself can fail. Start with `BROKER=paper`.
> Then use Alpaca *paper* for several weeks. Only use money you can afford to lose. This is not financial advice.

## What's included

| Path | What it does |
|---|---|
| `pine/rsi2_dip_strategy.pine` | **Recommended.** RSI(2) dip-buy: in an uptrend (above the 200 SMA), buy sharp 1–2 day dips and sell on the bounce. Fewest losing trades in testing |
| `research/compare_strategies.py` | Tests all the strategies below on real price history and prints the results |
| `pine/sma_cross_strategy.pine` | The video's strategy (not recommended, see below): buy on a close above the 50 SMA, sell on a close below. Optional MACD 3/10/16, higher-timeframe filter, and stop-loss with risk-% sizing |
| `pine/ema_rsi_atr_strategy.pine` | Another example strategy (EMA cross + RSI filter + ATR stop/target, long only) |
| `bot/backtest.py` | Backtests the RSI(2) or SMA rules on a TradingView CSV: with and without commission, against buy-and-hold |
| `bot/app.py` | Webhook server (`POST /webhook`, `GET /health`, `GET /status`) |
| `bot/risk.py` | Risk limits: risk-% sizing from the stop-loss, max $ per position, daily loss limit, max trades/day, symbol allow-list, duplicate-alert filter, kill switch |
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

1. Open a **daily** chart and the Pine Editor. Paste `pine/rsi2_dip_strategy.pine`, then **Add to chart**.
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

## Which strategy to use: test results

`python research/compare_strategies.py` runs each strategy on 7 real markets: the S&P 500, Apple, Microsoft,
IBM and Starbucks (2007–2016, including the 2008 crash), Google (2004–2013) and oil (1986–2019).
It goes all-in on each trade and pays 0.1% commission per buy and per sell.

| Strategy | Losing trades | Markets where it lost money | Beat buy-and-hold |
|---|---|---|---|
| Video: SMA 50 cross | 76% | 2 of 7 (S&P 500 −16%, IBM −24%) | 1 of 7 |
| SMA 50 cross, only above SMA 200 | 76% | 3 of 7 | 0 of 7 |
| SMA 50 cross with 2% buffer | 66% | 3 of 7 | 0 of 7 |
| SMA 50 cross + 5% take-profit | 69% | **6 of 7** | 0 of 7 |
| **RSI(2) dip-buy above SMA 200** | **37%** | **0 of 7** | 0 of 7 |
| RSI(2) dip-buy + 10% stop | 37% | 2 of 7 | 0 of 7 |

What this means:
- **The RSI(2) dip-buy has the fewest losing trades and made money on every market tested**, with much smaller
  drops than holding (S&P 500: worst drop 16% vs 56%). It's the default for the bot's backtester and the recommended script.
- **But no strategy beat simply buying and holding.** The RSI(2) strategy is out of the market about 90% of the time, so it
  misses most of the gains. It earned +9% on the S&P 500 where holding earned +29%.
- **A higher win rate doesn't mean more money.** The take-profit version wins more often but lost money on 6 of 7 markets,
  because it cuts the winners short.
- A fixed 10% stop made the RSI(2) strategy *worse* in testing, so it's off by default.
- These are past results on 7 markets. Losing trades still happen (about 1 in 3), and the future can be different.

## Features from the "AI Trading" course video

| In the video | Where it is here |
|---|---|
| SMA 50 strategy: buy on a close above, sell on a close below, long or flat | `pine/sma_cross_strategy.pine` (defaults match the video). **Not recommended:** it lost money on the S&P 500 and IBM in testing |
| MACD with Linda Raschke's 3/10/16 settings, for confluence | Strategy input "Require MACD confluence" |
| Multi-timeframe: higher timeframe for direction, lower for entries | Strategy input "Only buy when higher timeframe is in an uptrend" |
| Backtest on $10k with and without commission, compared with buy-and-hold | TradingView Strategy Tester, or `python -m bot.backtest your_export.csv` |
| Position sizing: risk 2% of the account with a stop-loss | `RISK_PER_TRADE_PCT=2`. Alerts that include `"stop"` are sized automatically (strategy input "Use stop-loss + risk-% sizing") |
| Paper trade before real money | `BROKER=paper` (default) or Alpaca with `ALPACA_PAPER=true` |

Not included: **connecting Claude to the TradingView desktop app** (the "TradingView MCP"). It is a separate,
unofficial open-source tool that runs on your own computer and lets Claude read and draw on your chart.
It's for analysis: support/resistance, market structure, adding indicators. This bot doesn't need it.
To set it up, follow the guide linked in the video and read that project's GitHub page first.

Things the video points out that apply here too:
- The SMA strategy loses on most trades (about 70% in the video's test). It makes money from a few big winners.
  Expect long losing streaks.
- The video's result (about 1.8x buy-and-hold) is on Bitcoin since 2015, which went up a lot. Test other markets and
  periods before trusting it.
- You stay responsible. Check what the bot did every day.

### Backtest example
```bash
python -m bot.backtest SPY_1D.csv                                   # RSI(2) dip-buy (default)
python -m bot.backtest BITSTAMP_BTCUSD_1D.csv --strategy sma --sma 50   # the video's strategy
```

## Known limitations (be aware)
- The built-in `paper` broker keeps its state in memory, so it resets when the server restarts.
- Stop-loss and take-profit are run by TradingView alerts, not placed at the broker. If TradingView, your server or the
  network is down when a stop triggers, the position stays open. Watch your positions.
- Market orders fill at the market price, not the alert's `price`. Expect slippage.
- `GET /status` needs the header `X-Webhook-Secret: <secret>`.
