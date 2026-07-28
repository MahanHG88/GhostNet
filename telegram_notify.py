import os
import threading

import requests


def _load_env():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, ".env")
    if os.path.exists(path):
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


_load_env()

_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")


def _send(text):
    if not _BOT_TOKEN or not _CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage",
            json={"chat_id": _CHAT_ID, "text": str(text)[:3900]},
            timeout=10,
        )
    except Exception as e:
        print(f"[Telegram notify error] {e}")


def notify(text):
    """Fire-and-forget Telegram notification. Never blocks the caller or raises."""
    if not _BOT_TOKEN or not _CHAT_ID:
        return
    threading.Thread(target=_send, args=(text,), daemon=True).start()
