import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crypto_agent import positions as pos


def make(entry=100.0, stop=95.0, size=10.0, fee=0.1, targets=None):
    book: list[pos.Position] = []
    return book, pos.open_position(book, "BINANCE:TESTUSDT", entry=entry, size=size,
                                   stop=stop, targets=targets or [], fee_pct=fee)


def test_r_is_measured_against_risk_at_entry():
    _, p = make(entry=100.0, stop=95.0, size=10.0, fee=0.0)
    assert p.total_risk == pytest.approx(50.0)
    # Exiting at the stop loses exactly 1R when there are no fees.
    assert p.r_at(95.0) == pytest.approx(-1.0)
    assert p.r_at(110.0) == pytest.approx(2.0)


def test_fees_are_charged_on_both_sides():
    _, free = make(fee=0.0)
    _, paid = make(fee=0.1)
    # Same exit, but the fee-paying position keeps less.
    assert paid.pnl_at(110.0) < free.pnl_at(110.0)
    # 0.1% a side on 10 units: 1.00 buying at 100, 1.10 selling at 110 = 2.10.
    assert free.pnl_at(110.0) - paid.pnl_at(110.0) == pytest.approx(2.10, abs=0.01)


def test_a_flat_exit_still_loses_the_fees():
    _, p = make(entry=100.0, fee=0.1)
    assert p.pnl_at(100.0) < 0, "closing at entry must not look like breakeven"


def test_stop_at_or_above_entry_is_rejected():
    book: list[pos.Position] = []
    with pytest.raises(pos.JournalError, match="at or above entry"):
        pos.open_position(book, "BINANCE:TESTUSDT", entry=100.0, size=1.0, stop=100.0)
    assert book == [], "a rejected position must not be recorded"


def test_target_below_entry_is_rejected():
    book: list[pos.Position] = []
    with pytest.raises(pos.JournalError, match="below entry"):
        pos.open_position(book, "BINANCE:TESTUSDT", entry=100.0, size=1.0,
                          stop=95.0, targets=[99.0])


def test_zero_size_is_rejected():
    book: list[pos.Position] = []
    with pytest.raises(pos.JournalError, match="size"):
        pos.open_position(book, "BINANCE:TESTUSDT", entry=100.0, size=0.0, stop=95.0)


def test_mae_and_mfe_track_the_extremes_not_the_last_price():
    _, p = make(entry=100.0, stop=95.0, size=10.0, fee=0.0)
    for price in (102.0, 97.0, 108.0, 101.0):
        pos.mark(p, price)
    assert p.worst_price == 97.0
    assert p.best_price == 108.0
    assert p.mae_r() == pytest.approx(-0.6)
    assert p.mfe_r() == pytest.approx(1.6)


def test_closing_records_the_exit_and_blocks_a_second_close():
    book, p = make()
    pos.close_position(p, 110.0, note="target")
    assert p.status == "closed" and p.exit == 110.0 and p.closed_at
    with pytest.raises(pos.JournalError, match="already closed"):
        pos.close_position(p, 111.0)


def test_stop_distance_pct_reaches_zero_at_the_stop():
    _, p = make(entry=100.0, stop=95.0)
    assert p.stop_distance_pct(100.0) == pytest.approx(100.0)
    assert p.stop_distance_pct(95.0) == pytest.approx(0.0)
    assert p.stop_distance_pct(96.0) == pytest.approx(20.0)


def test_round_trip_through_disk(tmp_path):
    book, p = make(targets=[120.0])
    path = tmp_path / "journal" / "positions.json"
    pos.save(book, path)
    reloaded = pos.load(path)
    assert len(reloaded) == 1
    assert reloaded[0].id == p.id
    assert reloaded[0].targets == [120.0]
    assert reloaded[0].r_at(110.0) == pytest.approx(p.r_at(110.0))


def test_load_missing_file_is_empty_not_an_error(tmp_path):
    assert pos.load(tmp_path / "nope.json") == []


def test_summary_reports_realised_expectancy():
    book: list[pos.Position] = []
    win = pos.open_position(book, "BINANCE:AAAUSDT", entry=100.0, size=10.0,
                            stop=95.0, fee_pct=0.0)
    loss = pos.open_position(book, "BINANCE:BBBUSDT", entry=100.0, size=10.0,
                             stop=95.0, fee_pct=0.0)
    pos.close_position(win, 110.0)    # +2R
    pos.close_position(loss, 95.0)    # -1R

    summary = pos.summarise(book)
    assert summary["closed_trades"] == 2
    assert summary["win_rate"] == 50.0
    assert summary["expectancy_r"] == pytest.approx(0.5)
    assert summary["total_r"] == pytest.approx(1.0)
    assert summary["profit_factor"] == pytest.approx(2.0)


def test_profit_factor_is_undefined_without_a_loss():
    book: list[pos.Position] = []
    p = pos.open_position(book, "BINANCE:AAAUSDT", entry=100.0, size=1.0, stop=95.0)
    pos.close_position(p, 110.0)
    assert pos.summarise(book)["profit_factor"] is None


def test_find_open_ignores_closed_and_matches_bare_symbol():
    book, p = make()
    assert pos.find_open(book, "TESTUSDT") is p
    pos.close_position(p, 110.0)
    assert pos.find_open(book, "BINANCE:TESTUSDT") is None
