import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crypto_agent.cli import main
from crypto_agent.i18n import t
from tests.helpers import bars_from_path, make_snapshot
from tests.test_signal import BULLISH_PULLBACK

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "watchlist.json"


def write_snapshot(tmp_path, payload):
    path = tmp_path / "snap.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_cli_analyzes_a_single_snapshot(tmp_path, capsys):
    bars = bars_from_path(BULLISH_PULLBACK)
    snap = make_snapshot(bars, bars[-1]["close"], {"RSI": 56.0, "MACD": 1.2, "Signal": 0.7}, [126.0])
    path = write_snapshot(tmp_path, snap)

    code = main(["analyze", str(path), "--config", str(CONFIG_PATH)])
    out = capsys.readouterr().out

    assert code == 0
    assert "=== Top Opportunities ===" in out
    assert "TESTUSDT" in out


def test_cli_accepts_a_list_of_snapshots(tmp_path, capsys):
    bars = bars_from_path(BULLISH_PULLBACK)
    payload = [
        make_snapshot(bars, bars[-1]["close"], {"RSI": 56.0, "MACD": 1.2, "Signal": 0.7}, [126.0], "BINANCE:AAAUSDT"),
        make_snapshot(bars, bars[-1]["close"], {"RSI": 56.0, "MACD": 1.2, "Signal": 0.7}, [126.0], "BINANCE:BBBUSDT"),
    ]
    path = write_snapshot(tmp_path, payload)

    assert main(["analyze", str(path), "--config", str(CONFIG_PATH)]) == 0
    out = capsys.readouterr().out
    assert "AAAUSDT" in out and "BBBUSDT" in out


def test_cli_reports_bad_symbols_instead_of_dropping_them(tmp_path, capsys):
    bars = bars_from_path(BULLISH_PULLBACK)
    good = make_snapshot(bars, bars[-1]["close"], {"RSI": 56.0, "MACD": 1.2, "Signal": 0.7}, [126.0], "BINANCE:AAAUSDT")
    broken = make_snapshot(bars, 1.0, {}, [], "BINANCE:BROKEN")
    broken["quote"] = {}
    path = write_snapshot(tmp_path, [good, broken])

    assert main(["analyze", str(path), "--config", str(CONFIG_PATH)]) == 0
    out = capsys.readouterr().out
    assert t("load_failures", "ar") in out
    assert "quote.last" in out


def test_cli_fails_when_nothing_could_be_parsed(tmp_path, capsys):
    broken = make_snapshot([], 1.0)
    broken["quote"] = {}
    path = write_snapshot(tmp_path, broken)
    assert main(["analyze", str(path), "--config", str(CONFIG_PATH)]) == 1


def test_cli_writes_json_and_logs(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bars = bars_from_path(BULLISH_PULLBACK)
    snap = make_snapshot(bars, bars[-1]["close"], {"RSI": 56.0, "MACD": 1.2, "Signal": 0.7}, [126.0])
    path = write_snapshot(tmp_path, snap)
    out_path = tmp_path / "out" / "result.json"

    code = main(["analyze", str(path), "--config", str(CONFIG_PATH),
                 "--json-out", str(out_path), "--log"])
    assert code == 0
    assert json.loads(out_path.read_text(encoding="utf-8"))[0]["symbol"] == "BINANCE:TESTUSDT"
    assert (tmp_path / "logs" / "signals.jsonl").exists()
    assert (tmp_path / "logs" / "signals.csv").exists()


def _run(monkeypatch, tmp_path, argv):
    monkeypatch.chdir(tmp_path)
    return main(argv)


def test_open_records_a_fill_and_rejects_a_duplicate(tmp_path, monkeypatch, capsys):
    args = ["open", "--symbol", "BINANCE:SOLUSDT", "--entry", "100", "--size", "10",
            "--stop", "95", "--target", "115", "--config", str(CONFIG_PATH)]
    assert _run(monkeypatch, tmp_path, args) == 0
    assert (tmp_path / "journal" / "positions.json").exists()
    capsys.readouterr()

    assert _run(monkeypatch, tmp_path, args) == 1
    assert t("already_open", "ar", sym="BINANCE:SOLUSDT", id="").split("(")[0].strip() in capsys.readouterr().err


def test_open_rejects_a_stop_above_entry(tmp_path, monkeypatch, capsys):
    code = _run(monkeypatch, tmp_path,
                ["open", "--symbol", "BINANCE:SOLUSDT", "--entry", "100",
                 "--size", "10", "--stop", "105", "--config", str(CONFIG_PATH)])
    assert code == 1
    assert "at or above entry" in capsys.readouterr().err
    assert not (tmp_path / "journal" / "positions.json").exists()


def test_close_reports_the_result_in_r(tmp_path, monkeypatch, capsys):
    _run(monkeypatch, tmp_path,
         ["open", "--symbol", "BINANCE:SOLUSDT", "--entry", "100", "--size", "10",
          "--stop", "95", "--config", str(CONFIG_PATH)])
    capsys.readouterr()

    assert _run(monkeypatch, tmp_path,
                ["close", "--symbol", "SOLUSDT", "--price", "110"]) == 0
    out = capsys.readouterr().out
    assert t("closed", "ar") in out and "R)" in out


def test_close_without_an_open_position_fails(tmp_path, monkeypatch, capsys):
    code = _run(monkeypatch, tmp_path,
                ["close", "--symbol", "SOLUSDT", "--price", "110"])
    assert code == 1
    assert t("no_open_position", "ar", sym="SOLUSDT") in capsys.readouterr().err


def test_status_shows_live_r_and_realised_summary(tmp_path, monkeypatch, capsys):
    _run(monkeypatch, tmp_path,
         ["open", "--symbol", "BINANCE:SOLUSDT", "--entry", "100", "--size", "10",
          "--stop", "95", "--config", str(CONFIG_PATH)])
    capsys.readouterr()

    assert _run(monkeypatch, tmp_path, ["status", "--price", "SOLUSDT=104"]) == 0
    out = capsys.readouterr().out
    assert "SOLUSDT" in out and "R" in out


def test_status_rejects_a_malformed_price(tmp_path, monkeypatch, capsys):
    assert _run(monkeypatch, tmp_path, ["status", "--price", "SOLUSDT"]) == 1
    assert t("bad_price_format", "ar", item="SOLUSDT") in capsys.readouterr().err


def test_watch_reports_regime_and_alerts_without_sending(tmp_path, monkeypatch, capsys):
    bars = bars_from_path(BULLISH_PULLBACK)
    studies = {"RSI": 56.0, "MACD": 1.2, "Signal": 0.7}
    payload = [
        make_snapshot(bars, bars[-1]["close"], studies, [126.0], "BINANCE:BTCUSDT"),
        make_snapshot(bars, bars[-1]["close"], studies, [126.0], "BINANCE:SOLUSDT"),
    ]
    path = tmp_path / "multi.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    code = _run(monkeypatch, tmp_path,
                ["watch", str(path), "--config", str(CONFIG_PATH), "--no-notify"])
    out = capsys.readouterr().out

    assert code == 0
    assert "=== Market Context ===" in out
    assert "Risk Sentiment" in out
    assert t("alerts_header", "ar") in out
    # A regime file is written so the next run can detect a flip.
    assert (tmp_path / "journal" / "regime.json").exists()


def test_watch_does_not_alert_on_a_symbol_already_held(tmp_path, monkeypatch, capsys):
    bars = bars_from_path(BULLISH_PULLBACK)
    studies = {"RSI": 56.0, "MACD": 1.2, "Signal": 0.7}
    payload = [make_snapshot(bars, bars[-1]["close"], studies, [126.0], "BINANCE:SOLUSDT")]
    path = tmp_path / "one.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    _run(monkeypatch, tmp_path,
         ["open", "--symbol", "BINANCE:SOLUSDT", "--entry", "100", "--size", "1",
          "--stop", "95", "--config", str(CONFIG_PATH)])
    capsys.readouterr()

    _run(monkeypatch, tmp_path,
         ["watch", str(path), "--config", str(CONFIG_PATH), "--no-notify"])
    out = capsys.readouterr().out
    assert "new_setup" not in out and t("new_setup_title", "ar", sym="SOLUSDT", q=0).split(":")[1].split("(")[0].strip() not in out, \
        "a held symbol must not be pitched as a new idea"


def test_cli_output_language_is_stable_on_windows(tmp_path, monkeypatch, capsys):
    """The report must not change language with the host OS once pinned.

    Regression: CLI tests asserted Arabic while Windows resolved to English.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    bars = bars_from_path(BULLISH_PULLBACK)
    snap = make_snapshot(bars, bars[-1]["close"],
                         {"RSI": 56.0, "MACD": 1.2, "Signal": 0.7}, [126.0])
    path = write_snapshot(tmp_path, snap)

    # conftest pins CRYPTO_AGENT_LANG=ar, which outranks the platform.
    assert main(["analyze", str(path), "--config", str(CONFIG_PATH)]) == 0
    assert t("watching", "ar") in capsys.readouterr().out

    # And an explicit flag always wins, on any platform.
    assert main(["analyze", str(path), "--config", str(CONFIG_PATH),
                 "--lang", "en"]) == 0
    assert t("watching", "en") in capsys.readouterr().out
