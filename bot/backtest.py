"""Backtest strategies on a CSV exported from TradingView. Long or flat, all-in, fills at the close.

Strategies:
  rsi2  (pine/rsi2_dip_strategy.pine): buy when close > 200 SMA and RSI(2) < 10,
        sell when close > 5 SMA.
  sma   (pine/sma_cross_strategy.pine, the video's rules): buy when a candle closes above the SMA
        after closing at/below it, sell when a candle closes below it.

Usage:
  python -m bot.backtest SPY_1D.csv --strategy rsi2 --commission 0.1 --cash 10000
  python -m bot.backtest BITSTAMP_BTCUSD_1D.csv --strategy sma --sma 50

Export the CSV in TradingView: chart menu (top-left arrow next to the symbol) > "Export chart data".
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


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
    bars_in_market: int = 0
    bars_total: int = 0

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
    def avg_win_pct(self) -> float:
        return self.gross_win / self.wins / self.start_equity * 100 if self.wins else 0.0

    @property
    def exposure_pct(self) -> float:
        return self.bars_in_market / self.bars_total * 100 if self.bars_total else 0.0

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


def rsi(values: list[float], length: int) -> list[float | None]:
    """Wilder's RSI, same as TradingView's ta.rsi."""
    out: list[float | None] = [None] * len(values)
    avg_gain = avg_loss = 0.0
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gain, loss = max(change, 0.0), max(-change, 0.0)
        if i <= length:
            avg_gain += gain / length
            avg_loss += loss / length
        else:
            avg_gain = (avg_gain * (length - 1) + gain) / length
            avg_loss = (avg_loss * (length - 1) + loss) / length
        if i >= length:
            out[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return out


EntryRule = Callable[[int], bool]
ExitRule = Callable[[int, float], bool]  # (bar index, entry price)


def run_rules(closes: list[float], entry: EntryRule, exit_: ExitRule, start: int, label: str,
              commission_pct: float = 0.0, cash: float = 10_000.0) -> Result:
    """Simulate long/flat, all-in trading from bar `start`. Trade P&L includes commission."""
    if len(closes) <= start + 1:
        raise ValueError(f"need more than {start + 1} candles, got {len(closes)}")
    c = commission_pct / 100
    start_cash = cash
    qty = entry_cost = entry_price = 0.0
    trades = wins = in_market = 0
    gross_win = gross_loss = 0.0
    curve = []
    for i in range(start, len(closes)):
        price = closes[i]
        if qty == 0:
            if entry(i):
                entry_cost, entry_price = cash, price
                qty = cash / (price * (1 + c))
                cash = 0.0
        elif exit_(i, entry_price):
            cash = qty * price * (1 - c)
            pnl = cash - entry_cost
            trades += 1
            if pnl > 0:
                wins += 1
                gross_win += pnl
            else:
                gross_loss += -pnl
            qty = 0.0
        in_market += qty > 0
        curve.append(cash + qty * price)
    return Result(label, start_cash, curve[-1], trades, wins, gross_win, gross_loss,
                  _max_drawdown_pct(curve), in_market, len(curve))


def run_sma_cross(closes: list[float], length: int = 50, commission_pct: float = 0.0,
                  cash: float = 10_000.0, start: int | None = None) -> Result:
    """The video's rules: buy on a close above the SMA, sell on a close below it."""
    if length < 2:
        raise ValueError("SMA length must be >= 2")
    if len(closes) <= length:
        raise ValueError(f"need more than {length} candles, got {len(closes)}")
    avg = sma(closes, length)

    def entry(i: int) -> bool:
        return closes[i] > avg[i] and closes[i - 1] <= avg[i - 1]

    def exit_(i: int, _entry_price: float) -> bool:
        return closes[i] < avg[i] and closes[i - 1] >= avg[i - 1]

    return run_rules(closes, entry, exit_, length if start is None else start,
                     f"SMA {length} cross, {commission_pct:g}% commission", commission_pct, cash)


def run_rsi2_dip(closes: list[float], commission_pct: float = 0.0, cash: float = 10_000.0,
                 trend_len: int = 200, rsi_len: int = 2, rsi_buy: float = 10, exit_len: int = 5,
                 stop_pct: float | None = None, start: int | None = None) -> Result:
    """Buy short dips in a long-term uptrend: close > SMA(trend_len) and RSI(rsi_len) < rsi_buy.
    Sell on the first close above SMA(exit_len), or at an optional % stop below the entry."""
    trend, quick, r = sma(closes, trend_len), sma(closes, exit_len), rsi(closes, rsi_len)

    def entry(i: int) -> bool:
        return trend[i] is not None and r[i] is not None and closes[i] > trend[i] and r[i] < rsi_buy

    def exit_(i: int, entry_price: float) -> bool:
        stopped = stop_pct is not None and closes[i] <= entry_price * (1 - stop_pct / 100)
        return closes[i] > quick[i] or stopped

    return run_rules(closes, entry, exit_, trend_len if start is None else start,
                     f"RSI(2) dip-buy, {commission_pct:g}% commission", commission_pct, cash)


def run_buy_and_hold(closes: list[float], length: int = 50, commission_pct: float = 0.0,
                     cash: float = 10_000.0) -> Result:
    """Buy once on the first bar the strategy could trade (bar `length`), hold to the end."""
    c = commission_pct / 100
    qty = cash / (closes[length] * (1 + c))
    curve = [qty * p for p in closes[length:]]
    return Result("Buy and hold", cash, curve[-1], 0, 0, 0.0, 0.0, _max_drawdown_pct(curve),
                  len(curve), len(curve))


def format_result(r: Result) -> str:
    lines = [
        r.label,
        f"  Net profit:     ${r.net_profit:,.2f} ({r.net_pct:,.1f}%)",
        f"  Max drawdown:   {r.max_drawdown_pct:.1f}%",
    ]
    if r.trades:
        pf = "inf" if r.profit_factor == float("inf") else f"{r.profit_factor:.2f}"
        lines += [f"  Closed trades:  {r.trades}  (win rate {r.win_rate:.1f}%, profit factor {pf})",
                  f"  Time in market: {r.exposure_pct:.0f}%"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="CSV with a 'close' column (TradingView export)")
    ap.add_argument("--strategy", choices=["rsi2", "sma"], default="rsi2")
    ap.add_argument("--sma", type=int, default=50, help="SMA length for --strategy sma")
    ap.add_argument("--commission", type=float, default=0.1, help="percent per buy and per sell")
    ap.add_argument("--cash", type=float, default=10_000)
    a = ap.parse_args(argv)
    closes = load_closes(a.csv)
    if a.strategy == "sma":
        warmup = a.sma
        results = [run_sma_cross(closes, a.sma, 0.0, a.cash), run_sma_cross(closes, a.sma, a.commission, a.cash)]
    else:
        warmup = 200
        results = [run_rsi2_dip(closes, 0.0, a.cash), run_rsi2_dip(closes, a.commission, a.cash)]
    results.append(run_buy_and_hold(closes, warmup, a.commission, a.cash))
    print(f"{len(closes)} candles, starting with ${a.cash:,.2f}\n")
    print("\n\n".join(format_result(r) for r in results))
    if results[1].trades < 30:
        print(f"\nWarning: only {results[1].trades} closed trades. That is too few to trust the result.")


if __name__ == "__main__":
    main()
