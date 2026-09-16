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
    assert plan.net_risk_reward >= CONFIG["risk"]["min_risk_reward"]
    assert plan.cost_in_r > 0, "a plan that ignores fees overstates its own edge"
    assert plan.net_risk_reward < plan.risk_reward
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
        assert result.plan.net_risk_reward >= CONFIG["risk"]["min_risk_reward"]
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


def test_cost_in_r_is_round_trip_cost_over_stop_distance():
    from crypto_agent.signal import cost_in_r
    cfg = {"fee_pct": 0.1, "slippage_pct": 0.03}
    # 0.26% round trip on a 100-priced asset = 0.26 of price; against a 1.0 stop
    # that is 0.26R.
    assert cost_in_r(100.0, 1.0, cfg) == pytest.approx(0.26, rel=1e-6)
    assert cost_in_r(100.0, 2.0, cfg) == pytest.approx(0.13, rel=1e-6)
    assert cost_in_r(100.0, 0.0, cfg) == 0.0


def test_tight_stops_on_a_quiet_15m_chart_are_rejected_on_cost():
    """The core hazard of a 15-minute holding period, in one test.

    Real BTC 15m bars move a fraction of a percent, so a structural stop lands
    ~0.1% from entry. A 0.26% round trip against that is over 2R -- the trade
    cannot pay for itself no matter how good the read is.
    """
    quiet = [60000, 60120, 60050, 60200, 60130, 60280, 60200]
    snap = build(quiet, {"RSI": 56.0, "MACD": 1.2, "Signal": 0.7},
                 pine_lines=[60400.0], symbol="BINANCE:BTCUSDT")
    snap.bars[:] = [b for b in snap.bars]  # bars already built by the helper
    result = analyse(snap, CONFIG)

    assert result.plan is None
    assert result.actionable is False
    assert "fees and slippage" in result.rejected_reason.lower()


def test_wide_stops_still_pass_the_cost_gate():
    """The gate must reject tight stops, not every trade."""
    snap = build(BULLISH_PULLBACK, {"RSI": 56.0, "MACD": 1.2, "Signal": 0.7},
                 pine_lines=[126.0])
    result = analyse(snap, CONFIG)
    assert result.plan is not None
    assert result.plan.cost_in_r < CONFIG["risk"]["max_cost_in_r"]


def test_computed_emas_are_a_note_not_a_data_gap():
    """A TradingView Basic account allows two indicators, so a user on that plan
    never has chart EMAs. Computing them from the same bars is equivalent, so it
    must not permanently cap their confidence."""
    snap = build(BULLISH_PULLBACK, {"RSI": 56.0, "MACD": 1.2, "Signal": 0.7},
                 pine_lines=[126.0])
    result = analyse(snap, CONFIG)

    assert result.warnings == [], f"computed EMAs are not a gap: {result.warnings}"
    assert any("computed from the same bars" in n for n in result.notes)
    assert result.confidence == "high", \
        "a full set of signals should reach high confidence on a Basic account"


def test_a_genuinely_missing_indicator_is_still_a_warning():
    snap = build(BULLISH_PULLBACK, {"RSI": 56.0}, pine_lines=[126.0])
    result = analyse(snap, CONFIG)
    assert any("MACD" in w for w in result.warnings)
    assert result.confidence != "high"


def test_an_unreadable_value_lowers_confidence_like_a_gap():
    """An unparseable study is a real problem, unlike a computed EMA."""
    bars = bars_from_path(BULLISH_PULLBACK)
    payload = make_snapshot(bars, bars[-1]["close"],
                            {"RSI": 56.0, "MACD": "n/a"}, [126.0])
    result = analyse(parse_snapshot(payload), CONFIG)
    assert any("not a number" in w for w in result.warnings)
