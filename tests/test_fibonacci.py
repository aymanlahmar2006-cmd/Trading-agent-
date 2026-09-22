import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crypto_agent import fibonacci as fib
from crypto_agent import indicators as ind
from crypto_agent.schema import parse_bar
from tests.helpers import bars_from_path


def _bars(payloads):
    return [parse_bar(p, i) for i, p in enumerate(payloads)]


def _swing(path, steps=14):
    bars = _bars(bars_from_path(path, steps=steps))
    pivots = ind.find_pivots(bars, 3)
    return fib.last_swing(pivots, bars, atr=ind.atr(bars, 14)), bars


def test_no_swing_without_two_opposite_pivots():
    bars = _bars(bars_from_path([100, 110], steps=5))
    assert fib.last_swing(ind.find_pivots(bars, 3), bars) is None
    assert fib.last_swing([], bars) is None


def test_a_leg_smaller_than_the_noise_floor_is_refused():
    """Levels drawn on a leg the size of one candle are decoration."""
    bars = _bars(bars_from_path([100, 100.4, 100.1, 100.5], steps=14))
    pivots = ind.find_pivots(bars, 3)
    big_atr = 50.0
    assert fib.last_swing(pivots, bars, atr=big_atr) is None


def test_retracement_levels_sit_inside_the_leg():
    swing, _ = _swing([100, 108, 103, 114, 109, 120, 114])
    assert swing is not None
    for ratio, level in swing.levels.items():
        assert swing.low <= level <= swing.high, f"{ratio} landed outside the leg"


def test_an_up_leg_retraces_down_from_the_high():
    swing, _ = _swing([100, 108, 103, 114, 109, 120, 114])
    assert swing.direction == "up"
    # A deeper ratio must sit lower in price.
    assert swing.levels[0.786] < swing.levels[0.5] < swing.levels[0.236]
    assert swing.levels[0.5] == pytest.approx((swing.high + swing.low) / 2)


def test_retracement_fraction_is_zero_at_the_high_and_one_at_the_low():
    swing, _ = _swing([100, 108, 103, 114, 109, 120, 114])
    assert swing.retracement_of(swing.high) == pytest.approx(0.0)
    assert swing.retracement_of(swing.low) == pytest.approx(1.0)


def test_the_golden_band_is_the_half_to_618_pullback():
    swing, _ = _swing([100, 108, 103, 114, 109, 120, 114])
    low, high = swing.golden_band
    assert low < high
    midpoint = (low + high) / 2
    assert swing.in_golden_zone(midpoint)
    assert not swing.in_golden_zone(swing.high)
    assert not swing.in_golden_zone(swing.low)


def test_extensions_project_beyond_the_leg():
    swing, _ = _swing([100, 108, 103, 114, 109, 120, 114])
    assert all(level > swing.high for level in swing.extensions.values())
    assert swing.extensions[1.618] > swing.extensions[1.272]


def test_levels_are_split_by_side_of_price():
    swing, _ = _swing([100, 108, 103, 114, 109, 120, 114])
    price = (swing.low + swing.high) / 2
    assert all(level < price for level in fib.support_levels(swing, price))
    assert all(level > price for level in fib.resistance_levels(swing, price))


def test_a_down_leg_measures_recovery_from_the_low():
    swing, _ = _swing([126, 118, 122, 110, 114, 102, 108])
    assert swing is not None and swing.direction == "down"
    assert swing.retracement_of(swing.low) == pytest.approx(0.0)
    assert swing.retracement_of(swing.high) == pytest.approx(1.0)


def test_a_zero_width_leg_yields_no_fraction():
    swing = fib.FibSwing(low=100.0, high=100.0, direction="up",
                         low_index=0, high_index=1)
    assert swing.retracement_of(100.0) is None
    assert not swing.in_golden_zone(100.0)
