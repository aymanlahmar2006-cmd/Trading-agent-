"""Market context for crypto, built from the chart rather than borrowed from equities.

There is no ready-made "crypto market regime" tool. What exists on a TradingView
chart is BTC's own trend, BTC dominance, and how the rest of the watchlist is
behaving relative to it -- so regime here is defined from exactly those three and
nothing else. Anything not collected is reported as unknown, never assumed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .signal import BEARISH, BULLISH, SymbolAnalysis

STATE_FILE = Path("journal/regime.json")

RISK_ON = "risk_on"
RISK_OFF = "risk_off"
MIXED = "mixed"
UNKNOWN = "unknown"

LABEL_AR = {
    RISK_ON: "مُقبل على المخاطرة (risk-on)",
    RISK_OFF: "متجنب للمخاطرة (risk-off)",
    MIXED: "مختلط",
    UNKNOWN: "غير معروف",
}


@dataclass
class Regime:
    sentiment: str = UNKNOWN
    btc_trend: str = UNKNOWN
    btc_strength: str = UNKNOWN
    breadth_bullish: int = 0
    breadth_total: int = 0
    dominance_note: str = ""
    notes: list[str] = field(default_factory=list)
    assessed_at: str = ""

    @property
    def breadth_pct(self) -> float | None:
        if not self.breadth_total:
            return None
        return self.breadth_bullish / self.breadth_total * 100.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_context(self) -> dict[str, Any]:
        """Shape the report renderer expects."""
        breadth = self.breadth_pct
        notes = list(self.notes)
        if breadth is not None:
            notes.append(
                f"اتساع السوق: {self.breadth_bullish} من {self.breadth_total} "
                f"رمز صاعد ({breadth:.0f}%)"
            )
        return {
            "btc_trend": f"{self.btc_trend} ({self.btc_strength})",
            "risk_sentiment": LABEL_AR.get(self.sentiment, self.sentiment),
            "dominance_note": self.dominance_note,
            "notes": notes,
        }


def assess(btc: SymbolAnalysis | None, others: list[SymbolAnalysis],
           dominance_note: str = "", assessed_at: str = "") -> Regime:
    """Classify the market from BTC's trend and how much of the list follows it.

    BTC leads crypto most of the time, but a rising BTC while everything else
    falls is a rotation into BTC, not a risk-on tape -- so breadth is required to
    call risk-on, and BTC alone is never enough.
    """
    regime = Regime(assessed_at=assessed_at, dominance_note=dominance_note)

    evaluable = [a for a in others if a.trend in (BULLISH, BEARISH, "neutral")]
    regime.breadth_total = len(evaluable)
    regime.breadth_bullish = sum(1 for a in evaluable if a.trend == BULLISH)

    if btc is not None:
        regime.btc_trend = btc.trend
        regime.btc_strength = btc.trend_strength
    else:
        regime.notes.append(
            "BTC لم يتم تحليله في هذه الجولة — تقييم السوق مبني على الاتساع فقط."
        )

    breadth = regime.breadth_pct

    if btc is None and breadth is None:
        regime.sentiment = UNKNOWN
        return regime

    if breadth is None:
        # Only BTC available: report its trend but do not claim a market regime.
        regime.sentiment = MIXED
        regime.notes.append(
            "لا توجد رموز أخرى للمقارنة، فمفيش حكم على اتساع السوق."
        )
        return regime

    btc_bullish = regime.btc_trend == BULLISH
    btc_bearish = regime.btc_trend == BEARISH

    if btc_bullish and breadth >= 60:
        regime.sentiment = RISK_ON
    elif btc_bearish and breadth <= 40:
        regime.sentiment = RISK_OFF
    elif btc_bullish and breadth < 40:
        regime.sentiment = MIXED
        regime.notes.append(
            "BTC صاعد لكن باقي السوق مش تابع — ده دوران نحو BTC، مش risk-on. "
            "الألت كوينز أضعف من المعتاد في الوضع ده."
        )
    elif btc_bearish and breadth > 60:
        regime.sentiment = MIXED
        regime.notes.append(
            "BTC هابط بينما الألت صاعدة — وضع غير مستقر، عادةً بيتحل لصالح BTC."
        )
    else:
        regime.sentiment = MIXED

    return regime


def load_previous(path: Path = STATE_FILE) -> Regime | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    known = {k: v for k, v in raw.items() if k in Regime.__dataclass_fields__}
    return Regime(**known)


def save(regime: Regime, path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(regime.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8")


def describe_change(previous: Regime | None, current: Regime) -> str | None:
    """A one-line description of a regime flip, or None when nothing changed."""
    if previous is None or previous.sentiment == UNKNOWN:
        return None
    if previous.sentiment == current.sentiment:
        return None
    return (f"حالة السوق اتغيرت من {LABEL_AR.get(previous.sentiment, previous.sentiment)} "
            f"إلى {LABEL_AR.get(current.sentiment, current.sentiment)}")
