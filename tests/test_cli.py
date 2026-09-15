import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crypto_agent.cli import main
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
    assert "فشل تحميلها" in out
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
