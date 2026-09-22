import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crypto_agent import indicators as ind
from crypto_agent import liquidity as liq
from crypto_agent.schema import parse_bar
from tests.helpers import bars_from_path


def _bars(payloads):
    return [parse_bar(p, i) for i, p in enumerate(payloads)]


def _setup(path, steps=14):
    bars = _bars(bars_from_path(path, steps=steps))
    pivots = ind.find_pivots(bars, 3)
    return bars, pivots, ind.atr(bars, 14)


def test_pools_are_split_by_side_of_price():
    bars, pivots, atr = _setup([100, 110, 104, 118, 111, 126, 118])
    price = bars[-1].close
    pools = liq.find_pools(bars, pivots, price, atr)

    for pool in pools:
        if pool.side == liq.BUY_SIDE:
            assert pool.price > price
        else:
            assert pool.price < price


def test_equal_lows_are_counted_as_one_cluster():
    """Two lows at the same price is the obvious stop shelf, not two levels."""
    bars, pivots, atr = _setup([100, 110, 100, 110, 100, 112, 106])
    pools = liq.find_pools(bars, pivots, bars[-1].close, atr)
    equal = [p for p in pools if p.is_equal_level]
    assert equal, f"expected a repeated level, got {[(p.price, p.touches) for p in pools]}"


def test_a_single_pivot_is_not_an_equal_level():
    bars, pivots, atr = _setup([100, 110, 104, 118, 111, 126, 118])
    pools = liq.find_pools(bars, pivots, bars[-1].close, atr)
    assert any(not p.is_equal_level for p in pools)


def test_no_pools_without_volatility():
    bars, pivots, _ = _setup([100, 110, 104, 118])
    assert liq.find_pools(bars, pivots, 110.0, atr=0.0) == []
    assert liq.find_pools([], pivots, 110.0, atr=1.0) == []


def test_a_sweep_is_a_break_that_closed_back():
    """Trading through a level and closing back is not the same as breaking it."""
    bars = _bars([
        {"time": i, "open": 100, "high": 101, "low": 99, "close": 100}
        for i in range(5)
    ] + [
        # Wicks below 95 but closes back above it.
        {"time": 5, "open": 100, "high": 101, "low": 94, "close": 100},
    ])
    assert liq._was_swept(bars, 95.0, liq.SELL_SIDE, lookback=3)
    # A bar that closed below the level is a break, not a sweep.
    broken = bars[:-1] + _bars([{"time": 6, "open": 100, "high": 101,
                                 "low": 94, "close": 94.5}])
    assert not liq._was_swept(broken, 95.0, liq.SELL_SIDE, lookback=1)


def test_recent_sweep_only_reports_below_price():
    """A spot long can act on stops taken below, not above."""
    bars, pivots, atr = _setup([100, 110, 100, 110, 100, 112, 106])
    sweep = liq.recent_sweep(bars, pivots, bars[-1].close, atr, lookback=40)
    if sweep is not None:
        assert sweep.side == liq.SELL_SIDE
        assert sweep.price < bars[-1].close


def test_a_stop_just_above_untouched_equal_lows_is_flagged():
    """The move that collects those stops takes yours on the way."""
    pools = [liq.Pool(price=100.0, side=liq.SELL_SIDE, touches=2, swept=False)]
    assert liq.stop_hazard(pools, stop=99.8, atr=2.0) is not None
    # Far enough below, and it is no longer in the path.
    assert liq.stop_hazard(pools, stop=90.0, atr=2.0) is None


def test_a_swept_pool_is_no_longer_a_hazard():
    pools = [liq.Pool(price=100.0, side=liq.SELL_SIDE, touches=2, swept=True)]
    assert liq.stop_hazard(pools, stop=99.8, atr=2.0) is None


def test_a_single_low_is_not_hazard_enough():
    pools = [liq.Pool(price=100.0, side=liq.SELL_SIDE, touches=1, swept=False)]
    assert liq.stop_hazard(pools, stop=99.8, atr=2.0) is None


def test_nearest_pool_picks_the_first_of_its_side():
    pools = [
        liq.Pool(price=120.0, side=liq.BUY_SIDE, touches=1, swept=False),
        liq.Pool(price=90.0, side=liq.SELL_SIDE, touches=2, swept=False),
    ]
    assert liq.nearest_pool(pools, liq.BUY_SIDE).price == 120.0
    assert liq.nearest_pool(pools, liq.SELL_SIDE).price == 90.0
    assert liq.nearest_pool([], liq.BUY_SIDE) is None
