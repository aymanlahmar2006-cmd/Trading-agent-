import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crypto_agent import i18n


def test_windows_gets_english_because_its_console_cannot_reorder_rtl(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert i18n.resolve("auto") == i18n.EN


def test_explicit_choice_beats_detection(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert i18n.resolve("ar") == i18n.AR
    monkeypatch.setattr(sys, "platform", "linux")
    assert i18n.resolve("en") == i18n.EN


def test_a_non_utf8_console_falls_back_to_english(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "stdout", type("S", (), {"encoding": "cp1252"})())
    assert i18n.resolve("auto") == i18n.EN


def test_env_var_can_force_a_language(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("CRYPTO_AGENT_LANG", "en")
    assert i18n.resolve("auto") == i18n.EN


def test_every_label_exists_in_both_languages():
    missing = [key for key, entry in i18n.T.items()
               if i18n.AR not in entry or i18n.EN not in entry]
    assert missing == [], f"labels missing a translation: {missing}"


def test_placeholders_match_across_languages():
    """A format field present in one language but not the other crashes at runtime."""
    import re
    mismatched = []
    for key, entry in i18n.T.items():
        fields = {lang: set(re.findall(r"\{(\w+)", text))
                  for lang, text in entry.items()}
        if len(set(map(frozenset, fields.values()))) > 1:
            mismatched.append((key, fields))
    assert mismatched == [], f"placeholder mismatch: {mismatched}"


def test_unknown_key_returns_itself_rather_than_raising():
    assert i18n.t("no_such_key", i18n.EN) == "no_such_key"
