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


def render_opportunity(index: int, analysis: SymbolAnalysis, lang: str,
                       full: bool = True) -> str:
    """One opportunity. ``full`` includes the reasoning; otherwise just levels.

    Reasoning is what makes a setup checkable, so the top picks always carry it.
    But repeating fifteen lines of it for every candidate buries the ranking the
    report exists to show, so the tail gets the numbers only.
    """
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
    ]
    if not full:
        lines.append(f"   {t('confidence', lang)}: {t(analysis.confidence, lang)}"
                     + (f" | ⚠ {len(analysis.warnings)}" if analysis.warnings else ""))
        return "\n".join(lines)

    lines.append(f"   {t('reason', lang)}")
    lines.extend(f"     • {reason}" for reason in analysis.reasoning)
    lines.append(f"   {t('confidence', lang)}: {t(analysis.confidence, lang)}")
    if analysis.warnings:
        lines.append(f"   {t('data_gaps', lang)}")
        lines.extend(f"     • {w}" for w in analysis.warnings)
    if analysis.notes:
        lines.append(f"   {t('notes', lang)}")
        lines.extend(f"     • {n}" for n in analysis.notes)
    return "\n".join(lines)


def render_watching(analysis: SymbolAnalysis, lang: str) -> str:
    reason = analysis.rejected_reason or t("no_clear_signal", lang)
    line = f"- {_short_symbol(analysis.symbol)}: {reason}"
    if analysis.warnings:
        line += "\n  ⚠ " + " | ".join(analysis.warnings)
    return line


def render_watching_grouped(analyses: list[SymbolAnalysis], lang: str) -> list[str]:
    """One line per reason, not per symbol.

    A 35-symbol watchlist produces 35 rejection paragraphs, which nobody reads --
    and an unread report hides the two lines that mattered. Grouping keeps the
    information and makes the shape of the market visible at a glance.
    """
    groups: dict[str, list[str]] = {}
    for analysis in analyses:
        kind = analysis.rejected_kind or "other"
        groups.setdefault(kind, []).append(_short_symbol(analysis.symbol))

    lines = []
    for kind, symbols in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        label = t(f"kind_{kind}", lang)
        if label == f"kind_{kind}":          # no label for this kind yet
            label = t("kind_other", lang)
        lines.append(f"- {label} ({len(symbols)}): {', '.join(sorted(symbols))}")
    return lines


def render_near_miss(analysis: SymbolAnalysis, lang: str) -> str:
    """A setup that stands but did not clear the confidence bar."""
    plan = analysis.plan
    assert plan is not None
    entry = (fmt_price(plan.entry_low)
             if abs(plan.entry_high - plan.entry_low) < 1e-12
             else f"{fmt_price(plan.entry_low)}–{fmt_price(plan.entry_high)}")
    return (f"- {_short_symbol(analysis.symbol)}: {t('entry', lang)} {entry} | "
            f"{t('stop', lang)} {fmt_price(plan.stop)} | "
            f"{t('target', lang)} {fmt_price(plan.target)} | "
            f"R:R {plan.net_risk_reward:.2f} {t('rr_net', lang)} | "
            f"{t('confidence', lang)}: {t(analysis.confidence, lang)} "
            f"({analysis.quality_score:.0f}/100)")


def render_report(analyses: list[SymbolAnalysis],
                  market_context: dict[str, Any] | None = None,
                  lang: str = "auto", max_opportunities: int = 5,
                  compact_watching: bool = True,
                  full_reasoning_for: int = 2,
                  show_near_misses: bool = True,
                  max_near_misses: int = 5) -> str:
    lang = resolve(lang)
    opportunities = [a for a in analyses if a.actionable and a.plan is not None]
    opportunities.sort(key=lambda a: a.quality_score, reverse=True)
    # Split by identity, not equality: SymbolAnalysis is a plain dataclass, so two
    # symbols that happen to score identically would compare equal and one would
    # vanish from the watch list entirely.
    promoted = {id(a) for a in opportunities}
    rest = [a for a in analyses if id(a) not in promoted]

    # A setup that is real but under the confidence bar is not the same as one
    # the market never offered. Collapsing both into "watching" hides the only
    # candidates worth a second look, which is the opposite of not missing one.
    near_misses: list[SymbolAnalysis] = []
    if show_near_misses:
        near_misses = [a for a in rest
                       if a.plan is not None and a.rejected_kind == "low_confidence"]
        near_misses.sort(key=lambda a: a.quality_score, reverse=True)
        near_ids = {id(a) for a in near_misses}
        rest = [a for a in rest if id(a) not in near_ids]
    watching = rest

    blocks = [render_market_context(market_context or {}, lang), ""]

    blocks.append(t("top_opportunities", lang))
    if opportunities:
        shown = opportunities[:max_opportunities] if max_opportunities > 0 \
            else opportunities
        for i, analysis in enumerate(shown, start=1):
            blocks.append(render_opportunity(i, analysis, lang,
                                             full=i <= full_reasoning_for))
            blocks.append("")
        remaining = len(opportunities) - len(shown)
        if remaining > 0:
            blocks.append(t("more_opportunities", lang, n=remaining))
            blocks.append("")
    else:
        blocks.append(t("no_opportunities", lang))
        blocks.append("")

    if near_misses:
        blocks.append(t("near_misses", lang))
        shown_near = near_misses[:max_near_misses] if max_near_misses > 0 \
            else near_misses
        blocks.extend(render_near_miss(a, lang) for a in shown_near)
        left = len(near_misses) - len(shown_near)
        if left > 0:
            blocks.append(t("more_near_misses", lang, n=left))
        blocks.append(t("near_miss_note", lang))
        blocks.append("")

    blocks.append(t("watching", lang))
    if not watching:
        blocks.append(t("nothing", lang))
    elif compact_watching and len(watching) > 5:
        blocks.extend(render_watching_grouped(watching, lang))
    else:
        blocks.extend(render_watching(a, lang) for a in watching)

    blocks.append("")
    blocks.append(t("scanned", lang, n=len(analyses)))
    blocks.append(t("safety_note", lang))
    return "\n".join(blocks)
