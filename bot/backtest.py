"""Backtest the SMA-cross rules on a CSV exported from TradingView.

Rules (same as pine/sma_cross_strategy.pine with extras off):
  buy all-in when a candle closes above the SMA after closing at/below it,
  sell everything when a candle closes below the SMA. Long or flat, fills at the close.

Usage:
  python -m bot.backtest BITSTAMP_BTCUSD_1D.csv --sma 50 --commission 0.1 --cash 10000

Export the CSV in TradingView: chart menu (top-left arrow next to the symbol) > "Export chart data".
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Result:
    label: str
    start_equity: float
    end_equity: float
    trades: int
    wins: int
    gross_win: float
    gross_loss: float
    max_drawdown_pct: float

    @property
    def net_profit(self) -> float:
        return self.end_equity - self.start_equity

    @property
    def net_pct(self) -> float:
        return self.net_profit / self.start_equity * 100

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades * 100 if self.trades else 0.0

    @property
    def profit_factor(self) -> float:
        return self.gross_win / self.gross_loss if self.gross_loss else float("inf")


def load_closes(path: str | Path) -> list[float]:
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV is empty")
        col = next((c for c in reader.fieldnames if c.strip().lower() == "close"), None)
        if col is None:
            raise ValueError(f"CSV needs a 'close' column, found: {reader.fieldnames}")
        closes = []
        for row in reader:
            value = (row.get(col) or "").strip()
            if value and value.lower() != "nan":
                closes.append(float(value))
    return closes


def sma(values: list[float], length: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= length:
            total -= values[i - length]
        if i >= length - 1:
            out[i] = total / length
    return out


def _max_drawdown_pct(equity: list[float]) -> float:
    peak, worst = equity[0], 0.0
    for e in equity:
        peak = max(peak, e)
        worst = max(worst, (peak - e) / peak * 100 if peak > 0 else 0.0)
    return worst


def run_sma_cross(closes: list[float], length: int = 50, commission_pct: float = 0.0,
                  cash: float = 10_000.0) -> Result:
    if length < 2:
        raise ValueError("SMA length must be >= 2")
    if len(closes) <= length:
        raise ValueError(f"need more than {length} candles, got {len(closes)}")
    c = commission_pct / 100
    avg = sma(closes, length)
    start = cash
    qty = 0.0
    entry_cost = 0.0
    trades = wins = 0
    gross_win = gross_loss = 0.0
    curve = []
    for i in range(length, len(closes)):
        price, prev = closes[i], closes[i - 1]
        above, was_above = price > avg[i], prev > avg[i - 1]
        if qty == 0 and above and not was_above:
            entry_cost = cash
            qty = cash / (price * (1 + c))
            cash = 0.0
        elif qty > 0 and price < avg[i] and prev >= avg[i - 1]:
            cash = qty * price * (1 - c)
            pnl = cash - entry_cost
            trades += 1
            if pnl > 0:
                wins += 1
                gross_win += pnl
            else:
                gross_loss += -pnl
            qty = 0.0
        curve.append(cash + qty * price)
    label = f"SMA {length} cross, {commission_pct:g}% commission"
    return Result(label, start, curve[-1], trades, wins, gross_win, gross_loss, _max_drawdown_pct(curve))


def run_buy_and_hold(closes: list[float], length: int = 50, commission_pct: float = 0.0,
                     cash: float = 10_000.0) -> Result:
    """Buy once on the first bar the strategy could trade, hold to the end."""
    c = commission_pct / 100
    qty = cash / (closes[length] * (1 + c))
    curve = [qty * p for p in closes[length:]]
    return Result("Buy and hold", cash, curve[-1], 0, 0, 0.0, 0.0, _max_drawdown_pct(curve))


def format_result(r: Result) -> str:
    lines = [
        r.label,
        f"  Net profit:     ${r.net_profit:,.2f} ({r.net_pct:,.1f}%)",
        f"  Max drawdown:   {r.max_drawdown_pct:.1f}%",
    ]
    if r.trades:
        pf = "inf" if r.profit_factor == float("inf") else f"{r.profit_factor:.2f}"
        lines += [f"  Closed trades:  {r.trades}  (win rate {r.win_rate:.1f}%, profit factor {pf})"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="CSV with a 'close' column (TradingView export)")
    ap.add_argument("--sma", type=int, default=50)
    ap.add_argument("--commission", type=float, default=0.1, help="percent per buy and per sell")
    ap.add_argument("--cash", type=float, default=10_000)
    a = ap.parse_args(argv)
    closes = load_closes(a.csv)
    results = [
        run_sma_cross(closes, a.sma, 0.0, a.cash),
        run_sma_cross(closes, a.sma, a.commission, a.cash),
        run_buy_and_hold(closes, a.sma, a.commission, a.cash),
    ]
    print(f"{len(closes)} candles, starting with ${a.cash:,.2f}\n")
    print("\n\n".join(format_result(r) for r in results))
    if results[1].trades < 30:
        print(f"\nWarning: only {results[1].trades} closed trades. That is too few to trust the result.")


if __name__ == "__main__":
    main()
