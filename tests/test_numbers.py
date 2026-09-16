import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crypto_agent.schema import coerce_number, parse_snapshot
from tests.helpers import bars_from_path, make_snapshot
from tests.test_signal import BULLISH_PULLBACK


def test_tradingview_minus_sign_is_read_as_negative():
    """The bug that made the engine report a present MACD as absent.

    TradingView writes negatives with U+2212 MINUS SIGN, not an ASCII hyphen.
    """
    assert coerce_number("−0.53") == pytest.approx(-0.53)
    assert coerce_number("−1234.56") == pytest.approx(-1234.56)


def test_other_dashes_are_handled_too():
    assert coerce_number("–1.2") == pytest.approx(-1.2)   # en dash
    assert coerce_number("—1.2") == pytest.approx(-1.2)   # em dash
    assert coerce_number("－1.2") == pytest.approx(-1.2)   # fullwidth


def test_thousands_separators_do_not_break_parsing():
    assert coerce_number("1,234.5") == pytest.approx(1234.5)
    assert coerce_number("1 234.5") == pytest.approx(1234.5)   # nbsp
    assert coerce_number("1'234.5") == pytest.approx(1234.5)        # swiss


def test_non_latin_digits_parse():
    assert coerce_number("２３４") == pytest.approx(234)  # fullwidth
    assert coerce_number("٥٦٧") == pytest.approx(567)  # arabic-indic


def test_percent_suffix_is_stripped():
    assert coerce_number("12%") == pytest.approx(12.0)


def test_numbers_pass_through_unchanged():
    assert coerce_number(59.3) == 59.3
    assert coerce_number(7) == 7.0


def test_genuine_rubbish_still_raises():
    for value in ["", "   ", "n/a", "--", None, [1], {}]:
        with pytest.raises((ValueError, TypeError)):
            coerce_number(value)


def test_booleans_are_rejected_rather_than_read_as_one_and_zero():
    with pytest.raises(ValueError, match="boolean"):
        coerce_number(True)


def test_a_minus_signed_macd_reaches_the_signal_engine():
    """End to end: the value TradingView actually sends must survive parsing."""
    bars = bars_from_path(BULLISH_PULLBACK)
    payload = make_snapshot(bars, bars[-1]["close"],
                            {"RSI": "56.4", "MACD": "−0.53", "Signal": "−1.10"})
    snapshot = parse_snapshot(payload)

    assert snapshot.studies["macd"] == pytest.approx(-0.53)
    assert snapshot.studies["macd_signal"] == pytest.approx(-1.10)
    assert snapshot.errors == [], "a readable value must not raise a data error"


def test_an_unreadable_study_is_named_not_silently_dropped():
    """Regression: unparseable values were skipped, and the engine then said
    the indicator was 'not present on the chart' -- pointing the user at the
    wrong problem entirely."""
    bars = bars_from_path(BULLISH_PULLBACK)
    payload = make_snapshot(bars, bars[-1]["close"],
                            {"RSI": 56.4, "MACD": "n/a"})
    snapshot = parse_snapshot(payload)

    assert "macd" not in snapshot.studies
    assert any("MACD" in err and "n/a" in err for err in snapshot.errors), \
        f"the unreadable value must be reported, got {snapshot.errors}"


def test_an_unreadable_pine_line_is_reported():
    bars = bars_from_path(BULLISH_PULLBACK)
    payload = make_snapshot(bars, bars[-1]["close"], {"RSI": 56.4})
    payload["pine_lines"] = [126.0, "not a price"]
    snapshot = parse_snapshot(payload)

    assert snapshot.pine_lines == [126.0]
    assert any("not a price" in err for err in snapshot.errors)


def test_bars_with_typographic_minus_parse():
    payload = make_snapshot([
        {"time": 1, "open": "−1.5", "high": "−1.0",
         "low": "−2.0", "close": "−1.2", "volume": "1,000"},
    ], 1.0, {"RSI": 50.0})
    snapshot = parse_snapshot(payload)
    assert snapshot.bars[0].close == pytest.approx(-1.2)
    assert snapshot.bars[0].volume == pytest.approx(1000.0)
