"""Deterministic math over raw bars.

These functions exist so that stop levels, targets and volatility are *computed*
from the candles TradingView returned rather than eyeballed. Every one of them
returns ``None`` when there is not enough history, which the engine surfaces as
a data-quality warning instead of filling in a plausible number.
"""

from __future__ import annotations

from dataclasses import dataclass

from .schema import Bar


@dataclass(frozen=True)
class Pivot:
    """A confirmed swing point."""

    index: int
    price: float
    kind: str  # "high" | "low"


def true_range(current: Bar, previous: Bar | None) -> float:
    if previous is None:
        return current.range
    return max(
        current.high - current.low,
        abs(current.high - previous.close),
        abs(current.low - previous.close),
    )


def atr(bars: list[Bar], period: int = 14) -> float | None:
    """Wilder-smoothed Average True Range over the most recent ``period`` bars."""
    if len(bars) < period + 1:
        return None

    ranges = [true_range(bars[i], bars[i - 1] if i > 0 else None)
              for i in range(len(bars))]

    # Seed with a simple mean of the first `period` true ranges, then smooth.
    value = sum(ranges[1:period + 1]) / period
    for tr in ranges[period + 1:]:
        value = (value * (period - 1) + tr) / period
    return value if value > 0 else None


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = value * k + result * (1 - k)
    return result


def ema_series(values: list[float], period: int) -> list[float]:
    """Full EMA series, left-padded so indices line up with ``values``."""
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out = [seed]
    for value in values[period:]:
        out.append(value * k + out[-1] * (1 - k))
    return out


def find_pivots(bars: list[Bar], lookback: int = 3) -> list[Pivot]:
    """Fractal pivots: a high with ``lookback`` lower highs on both sides.

    The last ``lookback`` bars can never be confirmed pivots, which is exactly
    why stops built on them are not repainted by the bar currently forming.
    """
    pivots: list[Pivot] = []
    if len(bars) < lookback * 2 + 1:
        return pivots

    for i in range(lookback, len(bars) - lookback):
        window = bars[i - lookback:i + lookback + 1]
        centre = bars[i]
        if all(centre.high >= b.high for b in window) and any(
            centre.high > b.high for b in window
        ):
            pivots.append(Pivot(index=i, price=centre.high, kind="high"))
        if all(centre.low <= b.low for b in window) and any(
            centre.low < b.low for b in window
        ):
            pivots.append(Pivot(index=i, price=centre.low, kind="low"))
    return _collapse_adjacent(pivots, lookback)


def _collapse_adjacent(pivots: list[Pivot], lookback: int) -> list[Pivot]:
    """Merge same-kind pivots that describe one turning point.

    Equal or near-equal highs on consecutive bars (a flat top, a doji, an
    open-equals-previous-close bar) each satisfy the fractal test, so one swing
    gets reported two or three times. Left in, the "last two highs" a structure
    read compares are two copies of the same high, and an uptrend reads as a
    downtrend. Keep the most extreme bar of each cluster.
    """
    merged: list[Pivot] = []
    for pivot in pivots:
        previous = next((p for p in reversed(merged) if p.kind == pivot.kind), None)
        if previous is not None and pivot.index - previous.index <= lookback:
            is_more_extreme = (
                pivot.price > previous.price if pivot.kind == "high"
                else pivot.price < previous.price
            )
            if is_more_extreme:
                merged[merged.index(previous)] = pivot
            continue
        merged.append(pivot)
    return sorted(merged, key=lambda p: p.index)


def last_pivot(pivots: list[Pivot], kind: str) -> Pivot | None:
    for pivot in reversed(pivots):
        if pivot.kind == kind:
            return pivot
    return None


def swing_structure(pivots: list[Pivot]) -> str:
    """Classify market structure from the last two highs and two lows.

    Returns "higher_highs", "lower_lows", "mixed" or "insufficient".
    """
    highs = [p.price for p in pivots if p.kind == "high"][-2:]
    lows = [p.price for p in pivots if p.kind == "low"][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return "insufficient"

    hh = highs[-1] > highs[-2]
    hl = lows[-1] > lows[-2]
    if hh and hl:
        return "higher_highs"
    if not hh and not hl:
        return "lower_lows"
    return "mixed"


def nearest_level_below(price: float, levels: list[float]) -> float | None:
    candidates = [lv for lv in levels if lv < price]
    return max(candidates) if candidates else None


def nearest_level_above(price: float, levels: list[float]) -> float | None:
    candidates = [lv for lv in levels if lv > price]
    return min(candidates) if candidates else None


def dedupe_levels(levels: list[float], tolerance: float) -> list[float]:
    """Collapse levels that sit within ``tolerance`` of each other.

    Pine lines and pivots routinely mark the same shelf twice; without this the
    "nearest resistance" is whichever duplicate happened to be listed first.
    """
    if tolerance <= 0:
        return sorted(set(levels), reverse=True)

    out: list[float] = []
    for level in sorted(levels, reverse=True):
        if not out or abs(out[-1] - level) > tolerance:
            out.append(level)
    return out
