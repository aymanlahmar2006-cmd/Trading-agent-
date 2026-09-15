"""Turn state changes into things worth interrupting the user for.

The bar is deliberately high. An agent that messages on every scan gets muted,
and a muted agent is worse than none -- so an alert fires on a *transition*
(a level reached, a regime flipped, a stop threatened), never on a condition
that is merely still true.
"""

from __future__ import annotations

from dataclasses import dataclass

from .formatting import fmt_price
from .i18n import resolve, t
from .positions import Position
from .regime import Regime, describe_change
from .signal import SymbolAnalysis

CRITICAL = "critical"
WARNING = "warning"
INFO = "info"

SEVERITY_ORDER = {CRITICAL: 0, WARNING: 1, INFO: 2}
ICONS = {CRITICAL: "🔴", WARNING: "🟡", INFO: "🔵"}


@dataclass
class Alert:
    kind: str
    severity: str
    title: str
    detail: str
    symbol: str = ""
    icon: str = "•"

    def key(self) -> str:
        """Identity for de-duplication across runs."""
        return f"{self.kind}:{self.symbol}"


def _alert(kind: str, severity: str, title: str, detail: str,
           symbol: str = "") -> Alert:
    return Alert(kind=kind, severity=severity, title=title, detail=detail,
                 symbol=symbol, icon=ICONS.get(severity, "•"))


def position_alerts(positions: list[Position], prices: dict[str, float],
                    stop_warn_pct: float = 25.0,
                    lang: str = "auto") -> list[Alert]:
    """Alerts about money already on the table. These outrank new ideas."""
    lang = resolve(lang)
    alerts: list[Alert] = []

    for position in positions:
        if position.status != "open":
            continue
        short = position.symbol.split(":")[-1]
        price = prices.get(position.symbol, prices.get(short))
        if price is None:
            alerts.append(_alert(
                "position_no_price", WARNING,
                t("no_price_title", lang, sym=short),
                t("no_price_detail", lang), short))
            continue

        r_value = position.r_at(price)
        r_text = f"{r_value:+.2f}R" if r_value is not None else t("r_not_computed", lang)

        if price <= position.stop:
            alerts.append(_alert(
                "stop_breached", CRITICAL,
                t("stop_breached_title", lang, sym=short),
                t("stop_breached_detail", lang, price=fmt_price(price),
                  stop=fmt_price(position.stop), r=r_text), short))
            continue

        hit = [target for target in position.targets if price >= target]
        if hit:
            alerts.append(_alert(
                "target_reached", CRITICAL,
                t("target_reached_title", lang, sym=short,
                  target=fmt_price(max(hit))),
                t("target_reached_detail", lang, price=fmt_price(price), r=r_text),
                short))
            continue

        remaining = position.stop_distance_pct(price)
        if remaining is not None and remaining <= stop_warn_pct:
            alerts.append(_alert(
                "stop_near", WARNING,
                t("stop_near_title", lang, sym=short),
                t("stop_near_detail", lang, pct=remaining, price=fmt_price(price),
                  stop=fmt_price(position.stop), r=r_text), short))

    return alerts


def regime_alert(previous: Regime | None, current: Regime,
                 lang: str = "auto") -> list[Alert]:
    lang = resolve(lang)
    change = describe_change(previous, current, lang)
    if not change:
        return []
    detail = change
    if current.notes:
        detail += " — " + t(current.notes[0], lang)
    return [_alert("regime_change", WARNING,
                   t("regime_change_title", lang), detail)]


def setup_alerts(analyses: list[SymbolAnalysis], open_symbols: set[str],
                 min_quality: float = 60.0, lang: str = "auto") -> list[Alert]:
    """New setups worth looking at, excluding symbols already held."""
    lang = resolve(lang)
    alerts: list[Alert] = []
    for analysis in analyses:
        short = analysis.symbol.split(":")[-1]
        if short in open_symbols or not analysis.actionable or analysis.plan is None:
            continue
        if analysis.quality_score < min_quality:
            continue
        plan = analysis.plan
        entry = (f"{fmt_price(plan.entry_low)}–{fmt_price(plan.entry_high)}"
                 if abs(plan.entry_high - plan.entry_low) > 1e-12
                 else fmt_price(plan.entry_low))
        alerts.append(_alert(
            "new_setup", INFO,
            t("new_setup_title", lang, sym=short, q=analysis.quality_score),
            t("new_setup_detail", lang, entry=entry, stop=fmt_price(plan.stop),
              target=fmt_price(plan.target), rr=plan.net_risk_reward), short))
    return alerts


def collect(analyses: list[SymbolAnalysis], positions: list[Position],
            prices: dict[str, float], previous: Regime | None, current: Regime,
            min_quality: float = 60.0, stop_warn_pct: float = 25.0,
            lang: str = "auto") -> list[Alert]:
    """All alerts for one scan, most urgent first."""
    lang = resolve(lang)
    open_symbols = {p.symbol.split(":")[-1] for p in positions if p.status == "open"}
    alerts = (position_alerts(positions, prices, stop_warn_pct, lang)
              + regime_alert(previous, current, lang)
              + setup_alerts(analyses, open_symbols, min_quality, lang))
    alerts.sort(key=lambda a: SEVERITY_ORDER.get(a.severity, 99))
    return alerts
