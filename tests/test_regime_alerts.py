import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crypto_agent import alerts as al
from crypto_agent import positions as pos
from crypto_agent import regime as rg
from crypto_agent.signal import SymbolAnalysis, TradePlan


def analysis(symbol, trend, strength="strong", actionable=False, quality=0.0):
    # An actionable analysis always carries a plan; the alert layer relies on it.
    plan = TradePlan(entry_low=98.0, entry_high=99.0, stop=95.0, target=110.0,
                     risk_reward=4.0, net_risk_reward=3.9, cost_in_r=0.1,
                     stop_basis="test", target_basis="test", entry_basis="test",
                     distance_to_entry_atr=0.2) if actionable else None
    return SymbolAnalysis(symbol=symbol, timeframe="60", collected_at="",
                          price=100.0, trend=trend, trend_strength=strength,
                          actionable=actionable, confidence="medium",
                          quality_score=quality, plan=plan)


def test_btc_up_with_broad_participation_is_risk_on():
    btc = analysis("BINANCE:BTCUSDT", "bullish")
    others = [analysis(f"X{i}", "bullish") for i in range(4)]
    assert rg.assess(btc, others).sentiment == rg.RISK_ON


def test_btc_down_with_weak_breadth_is_risk_off():
    btc = analysis("BINANCE:BTCUSDT", "bearish")
    others = [analysis(f"X{i}", "bearish") for i in range(4)]
    assert rg.assess(btc, others).sentiment == rg.RISK_OFF


def test_btc_up_while_alts_lag_is_rotation_not_risk_on():
    """The case a BTC-only read gets wrong."""
    btc = analysis("BINANCE:BTCUSDT", "bullish")
    others = [analysis(f"X{i}", "bearish") for i in range(4)]
    result = rg.assess(btc, others)
    assert result.sentiment == rg.MIXED
    assert any("دوران نحو BTC" in note for note in result.notes)


def test_missing_btc_is_reported_not_assumed():
    result = rg.assess(None, [analysis("X", "bullish")])
    assert result.btc_trend == rg.UNKNOWN
    assert any("BTC" in note for note in result.notes)


def test_no_data_at_all_is_unknown():
    assert rg.assess(None, []).sentiment == rg.UNKNOWN


def test_regime_change_is_detected_and_repeats_are_not():
    before = rg.Regime(sentiment=rg.RISK_ON)
    after = rg.Regime(sentiment=rg.RISK_OFF)
    assert rg.describe_change(before, after) is not None
    assert rg.describe_change(after, after) is None
    assert rg.describe_change(None, after) is None, "first run must not alert"


def test_regime_survives_a_corrupt_state_file(tmp_path):
    path = tmp_path / "regime.json"
    path.write_text("{not json", encoding="utf-8")
    assert rg.load_previous(path) is None


def test_regime_round_trip(tmp_path):
    path = tmp_path / "regime.json"
    rg.save(rg.Regime(sentiment=rg.RISK_ON, btc_trend="bullish"), path)
    assert rg.load_previous(path).sentiment == rg.RISK_ON


def _open(symbol="BINANCE:ETHUSDT", entry=100.0, stop=95.0, targets=None):
    book: list[pos.Position] = []
    pos.open_position(book, symbol, entry=entry, size=1.0, stop=stop,
                      targets=targets or [])
    return book


def test_breached_stop_is_critical():
    book = _open()
    found = al.position_alerts(book, {"ETHUSDT": 94.0})
    assert found[0].kind == "stop_breached"
    assert found[0].severity == al.CRITICAL


def test_reached_target_is_critical():
    book = _open(targets=[110.0])
    found = al.position_alerts(book, {"ETHUSDT": 111.0})
    assert found[0].kind == "target_reached"


def test_approaching_the_stop_warns_before_it_is_hit():
    book = _open(entry=100.0, stop=95.0)
    assert al.position_alerts(book, {"ETHUSDT": 96.0})[0].kind == "stop_near"
    # Comfortably above the stop: nothing to say.
    assert al.position_alerts(book, {"ETHUSDT": 99.0}) == []


def test_a_position_with_no_price_is_flagged_not_skipped():
    book = _open()
    found = al.position_alerts(book, {})
    assert found[0].kind == "position_no_price"


def test_new_setups_skip_symbols_already_held():
    held = analysis("BINANCE:ETHUSDT", "bullish", actionable=True, quality=80.0)
    fresh = analysis("BINANCE:SOLUSDT", "bullish", actionable=True, quality=80.0)
    found = al.setup_alerts([held, fresh], open_symbols={"ETHUSDT"})
    assert [a.symbol for a in found] == ["SOLUSDT"]


def test_low_quality_setups_do_not_alert():
    weak = analysis("BINANCE:SOLUSDT", "bullish", actionable=True, quality=40.0)
    assert al.setup_alerts([weak], open_symbols=set(), min_quality=60.0) == []


def test_alerts_are_ordered_by_urgency():
    book = _open(entry=100.0, stop=95.0)
    fresh = analysis("BINANCE:SOLUSDT", "bullish", actionable=True, quality=80.0)
    found = al.collect([fresh], book, {"ETHUSDT": 94.0}, None,
                       rg.Regime(sentiment=rg.RISK_ON))
    severities = [a.severity for a in found]
    assert severities == sorted(severities, key=lambda s: al.SEVERITY_ORDER[s])
    assert found[0].kind == "stop_breached", "money at risk outranks a new idea"
