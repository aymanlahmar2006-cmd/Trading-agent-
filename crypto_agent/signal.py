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

from . import fibonacci as fib
from . import ichimoku as ichi
from . import liquidity as liq
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
    risk_reward: float          # gross, before trading costs
    net_risk_reward: float      # after a round trip of fees and slippage
    cost_in_r: float            # what that round trip costs, in units of R
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
    # Genuine data gaps: these lower confidence.
    warnings: list[str] = field(default_factory=list)
    # Informational only -- the input was obtained a different way, not lost.
    notes: list[str] = field(default_factory=list)
    rejected_reason: str | None = None
    rejected_kind: str = ""
    atr: float | None = None
    # Where price sits relative to the cloud: above / inside / below, or "" when
    # Ichimoku could not be read.
    cloud_position: str = ""
    tier: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["votes"] = [asdict(v) for v in self.votes]
        data["plan"] = asdict(self.plan) if self.plan else None
        return data


def _ema_inputs(snap: Snapshot) -> tuple[dict[str, float], str, list[str]]:
    """Resolve EMA values, preferring what the chart itself reports.

    Values read off the chart match what the user is looking at. Computing them
    from the returned bars is a *note*, not a warning: it is the same price data
    the chart would use, so the number is not less trustworthy. It matters
    because a TradingView Basic account allows only two indicators, so a user
    on that plan would otherwise be capped below full confidence forever for a
    difference that does not affect the arithmetic.
    """
    notes: list[str] = []
    from_chart = {
        key: value
        for key, value in snap.studies.items()
        if key.startswith("ema") or key.startswith("moving_average_exponential")
    }
    if len(from_chart) >= 2:
        return from_chart, "chart studies", notes

    closes = [b.close for b in snap.bars]
    computed: dict[str, float] = {}
    for period in (9, 21, 50):
        value = ind.ema(closes, period)
        if value is not None:
            computed[f"ema_{period}"] = value
    if computed:
        notes.append(
            "No EMA studies on the chart, so EMA 9/21/50 were computed from the "
            "same bars the chart draws. The values are equivalent."
        )
    return computed, "computed from bars", notes


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
        parts = [f"{k}={fmt_price(v)}" for k, v in ordered]
        separator = " > " if (stacked_up or stacked_down) else ", "
        label = separator.join(parts)
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


def _ichimoku_votes(reading: ichi.Ichimoku | None, price: float,
                    source: str, weight: float = 2.0
                    ) -> tuple[list[Vote], list[str]]:
    """Votes from the cloud, weighted by how a chart is actually read.

    Where price sits relative to the cloud is the primary structural call in
    Ichimoku, so it carries more weight than a single oscillator. The TK cross
    and the cloud's own colour are confirmations, not the call.
    """
    if reading is None:
        return [], ["Ichimoku unavailable -- not enough bars for the cloud "
                    f"(needs {ichi.minimum_bars()})."]

    votes: list[Vote] = []
    position = reading.price_position(price)
    cloud = (f"cloud {fmt_price(reading.cloud_bottom)}-"
             f"{fmt_price(reading.cloud_top)} ({source})")

    if position == ichi.ABOVE:
        votes.append(Vote("ichimoku_cloud", BULLISH,
                          f"Price {fmt_price(price)} above the {cloud}",
                          weight=weight))
    elif position == ichi.BELOW:
        votes.append(Vote("ichimoku_cloud", BEARISH,
                          f"Price {fmt_price(price)} below the {cloud}",
                          weight=weight))
    else:
        votes.append(Vote("ichimoku_cloud", NEUTRAL,
                          f"Price {fmt_price(price)} inside the {cloud} -- "
                          "Ichimoku reads this as no trend", weight=weight))

    votes.append(Vote(
        "ichimoku_tk",
        BULLISH if reading.tk_bullish else BEARISH,
        f"Tenkan {fmt_price(reading.tenkan)} "
        f"{'above' if reading.tk_bullish else 'below'} "
        f"Kijun {fmt_price(reading.kijun)}"))

    votes.append(Vote(
        "ichimoku_cloud_colour",
        BULLISH if reading.cloud_is_bullish else BEARISH,
        f"Cloud ahead is {'bullish' if reading.cloud_is_bullish else 'bearish'} "
        f"(Senkou A {fmt_price(reading.senkou_a)} vs B "
        f"{fmt_price(reading.senkou_b)})", weight=0.5))

    if reading.chikou_above_past_price is not None:
        votes.append(Vote(
            "ichimoku_chikou",
            BULLISH if reading.chikou_above_past_price else BEARISH,
            f"Lagging span is {'above' if reading.chikou_above_past_price else 'below'} "
            f"the price {ichi.DISPLACEMENT} bars back", weight=0.5))

    return votes, []


def _fib_votes(swing: "fib.FibSwing | None", price: float) -> list[Vote]:
    """Where price sits in the last measured leg.

    The golden band is where a trend pullback usually ends, so price sitting in
    it during an up-leg is the entry condition this style waits for -- not a
    prediction, a location.
    """
    if swing is None:
        return []

    fraction = swing.retracement_of(price)
    if fraction is None:
        return []
    low, high = swing.golden_band
    band = f"{fmt_price(low)}-{fmt_price(high)}"

    if swing.direction == "up":
        if swing.in_golden_zone(price):
            return [Vote("fib_zone", BULLISH,
                         f"Pullback is {fraction:.0%} of the last up-leg, inside "
                         f"the 0.5-0.618 band ({band})", weight=1.5)]
        if fraction > 0.786:
            return [Vote("fib_zone", BEARISH,
                         f"Pullback is {fraction:.0%} of the last up-leg -- past "
                         "0.786 the leg is failing, not resting", weight=1.5)]
        return [Vote("fib_zone", NEUTRAL,
                     f"Pullback is {fraction:.0%} of the last up-leg, outside the "
                     f"0.5-0.618 band ({band})", weight=1.0)]

    if fraction >= 0.618:
        return [Vote("fib_zone", BULLISH,
                     f"Price has recovered {fraction:.0%} of the last down-leg",
                     weight=1.0)]
    return [Vote("fib_zone", BEARISH,
                 f"Price has recovered only {fraction:.0%} of the last down-leg",
                 weight=1.0)]


def _liquidity_votes(pools: list[liq.Pool], sweep: "liq.Pool | None",
                     price: float) -> list[Vote]:
    """What the resting orders say."""
    votes: list[Vote] = []

    if sweep is not None:
        votes.append(Vote("liquidity_sweep", BULLISH,
                          f"Stops below {fmt_price(sweep.price)} were taken and "
                          "price closed back above -- a sweep, not a break",
                          weight=1.5))

    above = liq.nearest_pool(pools, liq.BUY_SIDE)
    below = liq.nearest_pool(pools, liq.SELL_SIDE)
    if above is not None and below is not None:
        to_above = abs(above.price - price)
        to_below = abs(price - below.price)
        if to_above > 0 and to_below > 0:
            # Price tends toward the larger, closer pool; the nearer one is the
            # likelier next destination.
            if to_below < to_above * 0.6:
                votes.append(Vote("liquidity_draw", BEARISH,
                                  f"Nearest liquidity is below at "
                                  f"{fmt_price(below.price)}, closer than "
                                  f"{fmt_price(above.price)} above"))
            elif to_above < to_below * 0.6:
                votes.append(Vote("liquidity_draw", BULLISH,
                                  f"Nearest liquidity is above at "
                                  f"{fmt_price(above.price)}, closer than "
                                  f"{fmt_price(below.price)} below"))
    return votes


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


def cost_in_r(entry: float, risk: float, risk_cfg: dict[str, Any]) -> float:
    """One round trip's cost expressed in R.

    Fees and slippage are a fraction of *price*; R is a fraction of the *stop
    distance*. So the tighter the stop, the more of each R the costs eat -- which
    is why a short holding period is the expensive one, not the cheap one. A
    0.26% round trip against a 0.5% stop is 0.52R, larger than most edges.
    """
    if risk <= 0 or entry <= 0:
        return 0.0
    round_trip_pct = 2.0 * (float(risk_cfg.get("fee_pct", 0.0))
                            + float(risk_cfg.get("slippage_pct", 0.0)))
    return (entry * round_trip_pct / 100.0) / risk


def _build_plan(snap: Snapshot, atr_value: float, emas: dict[str, float],
                pivots: list[ind.Pivot], risk_cfg: dict[str, Any],
                reading: ichi.Ichimoku | None = None,
                swing: "fib.FibSwing | None" = None,
                pools: list[liq.Pool] | None = None
                ) -> tuple[TradePlan | None, str | None, str]:
    """Build a long-only plan anchored on real levels. Returns (plan, reject)."""
    price = snap.quote.last
    tolerance = atr_value * 0.25
    pools = pools or []

    support_pool = [lv for lv in snap.pine_lines if lv < price]
    support_pool += [p.price for p in pivots if p.kind == "low" and p.price < price]
    support_pool += [v for v in emas.values() if v < price]
    # Kijun and the cloud top are levels an Ichimoku trader leans on directly.
    if reading is not None:
        support_pool += ichi.support_levels(reading, price)
    if swing is not None:
        support_pool += fib.support_levels(swing, price)
    supports = ind.dedupe_levels(support_pool, tolerance)

    resistance_pool = [lv for lv in snap.pine_lines if lv > price]
    resistance_pool += [p.price for p in pivots if p.kind == "high" and p.price > price]
    if reading is not None:
        resistance_pool += ichi.resistance_levels(reading, price)
    if swing is not None:
        resistance_pool += fib.resistance_levels(swing, price)
    # Buy-side pools are where price is drawn, so they make honest targets.
    resistance_pool += [p.price for p in pools if p.side == liq.BUY_SIDE]
    resistances = sorted(ind.dedupe_levels(resistance_pool, tolerance))

    if not supports:
        return None, ("No support level below price could be identified from "
                      "pivots, EMAs or drawn lines -- there is nothing to anchor "
                      "an entry or stop to."), "no_support"
    if not resistances:
        return None, ("No resistance level above price could be identified -- a "
                      "target would have to be invented, so no trade is proposed."),\
            "no_resistance"

    entry_ref = max(supports)
    distance_atr = (price - entry_ref) / atr_value
    max_distance = float(risk_cfg.get("max_entry_distance_atr", 1.0))
    if distance_atr > max_distance:
        return None, (
            f"Nearest support {fmt_price(entry_ref)} is {distance_atr:.2f} ATR below "
            f"price {fmt_price(price)} (limit {max_distance:.2f} ATR) -- entering here "
            "means buying extended with the stop far away."
        ), "too_extended"

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
        return None, "Computed stop sits at or above entry -- setup discarded.", "bad_stop"

    min_rr = float(risk_cfg.get("min_risk_reward", 1.5))
    costs = cost_in_r(entry_low, risk, risk_cfg)

    max_cost = float(risk_cfg.get("max_cost_in_r", 0.25))
    if costs > max_cost:
        return None, (
            f"Fees and slippage cost {costs:.2f}R on this stop distance "
            f"({fmt_price(risk)} wide), above the {max_cost:.2f}R limit. The stop is "
            "too tight for the trade to survive its own costs."
        ), "cost"

    # Gate on the net ratio: a 1.5:1 that pays 0.3R to the exchange is a 1.2:1.
    viable = [lv for lv in resistances
              if ((lv - entry_low) / risk) - costs >= min_rr]
    if not viable:
        best = resistances[0]
        best_rr = (best - entry_low) / risk
        return None, (
            f"Nearest resistance {fmt_price(best)} offers {best_rr:.2f}:1 gross from "
            f"entry {fmt_price(entry_low)}, but {costs:.2f}R goes to fees and slippage, "
            f"leaving {best_rr - costs:.2f}:1 net (minimum {min_rr:.1f}:1). Structure "
            "does not support a target that far, so no trade is proposed."
        ), "low_rr"

    target = viable[0]
    gross_rr = (target - entry_low) / risk
    return TradePlan(
        entry_low=entry_low,
        entry_high=entry_high,
        stop=stop,
        target=target,
        risk_reward=gross_rr,
        net_risk_reward=gross_rr - costs,
        cost_in_r=costs,
        stop_basis=stop_basis,
        target_basis=f"nearest resistance clearing {min_rr:.1f}:1",
        entry_basis=entry_basis,
        distance_to_entry_atr=distance_atr,
    ), None, ""


def _confidence(agreement: float, aligned: int, plan: TradePlan | None,
                warnings: list[str], min_rr: float) -> str:
    if plan is None:
        return "low"
    if agreement >= 0.7 and aligned >= 4 and not warnings and plan.net_risk_reward >= min_rr:
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
    rr_points = min(plan.net_risk_reward / 3.0, 1.0) * 30
    # Closer to the entry level is better -- less waiting, tighter invalidation.
    proximity_points = max(0.0, 1.0 - plan.distance_to_entry_atr) * 20
    confidence_points = CONFIDENCE_ORDER[confidence] * 5
    penalty = len(warnings) * 4
    return round(max(0.0, min(100.0,
        trend_points + rr_points + proximity_points + confidence_points - penalty)), 1)


def watchlist_entry(symbol: str, config: dict[str, Any]) -> dict[str, Any]:
    """The watchlist row for ``symbol``, matched on the bare ticker."""
    short = symbol.split(":")[-1]
    for entry in config.get("watchlist", []) or []:
        if str(entry.get("symbol", "")).split(":")[-1] == short:
            return entry
    return {}


def analyse(snap: Snapshot, config: dict[str, Any]) -> SymbolAnalysis:
    """Turn one collected snapshot into a structured, spot-only analysis."""
    risk_cfg = dict(config.get("risk", {}))
    filters = config.get("filters", {})

    # A mid-cap costs several times what BTC costs to cross. Using one slippage
    # figure for the whole watchlist makes thin markets look tradeable.
    entry = watchlist_entry(snap.symbol, config)
    if entry.get("slippage_pct") is not None:
        risk_cfg["slippage_pct"] = entry["slippage_pct"]

    min_rr = float(risk_cfg.get("min_risk_reward", 1.5))

    warnings = list(snap.errors)
    emas, ema_source, ema_notes = _ema_inputs(snap)

    pivots = ind.find_pivots(snap.bars, int(risk_cfg.get("pivot_lookback", 3)))
    votes, vote_warnings = _collect_votes(snap, emas, pivots)
    warnings.extend(vote_warnings)

    reading = None
    ichi_source = ""
    if filters.get("ichimoku_enabled", False):
        reading = ichi.from_studies(snap.studies)
        ichi_source = "chart studies"
        if reading is None:
            reading = ichi.compute(snap.bars)
            ichi_source = "computed from bars"
        # Two separate levers. The veto blocks a trade outright; the weight
        # decides how much the cloud moves the trend vote. Turning only the veto
        # off leaves a heavy neutral vote still suppressing confidence, so the
        # setups a user expected to see stay hidden.
        ichi_votes, ichi_warnings = _ichimoku_votes(
            reading, snap.quote.last, ichi_source,
            weight=float(filters.get("ichimoku_weight", 2.0)))
        votes.extend(ichi_votes)
        warnings.extend(ichi_warnings)

    atr_value = snap.studies.get("atr")
    if atr_value is None:
        atr_value = ind.atr(snap.bars, int(risk_cfg.get("atr_period", 14)))

    swing = None
    pools: list[liq.Pool] = []
    sweep = None
    if atr_value is not None:
        if filters.get("fibonacci_enabled", True):
            swing = fib.last_swing(pivots, snap.bars, atr=atr_value)
            votes.extend(_fib_votes(swing, snap.quote.last))
            if swing is None:
                warnings.append(
                    "No swing large enough to measure Fibonacci from -- levels "
                    "drawn on noise are worse than none.")
        if filters.get("liquidity_enabled", True):
            pools = liq.find_pools(snap.bars, pivots, snap.quote.last, atr_value)
            sweep = liq.recent_sweep(snap.bars, pivots, snap.quote.last, atr_value)
            votes.extend(_liquidity_votes(pools, sweep, snap.quote.last))

    trend, strength, agreement = _score_trend(votes)

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
        notes=ema_notes,
        atr=atr_value,
        cloud_position=("" if reading is None
                        else reading.price_position(snap.quote.last)),
        tier=str(entry.get("tier", "")),
    )

    if atr_value is None:
        result.rejected_kind = "no_atr"
        result.rejected_reason = (
            f"ATR unavailable: {len(snap.bars)} bars returned, need at least "
            f"{int(risk_cfg.get('atr_period', 14)) + 1}. Stops cannot be sized."
        )
        result.reasoning = [v.detail for v in votes]
        return result

    if (filters.get("ichimoku_veto", True) and reading is not None
            and result.cloud_position != ichi.ABOVE):
        where = "inside" if result.cloud_position == ichi.INSIDE else "below"
        result.rejected_kind = f"cloud_{where}"
        result.rejected_reason = (
            f"Price {fmt_price(snap.quote.last)} is {where} the Ichimoku cloud "
            f"({fmt_price(reading.cloud_bottom)}-{fmt_price(reading.cloud_top)}). "
            "A chart with the cloud on it does not buy here, so the engine "
            "stands aside rather than giving advice the chart contradicts."
        )
        result.reasoning = [v.detail for v in votes]
        return result

    if filters.get("long_only", True) and trend != BULLISH:
        if trend == BEARISH:
            result.rejected_kind = "bearish"
            result.rejected_reason = (
                f"Trend is bearish ({strength}, {agreement:.0%} agreement). This is "
                "a spot account -- there is no short to take, so the symbol is left "
                "alone rather than forced into a long."
            )
        else:
            result.rejected_kind = "sideways"
            result.rejected_reason = (
                f"Trend is sideways ({agreement:.0%} directional agreement) -- "
                "signals disagree, so no clean setup."
            )
        result.reasoning = [v.detail for v in votes]
        return result

    plan, reject, reject_kind = _build_plan(
        snap, atr_value, emas, pivots, risk_cfg, reading, swing, pools)
    aligned = sum(1 for v in votes if v.direction == trend)
    confidence = _confidence(agreement, aligned, plan, warnings, min_rr)

    result.plan = plan
    result.rejected_reason = reject
    result.rejected_kind = reject_kind

    if plan is not None and pools:
        hazard = liq.stop_hazard(pools, plan.stop, atr_value)
        if hazard is not None:
            warnings.append(
                f"Stop {fmt_price(plan.stop)} sits just above untouched stops at "
                f"{fmt_price(hazard.price)} ({hazard.touches} equal lows). A move "
                "collecting those takes this stop on the way."
            )
    result.confidence = confidence
    result.quality_score = _quality_score(agreement, plan, confidence, warnings)
    result.actionable = plan is not None and CONFIDENCE_ORDER[confidence] >= \
        CONFIDENCE_ORDER.get(str(filters.get("min_confidence_to_report", "medium")), 1)
    if plan is not None and not result.actionable:
        result.rejected_kind = "low_confidence"
        result.rejected_reason = (
            f"Setup is valid but confidence is {confidence}, below the reporting "
            "threshold."
        )

    reasoning = [f"Trend read: {trend} ({strength}), {agreement:.0%} of weighted "
                 f"signals agree. EMA source: {ema_source}."]
    reasoning.extend(v.detail for v in votes)
    if plan:
        reasoning.append(f"Entry anchored on {plan.entry_basis}.")
        reasoning.append(f"Stop from {plan.stop_basis}.")
        reasoning.append(f"Target is the {plan.target_basis} at {fmt_price(plan.target)}.")
        reasoning.append(
            f"R:R {plan.risk_reward:.2f} gross, {plan.net_risk_reward:.2f} net after "
            f"{plan.cost_in_r:.2f}R of fees and slippage."
        )
        reasoning.append(f"ATR({risk_cfg.get('atr_period', 14)}) = {fmt_price(atr_value)}.")
    if reading is not None:
        reasoning.append(
            f"Ichimoku ({ichi_source}): price is {result.cloud_position} the cloud."
        )
    if swing is not None:
        low, high = swing.golden_band
        reasoning.append(
            f"Fib leg {fmt_price(swing.low)}-{fmt_price(swing.high)} "
            f"({swing.direction}), 0.5-0.618 band {fmt_price(low)}-{fmt_price(high)}."
        )
    if pools:
        below = liq.nearest_pool(pools, liq.SELL_SIDE)
        above = liq.nearest_pool(pools, liq.BUY_SIDE)
        parts = []
        if below is not None:
            parts.append(f"{fmt_price(below.price)} below"
                         + (" (swept)" if below.swept else ""))
        if above is not None:
            parts.append(f"{fmt_price(above.price)} above")
        if parts:
            reasoning.append("Liquidity: " + ", ".join(parts) + ".")
    result.reasoning = reasoning
    return result
