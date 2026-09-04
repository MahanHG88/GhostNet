"""Checks everything Mr. Alvarez needs, and says what is missing.

    python doctor.py          # config, token, connection, queue
    python doctor.py --live   # also sends one real request to each AI provider
"""
import json
import os
import sys
import time
from datetime import datetime

import requests

import ai_providers
import contacts
import env
import schedule
import state

env.load()
OK, BAD, MEH = "  ok  ", " FAIL ", " ??   "


def line(mark, text):
    print("[{}] {}".format(mark, text))


def check_config():
    print("\n--- config ---")
    if not os.path.exists(os.path.join(env.BASE_DIR, ".env")):
        line(BAD, ".env is missing. Copy .env.example to .env and put the token in it.")
        return False
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    admin = os.environ.get("ADMIN_CHAT_ID", "").strip()
    line(OK if token else BAD, "TELEGRAM_BOT_TOKEN {}".format("set" if token else "MISSING - the bot exits without it"))
    line(OK if admin else BAD, "ADMIN_CHAT_ID {}".format(admin or "MISSING - nobody can run commands"))
    for name in ("persona.md", "schedule.json", "contacts.json"):
        path = os.path.join(env.BASE_DIR, name)
        line(OK if os.path.exists(path) else MEH, "{} {}".format(name, "found" if os.path.exists(path) else "missing (a default is used)"))
    line(OK, "recognised contacts: {}".format(", ".join(contacts.ids()) or "none"))
    status, source = schedule.current_status(state.load().get("override"))
    line(OK, 'he would currently say she is "{}" (from the {})'.format(status, source))
    return bool(token)


def check_token():
    print("\n--- telegram ---")
    try:
        response = requests.get(
            "https://api.telegram.org/bot{}/getMe".format(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()),
            timeout=20,
        )
        data = response.json()
    except Exception as exc:
        line(BAD, "cannot reach api.telegram.org: {}".format(exc))
        return
    if not data.get("ok"):
        line(BAD, "token rejected: {}".format(data.get("description")))
        return
    bot = data["result"]
    line(OK, "token works - @{}".format(bot.get("username")))
    if bot.get("can_connect_to_business"):
        line(OK, "the bot is allowed to connect to business accounts")
    else:
        line(BAD, "this bot cannot connect to business accounts - enable it in @BotFather "
                  "(Bot Settings > Business Mode)")


def check_connection():
    print("\n--- chat automation connection ---")
    connection = state.load().get("connection") or {}
    if not connection.get("id"):
        line(BAD, "no connection recorded yet. Until her phone connects the bot in "
                  "Settings > Account > Chat Automation, no messages reach it at all. "
                  "The connection is recorded the moment she connects it while the bot is running - "
                  "if she connected it before you started the bot, toggle it off and on again.")
        return
    line(OK, "connected to account {}".format(connection.get("owner_id")))
    line(OK if connection.get("is_enabled", True) else BAD,
         "connection is {}".format("enabled" if connection.get("is_enabled", True) else "DISABLED in her settings"))
    line(OK if connection.get("can_reply", True) else BAD,
         "reply permission: {}".format("granted" if connection.get("can_reply", True) else "NOT GRANTED - he can read but not answer"))


def check_queue():
    print("\n--- queue ---")
    data = state.load()
    if data.get("paused"):
        line(BAD, "PAUSED - /resume from the admin chat")
    chats = data.get("chats") or {}
    if not chats:
        line(MEH, "no chats seen yet. If someone has written to her since the bot started, "
                  "the message never arrived - check the connection above, and that her "
                  "Chat Automation settings do not exclude that chat.")
    for chat_id, record in chats.items():
        bits = []
        pending = record.get("pending")
        if pending:
            due_in = (pending["due_at"] - time.time()) / 60
            bits.append("reply due in {:.1f} min".format(due_in) if due_in > 0 else "reply overdue by {:.1f} min".format(-due_in))
        if record.get("muted"):
            bits.append("MUTED")
        bits.append("{} ai replies, {} warnings".format(record.get("ai_replies", 0), record.get("warnings", 0)))
        if record.get("last_reply_at"):
            bits.append("last reply {}".format(datetime.fromtimestamp(record["last_reply_at"]).strftime("%d %b %H:%M")))
        line(OK, "chat {}: {}".format(chat_id, ", ".join(bits)))
    waiting = [e for e in data.get("inbox", []) if not e.get("answered")]
    line(OK, "{} message(s) waiting for her".format(len(waiting)))


def check_providers(live):
    print("\n--- ai providers ---")
    configured = ai_providers.providers()
    if not configured:
        line(BAD, "providers.json has no usable providers. Without one he cannot compose a reply, "
                  "so nothing is sent and the admin chat is told instead.")
        return
    for provider in configured:
        name = provider.get("name") or provider["model"]
        key_var = provider.get("api_key_env", "")
        if key_var and not os.environ.get(key_var, "").strip():
            line(BAD, "{}: {} is not set in .env".format(name, key_var))
        else:
            line(OK, "{}: {} at {}".format(name, provider["model"], provider["base_url"]))
    if live:
        print()
        try:
            reply, used = ai_providers.generate(
                [{"role": "user", "content": "Reply with the single word: listo"}], max_tokens=10)
            line(OK, 'live call answered by {}: "{}"'.format(used, reply))
        except Exception as exc:
            line(BAD, "every provider failed: {}".format(exc))


if __name__ == "__main__":
    live = "--live" in sys.argv
    if check_config():
        check_token()
    check_connection()
    check_queue()
    check_providers(live)
    print("\nIf everything above is ok and he still says nothing, watch the bot's own output - "
          "it logs every message it sees and every reason it stays quiet.")
