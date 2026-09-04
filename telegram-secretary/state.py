import json
import os
import tempfile
import time
from datetime import date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "state.json")

MAX_HISTORY = 20
MAX_INBOX = 200

_state = None


def _blank():
    return {"connection": {}, "paused": False, "override": None, "chats": {}, "inbox": []}


def load():
    global _state
    if _state is None:
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                _state = json.load(f)
        except (OSError, ValueError):
            _state = {}
        for key, value in _blank().items():
            _state.setdefault(key, value)
    return _state


def save():
    if _state is None:
        return
    fd, tmp_path = tempfile.mkstemp(dir=BASE_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(_state, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, STATE_FILE)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def chat(chat_id):
    chats = load()["chats"]
    key = str(chat_id)
    if key not in chats:
        chats[key] = {"history": [], "pending": None, "last_reply_at": 0, "replies": {"date": "", "count": 0}}
    return chats[key]


def add_history(chat_id, role, text):
    history = chat(chat_id)["history"]
    history.append({"role": role, "text": text, "ts": time.time()})
    del history[:-MAX_HISTORY]


def add_inbox(entry):
    inbox = load()["inbox"]
    inbox.append(entry)
    del inbox[:-MAX_INBOX]


def replies_today(record):
    replies = record.get("replies", {})
    return replies.get("count", 0) if replies.get("date") == date.today().isoformat() else 0


def bump_reply(record):
    today = date.today().isoformat()
    replies = record.setdefault("replies", {"date": "", "count": 0})
    if replies.get("date") != today:
        replies["date"] = today
        replies["count"] = 0
    replies["count"] += 1
    record["last_reply_at"] = time.time()
