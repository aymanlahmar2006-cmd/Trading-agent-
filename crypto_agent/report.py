"""Render analyses into the agreed report layout."""

from __future__ import annotations

from typing import Any

from .formatting import fmt_price
from .signal import SymbolAnalysis

CONFIDENCE_AR = {"high": "عالي", "medium": "متوسط", "low": "منخفض"}
TREND_AR = {"bullish": "صاعد", "bearish": "هابط", "neutral": "عرضي"}
STRENGTH_AR = {
    "strong": "قوي", "moderate": "متوسط", "weak": "ضعيف",
    "sideways": "عرضي", "unknown": "غير محدد",
}


def _short_symbol(symbol: str) -> str:
    return symbol.split(":")[-1]


def render_market_context(context: dict[str, Any]) -> str:
    """Phase 2 layer. Until it is wired up this states that it is missing."""
    lines = ["=== Market Context ==="]
    if not context:
        lines.append(
            "غير متاح — طبقة تقييم السوق (المرحلة 2) لسه مش متوصلة. "
            "التحليل تحت ده لرمز واحد فقط وبدون سياق BTC."
        )
        return "\n".join(lines)

    btc = context.get("btc_trend", "غير متاح")
    sentiment = context.get("risk_sentiment", "غير متاح")
    lines.append(f"BTC: {btc} | Risk Sentiment: {sentiment}")
    if context.get("dominance_note"):
        lines.append(f"BTC.D: {context['dominance_note']}")
    if context.get("notes"):
        lines.extend(f"  - {n}" for n in context["notes"])
    return "\n".join(lines)


def render_opportunity(index: int, analysis: SymbolAnalysis) -> str:
    plan = analysis.plan
    assert plan is not None, "render_opportunity requires an analysis with a plan"

    trend = TREND_AR.get(analysis.trend, analysis.trend)
    strength = STRENGTH_AR.get(analysis.trend_strength, analysis.trend_strength)
    entry = (f"{fmt_price(plan.entry_low)}"
             if abs(plan.entry_high - plan.entry_low) < 1e-12
             else f"{fmt_price(plan.entry_low)} – {fmt_price(plan.entry_high)}")

    lines = [
        f"{index}. {_short_symbol(analysis.symbol)} — {trend} ({strength})",
        f"   السعر الحالي: {fmt_price(analysis.price)} | "
        f"ATR: {fmt_price(analysis.atr)} | جودة الإعداد: {analysis.quality_score}/100",
        f"   Entry: {entry} | Stop: {fmt_price(plan.stop)} | "
        f"Target: {fmt_price(plan.target)}",
        f"   R:R: {plan.net_risk_reward:.2f} صافي "
        f"({plan.risk_reward:.2f} قبل التكاليف — الرسوم والانزلاق "
        f"بياخدوا {plan.cost_in_r:.2f}R)",
        "   السبب:",
    ]
    lines.extend(f"     • {reason}" for reason in analysis.reasoning)
    lines.append(f"   الثقة: {CONFIDENCE_AR.get(analysis.confidence, analysis.confidence)}")
    if analysis.warnings:
        lines.append("   ⚠ نواقص في البيانات:")
        lines.extend(f"     • {w}" for w in analysis.warnings)
    return "\n".join(lines)


def render_watching(analysis: SymbolAnalysis) -> str:
    reason = analysis.rejected_reason or "لا توجد إشارة واضحة."
    line = f"- {_short_symbol(analysis.symbol)}: {reason}"
    if analysis.warnings:
        line += "\n  ⚠ " + " | ".join(analysis.warnings)
    return line


def render_report(analyses: list[SymbolAnalysis],
                  market_context: dict[str, Any] | None = None) -> str:
    opportunities = [a for a in analyses if a.actionable and a.plan is not None]
    opportunities.sort(key=lambda a: a.quality_score, reverse=True)
    # Split by identity, not equality: SymbolAnalysis is a plain dataclass, so two
    # symbols that happen to score identically would compare equal and one would
    # vanish from the watch list entirely.
    promoted = {id(a) for a in opportunities}
    watching = [a for a in analyses if id(a) not in promoted]

    blocks = [render_market_context(market_context or {}), ""]

    blocks.append("=== Top Opportunities ===")
    if opportunities:
        for i, analysis in enumerate(opportunities, start=1):
            blocks.append(render_opportunity(i, analysis))
            blocks.append("")
    else:
        blocks.append("لا توجد فرص مستوفية للشروط في هذه الجولة.")
        blocks.append("")

    blocks.append("=== Watching (لسه معندهاش إشارة واضحة) ===")
    if watching:
        blocks.extend(render_watching(a) for a in watching)
    else:
        blocks.append("لا شيء.")

    blocks.append("")
    blocks.append("— إشارات فقط. لم يتم ولن يتم تنفيذ أي صفقة تلقائياً. —")
    return "\n".join(blocks)
