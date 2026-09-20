import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crypto_agent.report import render_report
from crypto_agent.schema import parse_snapshot
from crypto_agent.signal import analyse, watchlist_entry
from tests.helpers import bars_from_path, make_snapshot
from tests.test_signal import BEARISH, BULLISH_PULLBACK

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "watchlist.json"
LIVE_CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def analyse_symbol(symbol, path=BULLISH_PULLBACK, config=LIVE_CONFIG):
    bars = bars_from_path(path, steps=14)
    snap = parse_snapshot(make_snapshot(
        bars, bars[-1]["close"], {"RSI": 56.0, "MACD": 1.2, "Signal": 0.7},
        [126.0], symbol))
    return analyse(snap, config)


def test_every_watchlist_entry_declares_a_tier_and_slippage():
    for entry in LIVE_CONFIG["watchlist"]:
        assert entry.get("tier"), f"{entry['symbol']} has no tier"
        assert isinstance(entry.get("slippage_pct"), (int, float)), entry["symbol"]
        assert entry["symbol"].startswith("BINANCE:"), entry["symbol"]


def test_thinner_markets_are_charged_more_slippage():
    """Using BTC's spread for a mid-cap makes thin setups look tradeable."""
    by_tier = {}
    for entry in LIVE_CONFIG["watchlist"]:
        by_tier.setdefault(entry["tier"], set()).add(entry["slippage_pct"])
    assert max(by_tier["major"]) < min(by_tier["large"]) < min(by_tier["mid"])


def test_the_same_setup_costs_more_in_a_mid_cap():
    major = analyse_symbol("BINANCE:BTCUSDT")
    mid = analyse_symbol("BINANCE:CRVUSDT")
    assert major.tier == "major" and mid.tier == "mid"
    assert major.plan is not None and mid.plan is not None
    assert mid.plan.cost_in_r > major.plan.cost_in_r
    assert mid.plan.net_risk_reward < major.plan.net_risk_reward


def test_a_symbol_outside_the_watchlist_falls_back_to_the_global_cost():
    result = analyse_symbol("BINANCE:NOTLISTEDUSDT")
    assert result.tier == ""
    assert result.plan is not None
    expected = 2 * (LIVE_CONFIG["risk"]["fee_pct"] + LIVE_CONFIG["risk"]["slippage_pct"])
    risk = result.plan.entry_low - result.plan.stop
    assert result.plan.cost_in_r == pytest.approx(
        result.plan.entry_low * expected / 100.0 / risk)


def test_watchlist_entry_matches_on_the_bare_ticker():
    assert watchlist_entry("BTCUSDT", LIVE_CONFIG)["tier"] == "major"
    assert watchlist_entry("BINANCE:BTCUSDT", LIVE_CONFIG)["tier"] == "major"
    assert watchlist_entry("NOPEUSDT", LIVE_CONFIG) == {}


def test_rejections_carry_a_machine_readable_kind():
    bearish = analyse_symbol("BINANCE:ETHUSDT", path=BEARISH)
    assert bearish.rejected_kind, "a rejection with no kind cannot be grouped"
    assert bearish.plan is None


def test_a_long_watch_list_collapses_to_one_line_per_reason():
    """35 rejection paragraphs is a report nobody reads."""
    rejected = [analyse_symbol(f"BINANCE:X{i}USDT", path=BEARISH) for i in range(30)]
    report = render_report(rejected, {}, lang="en", compact_watching=True)

    watching = report.split("=== Watching")[1]
    # One grouped line, not thirty.
    assert watching.count("\n-") <= 3
    assert "X0USDT" in watching and "X29USDT" in watching
    assert "Scanned 30 symbols." in report


def test_a_short_watch_list_still_shows_each_reason_in_full():
    """Grouping is for long lists; a few symbols keep the reason that names the
    levels to wait for."""
    rejected = [analyse_symbol(f"BINANCE:X{i}USDT", path=BEARISH) for i in range(3)]
    report = render_report(rejected, {}, lang="en", compact_watching=True)

    assert report.count("Ichimoku cloud") == 3, "each symbol keeps its own reason"
    # The prose carries the actual cloud range, which a grouped line cannot.
    assert "113.6" in report


def test_opportunities_beyond_the_limit_are_counted_not_dropped():
    good = [analyse_symbol(f"BINANCE:X{i}USDT") for i in range(8)]
    assert all(a.actionable for a in good)
    report = render_report(good, {}, lang="en", max_opportunities=3)

    assert "and 5 more opportunities" in report
    assert report.count("Entry:") == 3


def test_only_the_top_few_carry_full_reasoning():
    good = [analyse_symbol(f"BINANCE:X{i}USDT") for i in range(5)]
    report = render_report(good, {}, lang="en", max_opportunities=5,
                           full_reasoning_for=2)
    # Reasoning blocks appear twice; every entry still shows its levels.
    assert report.count("Reasoning:") == 2
    assert report.count("Entry:") == 5


def test_the_shipped_config_report_settings_are_usable():
    settings = {k: v for k, v in LIVE_CONFIG["report"].items()
                if not k.startswith("_")}
    good = [analyse_symbol(f"BINANCE:X{i}USDT") for i in range(3)]
    render_report(good, {}, lang="en", **settings)


def _near_miss_config():
    """Confidence bar raised to high, so a medium setup lands as a near miss."""
    config = json.loads(json.dumps(LIVE_CONFIG))
    config["filters"]["min_confidence_to_report"] = "high"
    return config


def test_a_valid_setup_under_the_confidence_bar_is_shown_not_buried():
    """The user asked not to miss opportunities. Collapsing a real setup into
    the same group as symbols the market never offered does exactly that."""
    config = _near_miss_config()
    results = [analyse_symbol(f"BINANCE:X{i}USDT", config=config) for i in range(3)]
    for r in results:
        r.confidence = "medium"
        r.actionable = False
        r.rejected_kind = "low_confidence"

    report = render_report(results, {}, lang="en", show_near_misses=True)

    assert "Near misses" in report
    # Their actual levels are shown, not just their names.
    assert report.count("R:R") >= 3
    assert "Not recommendations" in report


def test_near_misses_are_ranked_and_capped():
    config = _near_miss_config()
    results = []
    for i in range(8):
        r = analyse_symbol(f"BINANCE:X{i}USDT", config=config)
        r.confidence, r.actionable, r.rejected_kind = "medium", False, "low_confidence"
        r.quality_score = float(i)
        results.append(r)

    report = render_report(results, {}, lang="en", show_near_misses=True,
                           max_near_misses=3)
    # The header itself ends in "===", so slice after it, not at it.
    near = report.split("lower confidence) ===")[1].split("=== Watching")[0]

    assert "X7USDT" in near and "X0USDT" not in near, "highest quality first"
    assert "and 5 more near the threshold" in report


def test_near_misses_do_not_also_appear_in_the_watch_list():
    config = _near_miss_config()
    r = analyse_symbol("BINANCE:X0USDT", config=config)
    r.confidence, r.actionable, r.rejected_kind = "medium", False, "low_confidence"
    report = render_report([r], {}, lang="en", show_near_misses=True)

    watching = report.split("=== Watching")[1]
    assert "X0USDT" not in watching


def test_the_section_can_be_switched_off():
    config = _near_miss_config()
    r = analyse_symbol("BINANCE:X0USDT", config=config)
    r.confidence, r.actionable, r.rejected_kind = "medium", False, "low_confidence"
    report = render_report([r], {}, lang="en", show_near_misses=False)

    assert "Near misses" not in report
    assert "X0USDT" in report, "still reported, just in the watch list"


def test_actionable_setups_never_land_in_near_misses():
    good = [analyse_symbol(f"BINANCE:X{i}USDT") for i in range(3)]
    assert all(a.actionable for a in good)
    report = render_report(good, {}, lang="en", show_near_misses=True)
    assert "Near misses" not in report
