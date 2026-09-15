import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import find_chat_id as fc


def test_extracts_id_and_name_from_a_normal_message():
    payload = {"ok": True, "result": [
        {"message": {"chat": {"id": 987654321, "first_name": "Ayman",
                              "type": "private"}}},
    ]}
    assert fc.chats_from(payload) == [("987654321", "Ayman")]


def test_deduplicates_repeated_chats():
    msg = {"message": {"chat": {"id": 5, "first_name": "A", "type": "private"}}}
    assert len(fc.chats_from({"result": [msg, msg, msg]})) == 1


def test_reads_group_titles_and_channel_posts():
    payload = {"result": [
        {"channel_post": {"chat": {"id": -100123, "title": "My Channel",
                                   "type": "channel"}}},
    ]}
    assert fc.chats_from(payload) == [("-100123", "My Channel")]


def test_falls_back_to_username_then_type_when_unnamed():
    payload = {"result": [
        {"message": {"chat": {"id": 1, "username": "someone", "type": "private"}}},
        {"message": {"chat": {"id": 2, "type": "private"}}},
    ]}
    found = dict(fc.chats_from(payload))
    assert found["1"] == "someone"
    assert found["2"] == "private"


def test_empty_result_yields_nothing_rather_than_raising():
    assert fc.chats_from({"ok": True, "result": []}) == []
    assert fc.chats_from({}) == []


def test_malformed_updates_are_skipped_not_fatal():
    payload = {"result": [{"message": {}}, {"message": {"chat": {}}}, {"junk": 1}]}
    assert fc.chats_from(payload) == []


def test_missing_token_exits_with_guidance(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert fc.main() == 1
    assert "setx" in capsys.readouterr().out


def test_a_401_says_the_token_is_wrong(monkeypatch, capsys):
    import urllib.error
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bad")

    def raise_401(token, timeout=15.0):
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)
    monkeypatch.setattr(fc, "fetch_updates", raise_401)

    assert fc.main() == 1
    assert "token is wrong" in capsys.readouterr().out


def test_no_messages_tells_the_user_to_press_start(monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setattr(fc, "fetch_updates", lambda *a, **k: {"ok": True, "result": []})
    assert fc.main() == 1
    assert "Start" in capsys.readouterr().out


def test_success_prints_the_setx_line(monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setattr(fc, "fetch_updates", lambda *a, **k: {"ok": True, "result": [
        {"message": {"chat": {"id": 42, "first_name": "Ayman", "type": "private"}}}]})
    assert fc.main() == 0
    out = capsys.readouterr().out
    assert "42" in out and 'setx TELEGRAM_CHAT_ID "42"' in out


def test_the_token_is_never_printed(monkeypatch, capsys):
    """The output gets pasted into chats and screenshots -- keep the token out."""
    secret = "8719810099:AAEaSECRETVALUE"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", secret)
    monkeypatch.setattr(fc, "fetch_updates", lambda *a, **k: {"ok": True, "result": [
        {"message": {"chat": {"id": 42, "first_name": "Ayman", "type": "private"}}}]})
    fc.main()
    assert secret not in capsys.readouterr().out
