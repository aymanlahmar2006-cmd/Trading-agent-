"""Snapshot contract between the TradingView MCP layer and the analysis engine.

The agent never fetches market data itself. Claude pulls it from the TradingView
MCP tools and writes it into a *snapshot* JSON that matches the shape below.
Everything the engine reports must be traceable back to a field in here, so any
value that was not actually retrieved stays ``None`` and is reported as
unavailable rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class SnapshotError(ValueError):
    """Raised when a snapshot is malformed or internally inconsistent."""


# TradingView renders numbers for humans, not for float(). Negative values come
# back with U+2212 MINUS SIGN rather than an ASCII hyphen, and depending on the
# locale a value can carry thousands separators or a trailing percent sign.
_NUMERIC_SUBSTITUTIONS = {
    "\u2212": "-",   # minus sign
    "\u2013": "-",   # en dash
    "\u2014": "-",   # em dash
    "\uff0d": "-",   # fullwidth hyphen-minus
    "\ufe63": "-",   # small hyphen-minus
    "\uff0b": "+",   # fullwidth plus
    "\u066b": ".",   # arabic decimal separator
    "\u00a0": "",    # no-break space
    "\u202f": "",    # narrow no-break space
    "\u2009": "",    # thin space
    "\u066c": "",    # arabic thousands separator
    ",": "",
    "'": "",          # swiss thousands separator
    " ": "",
    "%": "",
}


def coerce_number(value: Any) -> float:
    """Parse a number the way TradingView writes it.

    ``float()`` already handles Arabic-Indic and fullwidth digits, but not the
    typographic minus TradingView uses, nor thousands separators. A raw
    ``float()`` on "\u22120.53" raises ValueError -- and a caller that treats that
    as "the indicator is absent" reports present data as missing, which is worse
    than reporting nothing at all.

    Raises ValueError, like ``float``, when the text is genuinely not a number.
    """
    if isinstance(value, bool):
        # bool is an int subclass; a True here means the field was mis-filled.
        raise ValueError(f"expected a number, got boolean {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        raise ValueError(f"expected a number, got {type(value).__name__}")

    text = value.strip()
    if not text:
        raise ValueError("empty string is not a number")
    for needle, replacement in _NUMERIC_SUBSTITUTIONS.items():
        text = text.replace(needle, replacement)
    return float(text)


@dataclass(frozen=True)
class Bar:
    """One OHLCV candle as returned by ``data_get_ohlcv``."""

    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None

    @property
    def range(self) -> float:
        return self.high - self.low


@dataclass
class Quote:
    """Snapshot of ``quote_get``. ``last`` is the only required field."""

    last: float
    volume: float | None = None
    change_pct: float | None = None


@dataclass
class Snapshot:
    """Everything collected for a single symbol on a single pass."""

    symbol: str
    timeframe: str
    collected_at: str
    quote: Quote
    bars: list[Bar] = field(default_factory=list)
    # Raw output of data_get_study_values, normalised to lowercase keys.
    studies: dict[str, float] = field(default_factory=dict)
    # Horizontal levels from data_get_pine_lines / manual drawings.
    pine_lines: list[float] = field(default_factory=list)
    # Free-text annotations from data_get_pine_labels, carried through for the
    # reasoning section only -- never parsed into numbers.
    pine_labels: list[str] = field(default_factory=list)
    # Optional ohlcv summary block (summary: true) kept verbatim.
    ohlcv_summary: dict[str, Any] = field(default_factory=dict)
    # Populated in phase 2 by the market context layer.
    market_context: dict[str, Any] = field(default_factory=dict)
    # Tool calls that failed, so the report can say so out loud.
    errors: list[str] = field(default_factory=list)


_STUDY_ALIASES = {
    "rsi": "rsi",
    "relative strength index": "rsi",
    "macd": "macd",
    "macd histogram": "macd_hist",
    "histogram": "macd_hist",
    "signal": "macd_signal",
    "atr": "atr",
    "average true range": "atr",
    "conversion line": "tenkan",
    "tenkan-sen": "tenkan",
    "tenkan": "tenkan",
    "base line": "kijun",
    "kijun-sen": "kijun",
    "kijun": "kijun",
    "leading span a": "senkou_a",
    "senkou span a": "senkou_a",
    "leading span b": "senkou_b",
    "senkou span b": "senkou_b",
    "lagging span": "chikou",
    "chikou span": "chikou",
}


def normalise_study_key(raw: str) -> str:
    """Map a TradingView study label onto a stable snake_case key.

    ``data_get_study_values`` labels vary with locale and indicator settings
    ("RSI", "Relative Strength Index", "EMA 21"), so collapse the known ones and
    slugify the rest instead of dropping values we do not recognise.
    """
    key = raw.strip().lower()
    if key in _STUDY_ALIASES:
        return _STUDY_ALIASES[key]
    slug = "".join(ch if ch.isalnum() else "_" for ch in key)
    return "_".join(part for part in slug.split("_") if part)


def _require(payload: dict[str, Any], key: str, context: str) -> Any:
    if key not in payload or payload[key] is None:
        raise SnapshotError(f"{context}: missing required field '{key}'")
    return payload[key]


def _as_float(value: Any, context: str) -> float:
    try:
        return coerce_number(value)
    except (TypeError, ValueError) as exc:
        raise SnapshotError(f"{context}: expected a number, got {value!r}") from exc


def parse_bar(payload: dict[str, Any], index: int) -> Bar:
    ctx = f"bars[{index}]"
    volume = payload.get("volume")
    return Bar(
        time=int(_as_float(payload.get("time", index), ctx)),
        open=_as_float(_require(payload, "open", ctx), ctx),
        high=_as_float(_require(payload, "high", ctx), ctx),
        low=_as_float(_require(payload, "low", ctx), ctx),
        close=_as_float(_require(payload, "close", ctx), ctx),
        volume=None if volume is None else _as_float(volume, ctx),
    )


def parse_snapshot(payload: dict[str, Any]) -> Snapshot:
    """Validate and load a snapshot dict produced by the collection layer."""
    if not isinstance(payload, dict):
        raise SnapshotError("snapshot must be a JSON object")

    symbol = str(_require(payload, "symbol", "snapshot"))
    quote_payload = payload.get("quote") or {}
    if not isinstance(quote_payload, dict):
        raise SnapshotError("snapshot.quote must be an object")

    last = quote_payload.get("last")
    if last is None:
        raise SnapshotError(
            f"{symbol}: quote.last is required -- without a live price no entry, "
            "stop or target can be anchored"
        )

    quote = Quote(
        last=_as_float(last, "quote.last"),
        volume=None if quote_payload.get("volume") is None
        else _as_float(quote_payload["volume"], "quote.volume"),
        change_pct=None if quote_payload.get("change_pct") is None
        else _as_float(quote_payload["change_pct"], "quote.change_pct"),
    )

    raw_bars = payload.get("bars") or []
    if not isinstance(raw_bars, list):
        raise SnapshotError("snapshot.bars must be a list")
    bars = [parse_bar(b, i) for i, b in enumerate(raw_bars)]

    for i, bar in enumerate(bars):
        if bar.high < bar.low:
            raise SnapshotError(f"bars[{i}]: high {bar.high} is below low {bar.low}")

    errors = [str(x) for x in (payload.get("errors") or [])]

    studies_raw = payload.get("studies") or {}
    studies: dict[str, float] = {}
    for key, value in studies_raw.items():
        if value is None:
            continue
        try:
            studies[normalise_study_key(key)] = coerce_number(value)
        except (TypeError, ValueError):
            # A value that arrived but could not be read is NOT the same as an
            # absent indicator. Saying "not present on the chart" about a study
            # the chart did return sends the user looking for the wrong problem,
            # so name it instead of dropping it.
            errors.append(
                f"study '{key}' returned {value!r}, which is not a number the "
                "engine can read -- it was excluded from the signal"
            )

    pine_lines: list[float] = []
    for value in payload.get("pine_lines") or []:
        try:
            pine_lines.append(coerce_number(value))
        except (TypeError, ValueError):
            errors.append(
                f"pine line {value!r} is not a readable number -- that level was "
                "excluded from support and resistance"
            )

    return Snapshot(
        symbol=symbol,
        timeframe=str(payload.get("timeframe", "?")),
        collected_at=str(payload.get("collected_at", "")),
        quote=quote,
        bars=bars,
        studies=studies,
        pine_lines=sorted(pine_lines, reverse=True),
        pine_labels=[str(x) for x in (payload.get("pine_labels") or [])],
        ohlcv_summary=payload.get("ohlcv_summary") or {},
        market_context=payload.get("market_context") or {},
        errors=errors,
    )
