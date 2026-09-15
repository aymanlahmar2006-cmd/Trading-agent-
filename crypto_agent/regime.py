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

from .i18n import resolve, t
from .signal import BEARISH, BULLISH, SymbolAnalysis

STATE_FILE = Path("journal/regime.json")

RISK_ON = "risk_on"
RISK_OFF = "risk_off"
MIXED = "mixed"
UNKNOWN = "unknown"

SENTIMENT_KEY = {
    RISK_ON: "risk_on",
    RISK_OFF: "risk_off",
    MIXED: "mixed",
    UNKNOWN: "regime_unknown",
}


def label(sentiment: str, lang: str) -> str:
    return t(SENTIMENT_KEY.get(sentiment, "regime_unknown"), lang)


@dataclass
class Regime:
    sentiment: str = UNKNOWN
    btc_trend: str = UNKNOWN
    btc_strength: str = UNKNOWN
    breadth_bullish: int = 0
    breadth_total: int = 0
    dominance_note: str = ""
    # Translation keys, resolved at render time -- see SENTIMENT_KEY above.
    notes: list[str] = field(default_factory=list)
    assessed_at: str = ""

    @property
    def breadth_pct(self) -> float | None:
        if not self.breadth_total:
            return None
        return self.breadth_bullish / self.breadth_total * 100.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_context(self, lang: str = "auto") -> dict[str, Any]:
        """Shape the report renderer expects, in the requested language."""
        lang = resolve(lang)
        breadth = self.breadth_pct
        notes = [t(key, lang) for key in self.notes]
        if breadth is not None:
            notes.append(t("breadth", lang, bullish=self.breadth_bullish,
                           total=self.breadth_total, pct=breadth))
        trend = t(self.btc_trend, lang) if self.btc_trend != UNKNOWN \
            else t("unknown", lang)
        strength = t(self.btc_strength, lang) if self.btc_strength != UNKNOWN \
            else t("unknown", lang)
        return {
            "btc_trend": f"{trend} ({strength})",
            "risk_sentiment": label(self.sentiment, lang),
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
        regime.notes.append("btc_not_analysed")

    breadth = regime.breadth_pct

    if btc is None and breadth is None:
        regime.sentiment = UNKNOWN
        return regime

    if breadth is None:
        # Only BTC available: report its trend but do not claim a market regime.
        regime.sentiment = MIXED
        regime.notes.append("no_peers")
        return regime

    btc_bullish = regime.btc_trend == BULLISH
    btc_bearish = regime.btc_trend == BEARISH

    if btc_bullish and breadth >= 60:
        regime.sentiment = RISK_ON
    elif btc_bearish and breadth <= 40:
        regime.sentiment = RISK_OFF
    elif btc_bullish and breadth < 40:
        regime.sentiment = MIXED
        regime.notes.append("rotation_into_btc")
    elif btc_bearish and breadth > 60:
        regime.sentiment = MIXED
        regime.notes.append("btc_down_alts_up")
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


def describe_change(previous: Regime | None, current: Regime,
                    lang: str = "auto") -> str | None:
    """A one-line description of a regime flip, or None when nothing changed."""
    if previous is None or previous.sentiment == UNKNOWN:
        return None
    if previous.sentiment == current.sentiment:
        return None
    lang = resolve(lang)
    return t("regime_changed", lang,
             before=label(previous.sentiment, lang),
             after=label(current.sentiment, lang))
