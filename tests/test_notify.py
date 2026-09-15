import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crypto_agent import notify as nt
from crypto_agent.alerts import Alert


def test_message_is_always_written_to_the_outbox(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    outbox = tmp_path / "journal" / "outbox.log"

    nt.notify("hello", channel="auto", outbox=outbox)
    assert "hello" in outbox.read_text(encoding="utf-8")


def test_unconfigured_telegram_degrades_to_file_rather_than_raising(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    result = nt.notify("x", channel="auto", outbox=tmp_path / "out.log")
    assert result.ok and result.channel == "file"


def test_explicit_telegram_without_credentials_reports_failure(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    result = nt.notify("x", channel="telegram", outbox=tmp_path / "out.log")
    assert not result.ok
    assert "not configured" in result.detail


def test_a_failed_send_still_keeps_the_message(tmp_path, monkeypatch):
    """A dropped alert must remain recoverable, not vanish with the error."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(nt, "send_telegram",
                        lambda text, timeout=10.0: nt.Delivery("telegram", False, "boom"))
    outbox = tmp_path / "out.log"

    result = nt.notify("important", channel="auto", outbox=outbox)
    assert not result.ok
    assert "important" in outbox.read_text(encoding="utf-8")


def test_successful_send_reports_telegram(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(nt, "send_telegram",
                        lambda text, timeout=10.0: nt.Delivery("telegram", True))
    result = nt.notify("x", channel="auto", outbox=tmp_path / "out.log")
    assert result.ok and result.channel == "telegram"


def test_send_telegram_never_raises_on_a_network_failure(monkeypatch):
    def explode(*a, **k):
        raise OSError("network down")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(nt.urllib.request, "urlopen", explode)

    result = nt.send_telegram("x")
    assert not result.ok and "network down" in result.detail


def test_format_alerts_is_empty_when_there_is_nothing_to_say():
    assert nt.format_alerts([]) == ""


def test_format_alerts_includes_each_alert_and_the_safety_note():
    from crypto_agent.i18n import t
    alerts = [Alert("k", "critical", "عنوان", "تفصيل", "BTCUSDT", "🔴")]
    text = nt.format_alerts(alerts, lang="ar")
    assert "عنوان" in text and "تفصيل" in text
    assert t("safety_note", "ar") in text


def test_telegram_messages_stay_arabic_by_default():
    """The console cannot render right-to-left text; a phone can."""
    from crypto_agent.i18n import t
    alerts = [Alert("k", "info", "title", "detail", "BTCUSDT", "🔵")]
    assert t("safety_note", "ar") in nt.format_alerts(alerts)
