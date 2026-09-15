"""Print the Telegram chat IDs your bot can reach.

    python scripts/find_chat_id.py

Reads TELEGRAM_BOT_TOKEN from the environment, asks Telegram who has messaged
the bot, and prints each chat id with the name attached -- so the id is copied
from a labelled list rather than hunted out of raw JSON.

The token is never printed, and nothing is written to disk.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.telegram.org"


def fetch_updates(token: str, timeout: float = 15.0) -> dict:
    request = urllib.request.Request(f"{API}/bot{token}/getUpdates")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def chats_from(payload: dict) -> list[tuple[str, str]]:
    """Every distinct (id, label) the bot has seen, newest first."""
    seen: dict[str, str] = {}
    for update in payload.get("result", []):
        for key in ("message", "edited_message", "channel_post", "my_chat_member"):
            chat = (update.get(key) or {}).get("chat")
            if not chat or "id" not in chat:
                continue
            name = " ".join(filter(None, [
                chat.get("title"),
                chat.get("first_name"),
                chat.get("last_name"),
            ])) or chat.get("username") or chat.get("type", "")
            seen[str(chat["id"])] = name
    return list(reversed(list(seen.items())))


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set in this terminal.")
        print("On Windows, setx only affects terminals opened afterwards -- "
              "close this one and open a new one.")
        return 1

    try:
        payload = fetch_updates(token)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode()).get("description", "")
        except Exception:
            detail = ""
        print(f"Telegram refused the request: HTTP {exc.code} {detail}")
        if exc.code == 401:
            print("That means the token is wrong. Copy it again from @BotFather.")
        return 1
    except Exception as exc:
        print(f"Could not reach Telegram: {type(exc).__name__}: {exc}")
        return 1

    if not payload.get("ok"):
        print(f"Telegram returned an error: {payload.get('description', payload)}")
        return 1

    chats = chats_from(payload)
    if not chats:
        print("The bot has not received a message yet, so Telegram has no chat "
              "to report.")
        print("Open your bot in Telegram, press Start (or send it any message), "
              "then run this again.")
        return 1

    print("Chats your bot can reach:\n")
    for chat_id, name in chats:
        print(f"  {chat_id}   {name}")
    print(f'\nSet the one that is you:\n\n  setx TELEGRAM_CHAT_ID "{chats[0][0]}"')
    print("\nThen close this terminal and open a new one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
