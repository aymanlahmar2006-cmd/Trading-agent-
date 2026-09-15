import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crypto_agent.i18n import t
from crypto_agent.journal import append_csv, append_jsonl
from crypto_agent.report import fmt_price, render_report
from crypto_agent.schema import parse_snapshot
from crypto_agent.signal import analyse
from tests.helpers import CONFIG, bars_from_path, make_snapshot
from tests.test_signal import BEARISH, BULLISH_PULLBACK, build


def test_price_formatting_adapts_to_magnitude():
    assert fmt_price(59473.75) == "59,473.75"
    assert fmt_price(0.00002317).startswith("0.0000")
    assert fmt_price(None) == "—"


def test_report_separates_opportunities_from_watching():
    good = analyse(build(BULLISH_PULLBACK, {"RSI": 56.0, "MACD": 1.2, "Signal": 0.7},
                         [126.0], symbol="BINANCE:SOLUSDT"), CONFIG)
    bad = analyse(build(BEARISH, {"RSI": 38.0}, symbol="BINANCE:ADAUSDT"), CONFIG)

    report = render_report([bad, good])
    assert "=== Market Context ===" in report
    assert "=== Top Opportunities ===" in report
    assert "=== Watching" in report
    # The tradeable one is promoted regardless of input order.
    assert report.index("SOLUSDT") < report.index("ADAUSDT")
    assert "R:R:" in report
    assert t("safety_note", "ar") in report


def test_report_states_market_context_is_missing_rather_than_faking_it():
    result = analyse(build(BEARISH, {"RSI": 38.0}), CONFIG)
    assert t("context_unavailable", "ar") in render_report([result])


def test_report_ranks_opportunities_by_quality_score():
    studies = {"RSI": 56.0, "MACD": 1.2, "Signal": 0.7}
    a = analyse(build(BULLISH_PULLBACK, studies, [126.0], symbol="BINANCE:AAAUSDT"), CONFIG)
    b = analyse(build(BULLISH_PULLBACK, studies, [126.0], symbol="BINANCE:BBBUSDT"), CONFIG)
    b.quality_score = a.quality_score + 10
    report = render_report([a, b])
    assert report.index("BBBUSDT") < report.index("AAAUSDT")


def test_journal_round_trips_to_csv_and_jsonl(tmp_path):
    results = [
        analyse(build(BULLISH_PULLBACK, {"RSI": 56.0, "MACD": 1.2, "Signal": 0.7}, [126.0]), CONFIG),
        analyse(build(BEARISH, {"RSI": 38.0}), CONFIG),
    ]
    jsonl_path = tmp_path / "signals.jsonl"
    csv_path = tmp_path / "signals.csv"

    append_jsonl(results, jsonl_path)
    append_csv(results, csv_path)
    # Appending twice must not duplicate the CSV header.
    append_csv(results, csv_path)

    records = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    assert records[0]["votes"], "journal must keep the evidence, not just the verdict"

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert len(rows) == 4
    assert rows[0]["symbol"] == "BINANCE:TESTUSDT"


def test_sub_dollar_coin_keeps_precision_in_reasoning_and_levels():
    """A 0.00002-priced altcoin must not render every level as 0.0000.

    Regression: the reasoning strings used a fixed 4-decimal format, which
    collapsed distinct levels on cheap coins into identical-looking numbers.
    """
    tiny = [v / 5000.0 for v in BULLISH_PULLBACK]
    result = analyse(build(tiny, {"RSI": 56.0, "MACD": 0.0004, "Signal": 0.0002},
                           [126.0 / 5000.0], symbol="BINANCE:PEPEUSDT"), CONFIG)
    text = render_report([result])
    assert "0.0000 " not in text
    assert result.plan is None or result.plan.entry_low > 0
    joined = " ".join(result.reasoning)
    assert "0.0000 " not in joined
