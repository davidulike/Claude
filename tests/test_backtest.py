import pytest

from bot.backtest import load_closes, main, run_buy_and_hold, run_sma_cross, sma


def test_sma():
    assert sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]


def test_single_round_trip_math():
    # SMA(2): flat, cross up at 12, cross down at 8
    closes = [10, 10, 12, 14, 8]
    r = run_sma_cross(closes, 2, 0.0, 1000)
    assert r.trades == 1 and r.wins == 0
    assert r.end_equity == pytest.approx(1000 * 8 / 12)


def test_commission_reduces_profit():
    closes = [10, 10, 12, 20, 9, 9, 15, 30, 10]
    free = run_sma_cross(closes, 2, 0.0)
    paid = run_sma_cross(closes, 2, 1.0)
    assert free.trades == paid.trades == 2
    assert paid.end_equity < free.end_equity
    assert free.end_equity == pytest.approx(10_000 * (9 / 12) * (10 / 15))


def test_max_drawdown_and_buy_hold():
    closes = [100, 100, 100, 200, 100, 150]
    bh = run_buy_and_hold(closes, 2)
    assert bh.end_equity == pytest.approx(15_000)
    assert bh.max_drawdown_pct == pytest.approx(50)


def test_too_little_data():
    with pytest.raises(ValueError):
        run_sma_cross([1, 2, 3], 50)


def test_cli_with_tradingview_csv(tmp_path, capsys):
    p = tmp_path / "data.csv"
    rows = ["time,open,high,low,close,Volume"]
    rows += [f"{i},1,1,1,{100 + (i % 7) * 3},5" for i in range(120)]
    p.write_text("\n".join(rows))
    assert len(load_closes(p)) == 120
    main([str(p), "--sma", "5"])
    out = capsys.readouterr().out
    assert "Buy and hold" in out and "0.1% commission" in out


def test_csv_without_close(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError):
        load_closes(p)
