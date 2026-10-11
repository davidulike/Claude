"""Compare strategies on real daily price history (all-in, long/flat, 0.1% commission per side).

    python research/compare_strategies.py

Downloads public CSVs from GitHub into research/data/ on first run:
  S&P 500, Apple, Microsoft, IBM, Starbucks daily 2007-2016 (plotly/datasets),
  Google daily 2004-2013 (kernc/backtesting.py), WTI oil daily 1986-2019 (datasets/oil-prices;
  2020+ is skipped because oil futures went negative in April 2020).
Every strategy starts trading on bar 200 so all of them, and buy-and-hold, cover the same period.
"""
from __future__ import annotations

import csv
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.backtest import Result, run_rsi2_dip, run_rules, run_sma_cross, sma  # noqa: E402

DATA = Path(__file__).parent / "data"
SOURCES = {
    "stockdata.csv": "https://raw.githubusercontent.com/plotly/datasets/master/stockdata.csv",
    "GOOG.csv": "https://raw.githubusercontent.com/kernc/backtesting.py/master/backtesting/test/GOOG.csv",
    "wti-daily.csv": "https://raw.githubusercontent.com/datasets/oil-prices/main/data/wti-daily.csv",
}
START = 200
COMMISSION = 0.1


def fetch() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES.items():
        if not (DATA / name).exists():
            print(f"downloading {url}")
            urllib.request.urlretrieve(url, DATA / name)


def markets() -> dict[str, list[float]]:
    out = {}
    rows = list(csv.DictReader(open(DATA / "stockdata.csv")))
    for col, name in [("GSPC", "S&P 500 07-16"), ("AAPL", "Apple 07-16"), ("MSFT", "Microsoft 07-16"),
                      ("IBM", "IBM 07-16"), ("SBUX", "Starbucks 07-16")]:
        out[name] = [float(r[col]) for r in rows]
    out["Google 04-13"] = [float(r["Close"]) for r in csv.DictReader(open(DATA / "GOOG.csv"))]
    out["Oil 86-19"] = [float(r["Price"]) for r in csv.DictReader(open(DATA / "wti-daily.csv"))
                        if r["Date"] < "2020-01-01"]
    return out


def sma_variant(c: list[float], label: str, buffer: float = 0.0, need_200: bool = False,
                take_profit: float | None = None) -> Result:
    s50, s200 = sma(c, 50), sma(c, 200)
    hi, lo = 1 + buffer, 1 - buffer

    def entry(i: int) -> bool:
        cross = c[i] > s50[i] * hi and not c[i - 1] > s50[i - 1] * hi
        return cross and (not need_200 or c[i] > s200[i])

    def exit_(i: int, entry_price: float) -> bool:
        below = c[i] < s50[i] * lo and (buffer or c[i - 1] >= s50[i - 1])
        return below or (take_profit is not None and c[i] >= entry_price * (1 + take_profit))

    return run_rules(c, entry, exit_, START, label, COMMISSION)


STRATEGIES = {
    "1 Video: SMA 50 cross": lambda c: run_sma_cross(c, 50, COMMISSION, start=START),
    "2 SMA 50 cross, only above SMA 200": lambda c: sma_variant(c, "", need_200=True),
    "3 SMA 50 cross with 2% buffer": lambda c: sma_variant(c, "", buffer=0.02),
    "4 SMA 50 cross + 5% take-profit": lambda c: sma_variant(c, "", take_profit=0.05),
    "5 RSI(2) dip-buy above SMA 200": lambda c: run_rsi2_dip(c, COMMISSION, start=START),
    "6 RSI(2) dip-buy + 10% stop": lambda c: run_rsi2_dip(c, COMMISSION, stop_pct=10, start=START),
}


def buy_hold(c: list[float]) -> tuple[float, float]:
    base, peak, worst = c[START], c[START], 0.0
    for x in c[START:]:
        peak = max(peak, x)
        worst = max(worst, 1 - x / peak)
    return (c[-1] / base - 1) * 100, worst * 100


def main() -> None:
    fetch()
    data = markets()
    for name, fn in STRATEGIES.items():
        print(f"\n== {name}")
        wins = trades = beat = lost = 0
        for market, closes in data.items():
            r = fn(closes)
            bh, bh_dd = buy_hold(closes)
            wins += r.wins
            trades += r.trades
            beat += r.net_pct > bh
            lost += r.net_pct < 0
            print(f"  {market:16} trades {r.trades:3}  losing {100 - r.win_rate:5.1f}%  "
                  f"return {r.net_pct:7.1f}%  max drop {r.max_drawdown_pct:5.1f}%  in market {r.exposure_pct:3.0f}%"
                  f"  | buy&hold {bh:7.1f}%, max drop {bh_dd:5.1f}%")
        print(f"  ALL: losing trades {100 - wins / trades * 100:.1f}% of {trades}; "
              f"lost money on {lost}/{len(data)} markets; beat buy&hold on {beat}/{len(data)}")


if __name__ == "__main__":
    main()
