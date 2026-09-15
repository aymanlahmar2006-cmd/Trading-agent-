"""Outbound messages.

Telegram is the default because it is free, reaches a phone, and needs no paid
API -- which is the project's standing constraint. Credentials come from the
environment, never from a committed file, so the repo stays safe to make public.

Every channel falls back to a local file rather than raising: a failed alert
must never take down the analysis run that produced it, and a message that
could not be sent still needs to be recoverable.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OUTBOX = Path("journal/outbox.log")
TELEGRAM_API = "https://api.telegram.org"


@dataclass
class Delivery:
    """What actually happened to one message."""

    channel: str
    ok: bool
    detail: str = ""


def _append_outbox(text: str, path: Path = OUTBOX) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text.rstrip() + "\n" + "-" * 60 + "\n")


def telegram_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN")
                and os.environ.get("TELEGRAM_CHAT_ID"))


def send_telegram(text: str, timeout: float = 10.0) -> Delivery:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return Delivery("telegram", False,
                        "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")

    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()

    request = urllib.request.Request(
        f"{TELEGRAM_API}/bot{token}/sendMessage", data=payload)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode())
        if body.get("ok"):
            return Delivery("telegram", True)
        return Delivery("telegram", False, str(body.get("description", body)))
    except urllib.error.HTTPError as exc:
        # Telegram puts the useful reason in the body, not the status line.
        try:
            detail = json.loads(exc.read().decode()).get("description", str(exc))
        except Exception:
            detail = str(exc)
        return Delivery("telegram", False, f"HTTP {exc.code}: {detail}")
    except Exception as exc:
        return Delivery("telegram", False, f"{type(exc).__name__}: {exc}")


def notify(text: str, channel: str = "auto",
           outbox: Path = OUTBOX) -> Delivery:
    """Send ``text``. Always writes to the outbox, whatever the channel does."""
    _append_outbox(text, outbox)

    if channel == "file":
        return Delivery("file", True, str(outbox))

    if channel in ("auto", "telegram"):
        if telegram_configured():
            result = send_telegram(text)
            if result.ok:
                return result
            # Kept in the outbox above, so nothing is lost.
            return Delivery("telegram", False,
                            f"{result.detail} (message saved to {outbox})")
        if channel == "telegram":
            return Delivery("telegram", False,
                            f"not configured (message saved to {outbox})")
        return Delivery("file", True, f"telegram not configured; wrote {outbox}")

    return Delivery(channel, False, f"unknown channel '{channel}'")


def format_alerts(alerts: list[Any], header: str = "🔔 تنبيهات") -> str:
    """Render alerts as a plain-text Telegram message."""
    if not alerts:
        return ""
    lines = [header, ""]
    for alert in alerts:
        lines.append(f"{alert.icon} {alert.title}")
        lines.append(f"   {alert.detail}")
        lines.append("")
    lines.append("— إشارات فقط. لا تنفيذ تلقائي. —")
    return "\n".join(lines)
