"""Turn state changes into things worth interrupting the user for.

The bar is deliberately high. An agent that messages on every scan gets muted,
and a muted agent is worse than none -- so an alert fires on a *transition*
(a level reached, a regime flipped, a stop threatened), never on a condition
that is merely still true.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .formatting import fmt_price
from .positions import Position
from .regime import Regime, describe_change
from .signal import SymbolAnalysis

CRITICAL = "critical"
WARNING = "warning"
INFO = "info"

SEVERITY_ORDER = {CRITICAL: 0, WARNING: 1, INFO: 2}


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


def _icon_for(severity: str) -> str:
    return {CRITICAL: "🔴", WARNING: "🟡", INFO: "🔵"}.get(severity, "•")


def position_alerts(positions: list[Position],
                    prices: dict[str, float],
                    stop_warn_pct: float = 25.0) -> list[Alert]:
    """Alerts about money already on the table. These outrank new ideas."""
    alerts: list[Alert] = []

    for position in positions:
        if position.status != "open":
            continue
        short = position.symbol.split(":")[-1]
        price = prices.get(position.symbol, prices.get(short))
        if price is None:
            alerts.append(Alert(
                kind="position_no_price", severity=WARNING,
                title=f"{short}: مفيش سعر لحظي",
                detail=("الصفقة مفتوحة لكن ما قدرناش نجيب سعرها في الجولة دي، "
                        "فمفيش متابعة للستوب أو الهدف."),
                symbol=short, icon=_icon_for(WARNING)))
            continue

        r_now = position.r_at(price)
        r_text = f"{r_now:+.2f}R" if r_now is not None else "R غير محسوب"

        if price <= position.stop:
            alerts.append(Alert(
                kind="stop_breached", severity=CRITICAL,
                title=f"{short}: السعر اخترق الستوب",
                detail=(f"السعر {fmt_price(price)} تحت الستوب "
                        f"{fmt_price(position.stop)}. الخسارة الحالية {r_text}. "
                        "قرار الخروج قرارك — الأيجنت ما بينفذش."),
                symbol=short, icon=_icon_for(CRITICAL)))
            continue

        hit = [t for t in position.targets if price >= t]
        if hit:
            alerts.append(Alert(
                kind="target_reached", severity=CRITICAL,
                title=f"{short}: وصل الهدف {fmt_price(max(hit))}",
                detail=(f"السعر {fmt_price(price)} عند/فوق الهدف. "
                        f"الربح الحالي {r_text}."),
                symbol=short, icon=_icon_for(CRITICAL)))
            continue

        remaining = position.stop_distance_pct(price)
        if remaining is not None and remaining <= stop_warn_pct:
            alerts.append(Alert(
                kind="stop_near", severity=WARNING,
                title=f"{short}: السعر قرّب من الستوب",
                detail=(f"فاضل {remaining:.0f}% بس من مسافة المخاطرة الأصلية "
                        f"(السعر {fmt_price(price)}، الستوب "
                        f"{fmt_price(position.stop)}). الوضع الحالي {r_text}."),
                symbol=short, icon=_icon_for(WARNING)))

    return alerts


def regime_alert(previous: Regime | None, current: Regime) -> list[Alert]:
    change = describe_change(previous, current)
    if not change:
        return []
    detail = change
    if current.notes:
        detail += " — " + current.notes[0]
    return [Alert(kind="regime_change", severity=WARNING,
                  title="تغيّر في حالة السوق", detail=detail,
                  icon=_icon_for(WARNING))]


def setup_alerts(analyses: list[SymbolAnalysis],
                 open_symbols: set[str],
                 min_quality: float = 60.0) -> list[Alert]:
    """New setups worth looking at, excluding symbols already held."""
    alerts: list[Alert] = []
    for analysis in analyses:
        short = analysis.symbol.split(":")[-1]
        if short in open_symbols or not analysis.actionable or analysis.plan is None:
            continue
        if analysis.quality_score < min_quality:
            continue
        plan = analysis.plan
        alerts.append(Alert(
            kind="new_setup", severity=INFO,
            title=f"{short}: إعداد جديد ({analysis.quality_score:.0f}/100)",
            detail=(f"دخول {fmt_price(plan.entry_low)}–{fmt_price(plan.entry_high)} | "
                    f"ستوب {fmt_price(plan.stop)} | هدف {fmt_price(plan.target)} | "
                    f"R:R {plan.net_risk_reward:.2f} صافي"),
            symbol=short, icon=_icon_for(INFO)))
    return alerts


def collect(analyses: list[SymbolAnalysis], positions: list[Position],
            prices: dict[str, float], previous: Regime | None,
            current: Regime, min_quality: float = 60.0) -> list[Alert]:
    """All alerts for one scan, most urgent first."""
    open_symbols = {p.symbol.split(":")[-1] for p in positions if p.status == "open"}
    alerts = (position_alerts(positions, prices)
              + regime_alert(previous, current)
              + setup_alerts(analyses, open_symbols, min_quality))
    alerts.sort(key=lambda a: SEVERITY_ORDER.get(a.severity, 99))
    return alerts
