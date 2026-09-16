"""Ichimoku Kinko Hyo, computed from the same bars the chart draws.

The engine's other inputs are moving averages and oscillators. Ichimoku is a
different reading of the same price -- and when a trader has the cloud on their
chart, it is the reading they actually act on. An engine that ignores it can
call a trend the user's own screen contradicts.

Displacement is the part most implementations get wrong. Senkou A and B are
plotted 26 bars *forward*, so the cloud sitting under the current candle was
computed 26 bars ago. Comparing today's price against today's raw spans reads a
cloud that is not on the chart yet.
"""

from __future__ import annotations

from dataclasses import dataclass

from .schema import Bar

TENKAN_PERIOD = 9
KIJUN_PERIOD = 26
SENKOU_B_PERIOD = 52
DISPLACEMENT = 26

ABOVE = "above"
INSIDE = "inside"
BELOW = "below"


@dataclass(frozen=True)
class Ichimoku:
    """The reading at the most recent bar."""

    tenkan: float
    kijun: float
    # The cloud as displayed under the current candle.
    senkou_a: float
    senkou_b: float
    # Current close vs the close DISPLACEMENT bars back, the lagging-span check.
    chikou_above_past_price: bool | None

    @property
    def cloud_top(self) -> float:
        return max(self.senkou_a, self.senkou_b)

    @property
    def cloud_bottom(self) -> float:
        return min(self.senkou_a, self.senkou_b)

    @property
    def cloud_is_bullish(self) -> bool:
        """Senkou A above Senkou B -- the cloud a chart draws in green."""
        return self.senkou_a > self.senkou_b

    def price_position(self, price: float) -> str:
        if price > self.cloud_top:
            return ABOVE
        if price < self.cloud_bottom:
            return BELOW
        return INSIDE

    @property
    def tk_bullish(self) -> bool:
        return self.tenkan > self.kijun


def _midpoint(bars: list[Bar], period: int, index: int) -> float | None:
    """(highest high + lowest low) / 2 over ``period`` bars ending at ``index``."""
    start = index - period + 1
    if start < 0 or index >= len(bars):
        return None
    window = bars[start:index + 1]
    return (max(b.high for b in window) + min(b.low for b in window)) / 2.0


def minimum_bars() -> int:
    """Bars needed for a complete reading, displacement included."""
    return SENKOU_B_PERIOD + DISPLACEMENT


def compute(bars: list[Bar]) -> Ichimoku | None:
    """Read Ichimoku at the last bar, or None when history is too short."""
    if len(bars) < minimum_bars():
        return None

    last = len(bars) - 1
    tenkan = _midpoint(bars, TENKAN_PERIOD, last)
    kijun = _midpoint(bars, KIJUN_PERIOD, last)
    if tenkan is None or kijun is None:
        return None

    # The spans under today's candle were computed DISPLACEMENT bars ago.
    source = last - DISPLACEMENT
    past_tenkan = _midpoint(bars, TENKAN_PERIOD, source)
    past_kijun = _midpoint(bars, KIJUN_PERIOD, source)
    senkou_b = _midpoint(bars, SENKOU_B_PERIOD, source)
    if past_tenkan is None or past_kijun is None or senkou_b is None:
        return None
    senkou_a = (past_tenkan + past_kijun) / 2.0

    chikou: bool | None = None
    past_index = last - DISPLACEMENT
    if past_index >= 0:
        chikou = bars[last].close > bars[past_index].close

    return Ichimoku(
        tenkan=tenkan,
        kijun=kijun,
        senkou_a=senkou_a,
        senkou_b=senkou_b,
        chikou_above_past_price=chikou,
    )


def from_studies(studies: dict[str, float]) -> Ichimoku | None:
    """Build a reading from values the chart itself reported, if all are there.

    Chart values are preferred because they are literally what the user sees,
    displacement already applied.
    """
    needed = ("tenkan", "kijun", "senkou_a", "senkou_b")
    if not all(key in studies for key in needed):
        return None
    return Ichimoku(
        tenkan=studies["tenkan"],
        kijun=studies["kijun"],
        senkou_a=studies["senkou_a"],
        senkou_b=studies["senkou_b"],
        # The chart reports the lagging span's value, not the comparison, so the
        # bar-based check stays the source for it.
        chikou_above_past_price=None,
    )


def support_levels(reading: Ichimoku, price: float) -> list[float]:
    """Ichimoku levels below price that a trader would actually lean on."""
    candidates = [reading.kijun, reading.tenkan,
                  reading.cloud_top, reading.cloud_bottom]
    return [level for level in candidates if level < price]


def resistance_levels(reading: Ichimoku, price: float) -> list[float]:
    candidates = [reading.kijun, reading.tenkan,
                  reading.cloud_bottom, reading.cloud_top]
    return [level for level in candidates if level > price]
