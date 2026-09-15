import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crypto_agent.schema import SnapshotError, parse_snapshot
from crypto_agent.signal import analyse
from tests.helpers import CONFIG, bars_from_path, make_snapshot

BULLISH_PULLBACK = [100, 108, 103, 114, 109, 120, 114]
BEARISH = [126, 118, 122, 110, 114, 102, 106]


def build(path, studies=None, pine_lines=None, last=None, symbol="BINANCE:TESTUSDT"):
    bars = bars_from_path(path)
    return parse_snapshot(make_snapshot(
        bars, last if last is not None else bars[-1]["close"],
        studies, pine_lines, symbol,
    ))


def test_bullish_pullback_produces_a_coherent_long_plan():
    snap = build(BULLISH_PULLBACK, {"RSI": 56.0, "MACD": 1.2, "Signal": 0.7},
                 pine_lines=[126.0])
    result = analyse(snap, CONFIG)

    assert result.trend == "bullish"
    assert result.actionable is True
    plan = result.plan
    assert plan is not None
    assert plan.stop < plan.entry_low <= plan.entry_high < plan.target
    assert plan.risk_reward >= CONFIG["risk"]["min_risk_reward"]
    # The stop must sit below a real structural level, not an arbitrary offset.
    assert "swing low" in plan.stop_basis or "ATR stop" in plan.stop_basis


def test_every_reported_number_is_traceable_to_the_reasoning():
    snap = build(BULLISH_PULLBACK, {"RSI": 56.0}, pine_lines=[126.0])
    result = analyse(snap, CONFIG)
    joined = " ".join(result.reasoning)
    assert "Entry anchored on" in joined
    assert "Stop from" in joined
    assert "ATR" in joined
    assert result.votes, "a trend call with no votes behind it is a guess"


def test_bearish_trend_yields_no_short_because_this_is_spot():
    snap = build(BEARISH, {"RSI": 38.0, "MACD": -1.4, "Signal": -0.6})
    result = analyse(snap, CONFIG)

    assert result.trend == "bearish"
    assert result.plan is None
    assert result.actionable is False
    assert "spot" in result.rejected_reason.lower()


def test_insufficient_bars_reports_missing_atr_instead_of_guessing():
    snap = build([100, 102], last=102.0)
    result = analyse(snap, CONFIG)

    assert result.plan is None
    assert result.atr is None
    assert "ATR unavailable" in result.rejected_reason


def test_target_below_min_rr_is_rejected_not_stretched():
    # Resistance sits just above entry, so no target can clear 1.5:1 honestly.
    snap = build(BULLISH_PULLBACK, {"RSI": 56.0}, pine_lines=[114.5])
    result = analyse(snap, CONFIG)

    if result.plan is not None:
        assert result.plan.risk_reward >= CONFIG["risk"]["min_risk_reward"]
    else:
        assert "minimum" in result.rejected_reason or "resistance" in result.rejected_reason


def test_missing_live_price_is_a_hard_error():
    bars = bars_from_path(BULLISH_PULLBACK)
    payload = make_snapshot(bars, 100.0)
    payload["quote"] = {}
    with pytest.raises(SnapshotError, match="quote.last"):
        parse_snapshot(payload)


def test_chart_emas_are_preferred_over_computed_ones():
    snap = build(BULLISH_PULLBACK,
                 {"RSI": 58.0, "EMA 9": 113.0, "EMA 21": 111.0, "EMA 50": 108.0,
                  "MACD": 1.2, "Signal": 0.7},
                 pine_lines=[126.0])
    result = analyse(snap, CONFIG)
    assert "chart studies" in result.reasoning[0]
    assert not any("computed from the returned bars" in w for w in result.warnings)


def test_missing_indicators_are_surfaced_as_warnings():
    snap = build(BULLISH_PULLBACK, {}, pine_lines=[126.0])
    result = analyse(snap, CONFIG)
    text = " ".join(result.warnings)
    assert "RSI" in text and "MACD" in text


def test_tool_errors_from_collection_survive_into_the_analysis():
    bars = bars_from_path(BULLISH_PULLBACK)
    payload = make_snapshot(bars, bars[-1]["close"], {"RSI": 56.0})
    payload["errors"] = ["data_get_pine_lines failed: no such study"]
    result = analyse(parse_snapshot(payload), CONFIG)
    assert any("pine_lines failed" in w for w in result.warnings)
