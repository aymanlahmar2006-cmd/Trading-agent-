"""Render analyses into the agreed report layout, in Arabic or English."""

from __future__ import annotations

from typing import Any

from .formatting import fmt_price
from .i18n import resolve, t
from .signal import SymbolAnalysis


def _short_symbol(symbol: str) -> str:
    return symbol.split(":")[-1]


def render_market_context(context: dict[str, Any], lang: str) -> str:
    lines = [t("market_context", lang)]
    if not context:
        lines.append(t("context_unavailable", lang))
        return "\n".join(lines)

    btc = context.get("btc_trend") or t("unknown", lang)
    sentiment = context.get("risk_sentiment") or t("regime_unknown", lang)
    lines.append(f"BTC: {btc} | Risk Sentiment: {sentiment}")
    if context.get("dominance_note"):
        lines.append(f"BTC.D: {context['dominance_note']}")
    for note in context.get("notes") or []:
        lines.append(f"  - {note}")
    return "\n".join(lines)


def render_opportunity(index: int, analysis: SymbolAnalysis, lang: str) -> str:
    plan = analysis.plan
    assert plan is not None, "render_opportunity requires an analysis with a plan"

    trend = t(analysis.trend, lang)
    strength = t(analysis.trend_strength, lang)
    entry = (fmt_price(plan.entry_low)
             if abs(plan.entry_high - plan.entry_low) < 1e-12
             else f"{fmt_price(plan.entry_low)} – {fmt_price(plan.entry_high)}")

    lines = [
        f"{index}. {_short_symbol(analysis.symbol)} — {trend} ({strength})",
        f"   {t('price_now', lang)}: {fmt_price(analysis.price)} | "
        f"ATR: {fmt_price(analysis.atr)} | "
        f"{t('setup_quality', lang)}: {analysis.quality_score}/100",
        f"   Entry: {entry} | Stop: {fmt_price(plan.stop)} | "
        f"Target: {fmt_price(plan.target)}",
        f"   R:R: {plan.net_risk_reward:.2f} {t('rr_net', lang)} "
        f"({plan.risk_reward:.2f} {t('rr_gross_note', lang)} {plan.cost_in_r:.2f}R)",
        f"   {t('reason', lang)}",
    ]
    lines.extend(f"     • {reason}" for reason in analysis.reasoning)
    lines.append(f"   {t('confidence', lang)}: {t(analysis.confidence, lang)}")
    if analysis.warnings:
        lines.append(f"   {t('data_gaps', lang)}")
        lines.extend(f"     • {w}" for w in analysis.warnings)
    return "\n".join(lines)


def render_watching(analysis: SymbolAnalysis, lang: str) -> str:
    reason = analysis.rejected_reason or t("no_clear_signal", lang)
    line = f"- {_short_symbol(analysis.symbol)}: {reason}"
    if analysis.warnings:
        line += "\n  ⚠ " + " | ".join(analysis.warnings)
    return line


def render_report(analyses: list[SymbolAnalysis],
                  market_context: dict[str, Any] | None = None,
                  lang: str = "auto") -> str:
    lang = resolve(lang)
    opportunities = [a for a in analyses if a.actionable and a.plan is not None]
    opportunities.sort(key=lambda a: a.quality_score, reverse=True)
    # Split by identity, not equality: SymbolAnalysis is a plain dataclass, so two
    # symbols that happen to score identically would compare equal and one would
    # vanish from the watch list entirely.
    promoted = {id(a) for a in opportunities}
    watching = [a for a in analyses if id(a) not in promoted]

    blocks = [render_market_context(market_context or {}, lang), ""]

    blocks.append(t("top_opportunities", lang))
    if opportunities:
        for i, analysis in enumerate(opportunities, start=1):
            blocks.append(render_opportunity(i, analysis, lang))
            blocks.append("")
    else:
        blocks.append(t("no_opportunities", lang))
        blocks.append("")

    blocks.append(t("watching", lang))
    if watching:
        blocks.extend(render_watching(a, lang) for a in watching)
    else:
        blocks.append(t("nothing", lang))

    blocks.append("")
    blocks.append(t("safety_note", lang))
    return "\n".join(blocks)
