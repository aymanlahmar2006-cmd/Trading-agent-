import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crypto_agent import indicators as ind
from crypto_agent.schema import Bar, parse_bar
from tests.helpers import bars_from_path


def _bars(payloads):
    return [parse_bar(p, i) for i, p in enumerate(payloads)]


def test_atr_returns_none_without_enough_history():
    bars = _bars(bars_from_path([100, 101], steps=3))
    assert ind.atr(bars, period=14) is None


def test_atr_is_positive_and_scales_with_range():
    tight = _bars(bars_from_path([100, 101, 100, 101, 100], steps=6, wick=0.1))
    wide = _bars(bars_from_path([100, 101, 100, 101, 100], steps=6, wick=2.0))
    assert ind.atr(tight, 14) is not None
    assert ind.atr(wide, 14) > ind.atr(tight, 14)


def test_find_pivots_confirms_turning_points_only():
    bars = _bars(bars_from_path([100, 110, 104, 118], steps=6))
    pivots = ind.find_pivots(bars, lookback=3)
    kinds = [p.kind for p in pivots]
    assert "high" in kinds and "low" in kinds
    # The final bars cannot be confirmed pivots -- that is what stops repainting.
    assert all(p.index <= len(bars) - 4 for p in pivots)


def test_swing_structure_reads_uptrend_and_downtrend():
    up = ind.find_pivots(_bars(bars_from_path([100, 110, 104, 118, 111, 126])), 3)
    down = ind.find_pivots(_bars(bars_from_path([126, 111, 118, 104, 110, 100])), 3)
    assert ind.swing_structure(up) == "higher_highs"
    assert ind.swing_structure(down) == "lower_lows"


def test_swing_structure_insufficient_without_pivots():
    assert ind.swing_structure([]) == "insufficient"


def test_dedupe_collapses_levels_inside_tolerance():
    assert ind.dedupe_levels([100.0, 100.4, 100.8, 105.0], tolerance=1.0) == [105.0, 100.8]


def test_nearest_levels():
    levels = [90.0, 95.0, 105.0, 110.0]
    assert ind.nearest_level_below(100.0, levels) == 95.0
    assert ind.nearest_level_above(100.0, levels) == 105.0
    assert ind.nearest_level_below(80.0, levels) is None


def test_pivots_are_not_double_counted_on_flat_turns():
    """One turning point must yield one pivot, even with equal adjacent highs.

    Regression: duplicated pivots made swing_structure compare a high against a
    copy of itself, inverting the trend read.
    """
    bars = _bars(bars_from_path([100, 110, 104, 118, 111, 126]))
    pivots = ind.find_pivots(bars, lookback=3)
    prices = [(p.kind, p.price) for p in pivots]
    assert len(prices) == len(set(prices)), f"duplicate pivots: {prices}"
