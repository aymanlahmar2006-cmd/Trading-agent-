"""Signal generation for crypto spot.

Spot-only constraint
--------------------
On spot you can only profit from price going up. A bearish read therefore does
not produce a "short" idea -- it produces *no trade*. Downtrending symbols are
routed to the watch list with the bearish reading stated, and the engine never
emits a sell-side entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from . import indicators as ind
from .formatting import fmt_price
from .schema import Snapshot

BULLISH = "bullish"
BEARISH = "bearish"
NEUTRAL = "neutral"

CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass
class Vote:
    """One directional input, with the numbers that produced it."""

    name: str
    direction: str
    detail: str
    weight: float = 1.0


@dataclass
class TradePlan:
    entry_low: float
    entry_high: float
    stop: float
    target: float
    risk_reward: float
    stop_basis: str
    target_basis: str
    entry_basis: str
    distance_to_entry_atr: float


@dataclass
class SymbolAnalysis:
    symbol: str
    timeframe: str
    collected_at: str
    price: float
    trend: str
    trend_strength: str
    actionable: bool
    confidence: str
    quality_score: float
    votes: list[Vote] = field(default_factory=list)
    plan: TradePlan | None = None
    reasoning: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rejected_reason: str | None = None
    atr: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["votes"] = [asdict(v) for v in self.votes]
        data["plan"] = asdict(self.plan) if self.plan else None
        return data


def _ema_inputs(snap: Snapshot) -> tuple[dict[str, float], str, list[str]]:
    """Resolve EMA values, preferring what the chart itself reports.

    Values read off the chart match what the user is looking at; values computed
    from bars are a fallback so the engine still works on a bare chart. The
    source is returned so the report can say which one was used.
    """
    warnings: list[str] = []
    from_chart = {
        key: value
        for key, value in snap.studies.items()
        if key.startswith("ema") or key.startswith("moving_average_exponential")
    }
    if len(from_chart) >= 2:
        return from_chart, "chart studies", warnings

    closes = [b.close for b in snap.bars]
    computed: dict[str, float] = {}
    for period in (9, 21, 50):
        value = ind.ema(closes, period)
        if value is not None:
            computed[f"ema_{period}"] = value
    if computed:
        warnings.append(
            "No EMA studies found on the chart; EMA 9/21/50 were computed from "
            "the returned bars instead."
        )
    return computed, "computed from bars", warnings


def _sorted_emas(emas: dict[str, float]) -> list[tuple[str, float]]:
    """Order EMAs fast-to-slow by the period embedded in their key."""
    def period_of(key: str) -> int:
        digits = "".join(ch for ch in key if ch.isdigit())
        return int(digits) if digits else 10**6

    return sorted(emas.items(), key=lambda kv: period_of(kv[0]))


def _collect_votes(snap: Snapshot, emas: dict[str, float],
                   pivots: list[ind.Pivot]) -> tuple[list[Vote], list[str]]:
    votes: list[Vote] = []
    warnings: list[str] = []
    price = snap.quote.last

    ordered = _sorted_emas(emas)
    if len(ordered) >= 2:
        values = [v for _, v in ordered]
        stacked_up = all(a > b for a, b in zip(values, values[1:]))
        stacked_down = all(a < b for a, b in zip(values, values[1:]))
        label = " > ".join(f"{k}={fmt_price(v)}" for k, v in ordered)
        if stacked_up:
            votes.append(Vote("ema_stack", BULLISH,
                              f"EMAs stacked bullish ({label})", weight=1.5))
        elif stacked_down:
            votes.append(Vote("ema_stack", BEARISH,
                              f"EMAs stacked bearish ({label})", weight=1.5))
        else:
            votes.append(Vote("ema_stack", NEUTRAL,
                              f"EMAs interleaved ({label}) -- no clean trend",
                              weight=1.5))

        slowest_key, slowest_value = ordered[-1]
        if price > slowest_value:
            votes.append(Vote("price_vs_slow_ema", BULLISH,
                              f"Price {fmt_price(price)} above {slowest_key} "
                              f"{fmt_price(slowest_value)}"))
        else:
            votes.append(Vote("price_vs_slow_ema", BEARISH,
                              f"Price {fmt_price(price)} below {slowest_key} "
                              f"{fmt_price(slowest_value)}"))
    else:
        warnings.append("Fewer than 2 EMAs available -- trend read is weaker.")

    structure = ind.swing_structure(pivots)
    if structure == "higher_highs":
        votes.append(Vote("structure", BULLISH,
                          "Swing structure is higher highs + higher lows",
                          weight=1.5))
    elif structure == "lower_lows":
        votes.append(Vote("structure", BEARISH,
                          "Swing structure is lower highs + lower lows",
                          weight=1.5))
    elif structure == "mixed":
        votes.append(Vote("structure", NEUTRAL,
                          "Swing structure is mixed -- range, not trend",
                          weight=1.5))
    else:
        warnings.append(
            "Not enough confirmed pivots to read swing structure "
            f"({len(pivots)} found)."
        )

    rsi = snap.studies.get("rsi")
    if rsi is not None:
        if rsi >= 55:
            votes.append(Vote("rsi", BULLISH, f"RSI {rsi:.1f} in bullish regime"))
        elif rsi <= 45:
            votes.append(Vote("rsi", BEARISH, f"RSI {rsi:.1f} in bearish regime"))
        else:
            votes.append(Vote("rsi", NEUTRAL, f"RSI {rsi:.1f} is neutral"))
    else:
        warnings.append("RSI not present on the chart.")

    hist = snap.studies.get("macd_hist")
    if hist is None and "macd" in snap.studies and "macd_signal" in snap.studies:
        hist = snap.studies["macd"] - snap.studies["macd_signal"]
    if hist is not None:
        if hist > 0:
            votes.append(Vote("macd", BULLISH,
                              f"MACD histogram positive ({hist:+.5f})"))
        elif hist < 0:
            votes.append(Vote("macd", BEARISH,
                              f"MACD histogram negative ({hist:+.5f})"))
        else:
            votes.append(Vote("macd", NEUTRAL, "MACD histogram flat"))
    else:
        warnings.append("MACD not present on the chart.")

    return votes, warnings


def _score_trend(votes: list[Vote]) -> tuple[str, str, float]:
    """Weighted vote tally -> (direction, strength label, agreement 0..1)."""
    if not votes:
        return NEUTRAL, "unknown", 0.0

    total_weight = sum(v.weight for v in votes)
    score = sum(
        v.weight * (1 if v.direction == BULLISH else -1 if v.direction == BEARISH else 0)
        for v in votes
    )
    agreement = abs(score) / total_weight if total_weight else 0.0

    if agreement < 0.25:
        return NEUTRAL, "sideways", agreement
    direction = BULLISH if score > 0 else BEARISH
    if agreement >= 0.7:
        strength = "strong"
    elif agreement >= 0.45:
        strength = "moderate"
    else:
        strength = "weak"
    return direction, strength, agreement


def _build_plan(snap: Snapshot, atr_value: float, emas: dict[str, float],
                pivots: list[ind.Pivot], risk_cfg: dict[str, Any]
                ) -> tuple[TradePlan | None, str | None]:
    """Build a long-only plan anchored on real levels. Returns (plan, reject)."""
    price = snap.quote.last
    tolerance = atr_value * 0.25

    support_pool = [lv for lv in snap.pine_lines if lv < price]
    support_pool += [p.price for p in pivots if p.kind == "low" and p.price < price]
    support_pool += [v for v in emas.values() if v < price]
    supports = ind.dedupe_levels(support_pool, tolerance)

    resistance_pool = [lv for lv in snap.pine_lines if lv > price]
    resistance_pool += [p.price for p in pivots if p.kind == "high" and p.price > price]
    resistances = sorted(ind.dedupe_levels(resistance_pool, tolerance))

    if not supports:
        return None, ("No support level below price could be identified from "
                      "pivots, EMAs or drawn lines -- there is nothing to anchor "
                      "an entry or stop to.")
    if not resistances:
        return None, ("No resistance level above price could be identified -- a "
                      "target would have to be invented, so no trade is proposed.")

    entry_ref = max(supports)
    distance_atr = (price - entry_ref) / atr_value
    max_distance = float(risk_cfg.get("max_entry_distance_atr", 1.0))
    if distance_atr > max_distance:
        return None, (
            f"Nearest support {fmt_price(entry_ref)} is {distance_atr:.2f} ATR below "
            f"price {fmt_price(price)} (limit {max_distance:.2f} ATR) -- entering here "
            "means buying extended with the stop far away."
        )

    entry_low = entry_ref
    entry_high = min(price, entry_ref + 0.3 * atr_value)
    if entry_high < entry_low:
        entry_high = entry_low
    entry_basis = f"nearest support {fmt_price(entry_ref)}"

    swing_low = ind.last_pivot(pivots, "low")
    min_stop_gap = float(risk_cfg.get("min_stop_distance_atr", 0.6)) * atr_value
    atr_stop = entry_low - float(risk_cfg.get("atr_stop_multiple", 1.5)) * atr_value

    if swing_low is not None and swing_low.price < entry_low:
        structural_stop = swing_low.price - 0.25 * atr_value
        if entry_low - structural_stop >= min_stop_gap:
            stop = structural_stop
            stop_basis = (f"last confirmed swing low {fmt_price(swing_low.price)} "
                          f"less 0.25 ATR")
        else:
            stop = atr_stop
            stop_basis = (f"swing low {fmt_price(swing_low.price)} is inside the "
                          f"{fmt_price(min_stop_gap)} noise band, so ATR stop used")
    else:
        stop = atr_stop
        stop_basis = "no confirmed swing low below entry, so ATR stop used"

    risk = entry_low - stop
    if risk <= 0:
        return None, "Computed stop sits at or above entry -- setup discarded."

    min_rr = float(risk_cfg.get("min_risk_reward", 1.5))
    viable = [lv for lv in resistances if (lv - entry_low) / risk >= min_rr]
    if not viable:
        best = resistances[0]
        best_rr = (best - entry_low) / risk
        return None, (
            f"Nearest resistance {fmt_price(best)} only offers {best_rr:.2f}:1 from "
            f"entry {fmt_price(entry_low)} (minimum {min_rr:.1f}:1). Structure does not "
            "support a target that far, so no trade is proposed."
        )

    target = viable[0]
    return TradePlan(
        entry_low=entry_low,
        entry_high=entry_high,
        stop=stop,
        target=target,
        risk_reward=(target - entry_low) / risk,
        stop_basis=stop_basis,
        target_basis=f"nearest resistance clearing {min_rr:.1f}:1",
        entry_basis=entry_basis,
        distance_to_entry_atr=distance_atr,
    ), None


def _confidence(agreement: float, aligned: int, plan: TradePlan | None,
                warnings: list[str], min_rr: float) -> str:
    if plan is None:
        return "low"
    if agreement >= 0.7 and aligned >= 4 and not warnings and plan.risk_reward >= min_rr:
        return "high"
    if agreement >= 0.45 and aligned >= 3 and len(warnings) <= 1:
        return "medium"
    return "low"


def _quality_score(agreement: float, plan: TradePlan | None, confidence: str,
                   warnings: list[str]) -> float:
    """0-100 ranking score. Used in phase 3 to order opportunities."""
    if plan is None:
        return 0.0
    trend_points = agreement * 40
    rr_points = min(plan.risk_reward / 3.0, 1.0) * 30
    # Closer to the entry level is better -- less waiting, tighter invalidation.
    proximity_points = max(0.0, 1.0 - plan.distance_to_entry_atr) * 20
    confidence_points = CONFIDENCE_ORDER[confidence] * 5
    penalty = len(warnings) * 4
    return round(max(0.0, min(100.0,
        trend_points + rr_points + proximity_points + confidence_points - penalty)), 1)


def analyse(snap: Snapshot, config: dict[str, Any]) -> SymbolAnalysis:
    """Turn one collected snapshot into a structured, spot-only analysis."""
    risk_cfg = config.get("risk", {})
    filters = config.get("filters", {})
    min_rr = float(risk_cfg.get("min_risk_reward", 1.5))

    warnings = list(snap.errors)
    emas, ema_source, ema_warnings = _ema_inputs(snap)
    warnings.extend(ema_warnings)

    pivots = ind.find_pivots(snap.bars, int(risk_cfg.get("pivot_lookback", 3)))
    votes, vote_warnings = _collect_votes(snap, emas, pivots)
    warnings.extend(vote_warnings)

    trend, strength, agreement = _score_trend(votes)

    atr_value = snap.studies.get("atr")
    if atr_value is None:
        atr_value = ind.atr(snap.bars, int(risk_cfg.get("atr_period", 14)))

    result = SymbolAnalysis(
        symbol=snap.symbol,
        timeframe=snap.timeframe,
        collected_at=snap.collected_at,
        price=snap.quote.last,
        trend=trend,
        trend_strength=strength,
        actionable=False,
        confidence="low",
        quality_score=0.0,
        votes=votes,
        warnings=warnings,
        atr=atr_value,
    )

    if atr_value is None:
        result.rejected_reason = (
            f"ATR unavailable: {len(snap.bars)} bars returned, need at least "
            f"{int(risk_cfg.get('atr_period', 14)) + 1}. Stops cannot be sized."
        )
        result.reasoning = [v.detail for v in votes]
        return result

    if filters.get("long_only", True) and trend != BULLISH:
        if trend == BEARISH:
            result.rejected_reason = (
                f"Trend is bearish ({strength}, {agreement:.0%} agreement). This is "
                "a spot account -- there is no short to take, so the symbol is left "
                "alone rather than forced into a long."
            )
        else:
            result.rejected_reason = (
                f"Trend is sideways ({agreement:.0%} directional agreement) -- "
                "signals disagree, so no clean setup."
            )
        result.reasoning = [v.detail for v in votes]
        return result

    plan, reject = _build_plan(snap, atr_value, emas, pivots, risk_cfg)
    aligned = sum(1 for v in votes if v.direction == trend)
    confidence = _confidence(agreement, aligned, plan, warnings, min_rr)

    result.plan = plan
    result.rejected_reason = reject
    result.confidence = confidence
    result.quality_score = _quality_score(agreement, plan, confidence, warnings)
    result.actionable = plan is not None and CONFIDENCE_ORDER[confidence] >= \
        CONFIDENCE_ORDER.get(str(filters.get("min_confidence_to_report", "medium")), 1)

    reasoning = [f"Trend read: {trend} ({strength}), {agreement:.0%} of weighted "
                 f"signals agree. EMA source: {ema_source}."]
    reasoning.extend(v.detail for v in votes)
    if plan:
        reasoning.append(f"Entry anchored on {plan.entry_basis}.")
        reasoning.append(f"Stop from {plan.stop_basis}.")
        reasoning.append(f"Target is the {plan.target_basis} at {fmt_price(plan.target)}.")
        reasoning.append(f"ATR({risk_cfg.get('atr_period', 14)}) = {fmt_price(atr_value)}.")
    result.reasoning = reasoning
    return result
