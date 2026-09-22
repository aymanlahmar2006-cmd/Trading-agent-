"""Fibonacci retracement and extension from the last significant swing.

The levels themselves are arithmetic; the judgement is which swing to measure.
Measuring the wrong leg produces levels that look authoritative and mean
nothing, so the swing is taken from confirmed pivots -- the same ones the stop
logic uses -- and the reading is refused outright when no clean leg exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .indicators import Pivot
from .schema import Bar

RETRACEMENTS = (0.236, 0.382, 0.5, 0.618, 0.786)
EXTENSIONS = (1.272, 1.618, 2.0)
# The 0.5-0.618 band, where a trend pullback most often ends.
GOLDEN = (0.5, 0.618)


@dataclass
class FibSwing:
    """One measured leg and the levels hanging off it."""

    low: float
    high: float
    direction: str                       # "up" when the leg ran low -> high
    low_index: int
    high_index: int
    levels: dict[float, float] = field(default_factory=dict)
    extensions: dict[float, float] = field(default_factory=dict)

    @property
    def size(self) -> float:
        return self.high - self.low

    def retracement_of(self, price: float) -> float | None:
        """How far price has retraced the leg, as a fraction. 0 = no giveback."""
        if self.size <= 0:
            return None
        if self.direction == "up":
            return (self.high - price) / self.size
        return (price - self.low) / self.size

    def in_golden_zone(self, price: float) -> bool:
        fraction = self.retracement_of(price)
        return fraction is not None and GOLDEN[0] <= fraction <= GOLDEN[1]

    @property
    def golden_band(self) -> tuple[float, float]:
        """The price range of the 0.5-0.618 pullback, low value first."""
        a, b = self.levels[GOLDEN[0]], self.levels[GOLDEN[1]]
        return (min(a, b), max(a, b))


def last_swing(pivots: list[Pivot], bars: list[Bar],
               min_size_atr: float = 1.5, atr: float | None = None
               ) -> FibSwing | None:
    """The most recent confirmed leg worth measuring.

    Takes the last two opposite pivots. A leg smaller than ``min_size_atr`` of
    ATR is noise, and levels drawn on noise are worse than none -- so it is
    rejected rather than measured.
    """
    if len(pivots) < 2:
        return None

    last = pivots[-1]
    previous = next((p for p in reversed(pivots[:-1]) if p.kind != last.kind), None)
    if previous is None:
        return None

    if last.kind == "high":
        low, high = previous, last
        direction = "up"
    else:
        low, high = last, previous
        direction = "down"

    size = high.price - low.price
    if size <= 0:
        return None
    if atr is not None and size < min_size_atr * atr:
        return None

    swing = FibSwing(low=low.price, high=high.price, direction=direction,
                     low_index=low.index, high_index=high.index)

    for ratio in RETRACEMENTS:
        # Retracing an up-leg means giving back from the high; a down-leg from
        # the low. Getting this backwards puts every level on the wrong side.
        swing.levels[ratio] = (high.price - size * ratio if direction == "up"
                               else low.price + size * ratio)
    for ratio in EXTENSIONS:
        swing.extensions[ratio] = (low.price + size * ratio if direction == "up"
                                   else high.price - size * ratio)
    return swing


def support_levels(swing: FibSwing, price: float) -> list[float]:
    return sorted({lv for lv in swing.levels.values() if lv < price}, reverse=True)


def resistance_levels(swing: FibSwing, price: float) -> list[float]:
    candidates = set(lv for lv in swing.levels.values() if lv > price)
    candidates |= {lv for lv in swing.extensions.values() if lv > price}
    if swing.high > price:
        candidates.add(swing.high)
    return sorted(candidates)
