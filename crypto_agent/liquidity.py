"""Where stop orders are resting, and whether price has already taken them.

Stops cluster just beyond obvious levels: under a swing low, above a swing
high, and especially beyond two or more highs or lows at the same price, which
every chart reader can see. Those clusters are liquidity -- the resting orders a
large move needs in order to fill.

Two things follow that the other modules do not capture:

  * a level with stops under it is a level price is drawn toward, not a level
    that reliably holds, so it is a poor place to put a stop of your own;
  * a move that takes out such a cluster and then closes back above it is a
    sweep -- the stops were filled and price rejected -- which is a different
    event from a level simply breaking.
"""

from __future__ import annotations

from dataclasses import dataclass

from .indicators import Pivot
from .schema import Bar

BUY_SIDE = "buy_side"     # above price: stops of shorts, and breakout buys
SELL_SIDE = "sell_side"   # below price: stops of longs


@dataclass(frozen=True)
class Pool:
    """A price level with resting orders beyond it."""

    price: float
    side: str
    touches: int          # how many pivots formed at this level
    swept: bool           # price traded through it and closed back

    @property
    def is_equal_level(self) -> bool:
        """Two or more pivots at the same price -- the obvious kind."""
        return self.touches >= 2


def _cluster(pivots: list[Pivot], tolerance: float) -> list[tuple[float, int]]:
    """Group pivot prices that sit within ``tolerance`` of each other."""
    if not pivots:
        return []
    groups: list[list[float]] = []
    for price in sorted(p.price for p in pivots):
        if groups and abs(price - groups[-1][-1]) <= tolerance:
            groups[-1].append(price)
        else:
            groups.append([price])
    return [(sum(g) / len(g), len(g)) for g in groups]


def _was_swept(bars: list[Bar], level: float, side: str, lookback: int) -> bool:
    """Did price trade beyond ``level`` and close back on the original side?"""
    for bar in bars[-lookback:]:
        if side == SELL_SIDE and bar.low < level <= bar.close:
            return True
        if side == BUY_SIDE and bar.high > level >= bar.close:
            return True
    return False


def find_pools(bars: list[Bar], pivots: list[Pivot], price: float,
               atr: float, lookback: int = 10) -> list[Pool]:
    """Liquidity above and below the current price, most significant first."""
    if atr <= 0 or not bars:
        return []
    tolerance = atr * 0.25

    pools: list[Pool] = []
    for kind, side in (("high", BUY_SIDE), ("low", SELL_SIDE)):
        for level, touches in _cluster([p for p in pivots if p.kind == kind],
                                       tolerance):
            if side == BUY_SIDE and level <= price:
                continue
            if side == SELL_SIDE and level >= price:
                continue
            pools.append(Pool(
                price=level, side=side, touches=touches,
                swept=_was_swept(bars, level, side, lookback)))

    # Equal levels first, then nearest -- that is the order they matter in.
    pools.sort(key=lambda p: (-p.touches, abs(p.price - price)))
    return pools


def recent_sweep(bars: list[Bar], pivots: list[Pivot], price: float,
                 atr: float, lookback: int = 10) -> Pool | None:
    """A sell-side pool taken and reclaimed -- stops filled, price rejected.

    This is the constructive version of a broken low: the level did not fail,
    it was used. Only reported below price, since that is the one a spot long
    can act on.
    """
    for pool in find_pools(bars, pivots, price, atr, lookback):
        if pool.side == SELL_SIDE and pool.swept:
            return pool
    return None


def nearest_pool(pools: list[Pool], side: str) -> Pool | None:
    matching = [p for p in pools if p.side == side]
    return matching[0] if matching else None


def stop_hazard(pools: list[Pool], stop: float, atr: float) -> Pool | None:
    """An untouched sell-side cluster sitting just above a proposed stop.

    Placing a stop above resting liquidity means the move that collects those
    stops takes yours on the way, before any real invalidation.
    """
    for pool in pools:
        if pool.side != SELL_SIDE or pool.swept:
            continue
        if 0 < pool.price - stop < atr * 0.5 and pool.is_equal_level:
            return pool
    return None
