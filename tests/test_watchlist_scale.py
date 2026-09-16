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
