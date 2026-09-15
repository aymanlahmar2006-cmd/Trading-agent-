"""Shared test configuration.

The agent picks its output language from the platform: English on Windows,
whose console cannot render right-to-left text, Arabic elsewhere. That made the
suite pass on Linux and fail on Windows purely on which labels came back. Pin
the language for every test so assertions mean the same thing on any machine;
the detection logic itself is covered in test_i18n.py, which clears this.
"""

import pytest


@pytest.fixture(autouse=True)
def pinned_language(monkeypatch):
    monkeypatch.setenv("CRYPTO_AGENT_LANG", "ar")
