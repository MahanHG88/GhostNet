import json
import os
import re
import time
from datetime import datetime

import requests

import ai_providers
import env
import persona
import schedule
import state

env.load()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "").strip()
REPLY_DELAY_MINUTES = env.get_int("REPLY_DELAY_MINUTES", 5)
REPLY_COOLDOWN_MINUTES = env.get_int("REPLY_COOLDOWN_MINUTES", 30)
MAX_REPLIES_PER_CHAT_PER_DAY = env.get_int("MAX_REPLIES_PER_CHAT_PER_DAY", 5)

API_BASE = "https://api.telegram.org/bot{}".format(BOT_TOKEN)
ALLOWED_UPDATES = ["message", "business_connection", "business_message"]
STALE_AFTER_MINUTES = 60

DURATION_RE = re.compile(r"\s+for\s+(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)\s*$", re.I)
UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400}

HELP_TEXT = """Mr. Alvarez - Ms. Garcia's message desk

/update <status> - set her current status, e.g.
    /update in a meeting until 4pm
    /update travelling for 2d
/clear - drop the manual status, go back to the schedule
/status - what he would tell someone right now
/messages - recent messages left for her
/pause - stop replying to anyone
/resume - start again
/help - this list"""


def log(message):
    print("[{}] {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message), flush=True)


def api(method, payload):
    response = requests.post("{}/{}".format(API_BASE, method), json=payload, timeout=30)
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description") or "telegram error {}".format(response.status_code))
    return data.get("result")


def send(chat_id, text, connection_id=None):
    payload = {"chat_id": chat_id, "text": str(text)[:3900]}
    if connection_id:
        payload["business_connection_id"] = connection_id
    return api("sendMessage", payload)


def notify_admin(text):
    if not ADMIN_CHAT_ID:
        return
    try:
        send(ADMIN_CHAT_ID, text)
    except Exception as exc:
        log("could not reach admin chat: {}".format(exc))


def display_name(user):
    name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")])).strip()
    if name:
        return name
    if user.get("username"):
        return "@" + user["username"]
    return str(user.get("id", "unknown"))


# ------------------------------------------------------------------ updates ---

def handle_connection(connection):
    rights = connection.get("rights") or {}
    record = state.load()["connection"]
    record.update({
        "id": connection.get("id"),
        "owner_id": (connection.get("user") or {}).get("id"),
        "is_enabled": connection.get("is_enabled", True),
        "can_reply": connection.get("can_reply", rights.get("can_reply", True)),
    })
    state.save()
    if record["is_enabled"]:
        log("connected to account {}, can_reply={}".format(record["owner_id"], record["can_reply"]))
        notify_admin("Mr. Alvarez is connected to Ms. Garcia's account.")
    else:
        log("connection disabled by the account owner")
        notify_admin("Mr. Alvarez was disconnected from Ms. Garcia's account.")


def handle_business_message(message):
    if message.get("sender_business_bot"):
        return

    chat_id = message.get("chat", {}).get("id")
    sender = message.get("from") or {}
    text = (message.get("text") or message.get("caption") or "").strip()
    connection = state.load()["connection"]
    record = state.chat(chat_id)

    if sender.get("id") and sender.get("id") == connection.get("owner_id"):
        if record.get("pending"):
            log("chat {}: Ms. Garcia replied herself, standing down".format(chat_id))
        record["pending"] = None
        state.add_history(chat_id, "her", text)
        state.save()
        return

    if sender.get("is_bot"):
        return

    name = display_name(sender)
    state.add_history(chat_id, "them", text or "(sent a non-text message)")
    state.add_inbox({"chat_id": chat_id, "name": name, "text": text or "(non-text message)", "ts": time.time()})

    sent_at = message.get("date", 0)
    if sent_at and time.time() - sent_at > STALE_AFTER_MINUTES * 60:
        log("chat {}: message from {} is stale, not queuing a reply".format(chat_id, name))
        state.save()
        return

    if record.get("pending"):
        record["pending"]["connection_id"] = message.get("business_connection_id")
    else:
        record["pending"] = {
            "due_at": time.time() + REPLY_DELAY_MINUTES * 60,
            "connection_id": message.get("business_connection_id"),
            "name": name,
        }
        log("chat {}: {} wrote in, replying in {} min unless she answers".format(chat_id, name, REPLY_DELAY_MINUTES))
    state.save()


def _blocked_reason(record):
    connection = state.load()["connection"]
    if not connection.get("is_enabled", True):
        return "the bot is disconnected from her account"
    if not connection.get("can_reply", True):
        return "the bot does not have permission to reply"
    if time.time() - record.get("last_reply_at", 0) < REPLY_COOLDOWN_MINUTES * 60:
        return "already replied in this chat within the last {} min".format(REPLY_COOLDOWN_MINUTES)
    if state.replies_today(record) >= MAX_REPLIES_PER_CHAT_PER_DAY:
        return "daily reply cap reached for this chat"
    return None


def _last_incoming(record):
    for entry in reversed(record.get("history", [])):
        if entry.get("role") == "them":
            return entry.get("text", "")
    return ""


def answer(chat_id, record, pending):
    status, source = schedule.current_status(state.load().get("override"))
    messages = persona.build_messages(
        history=record.get("history", []),
        status=status,
        schedule_hint=schedule.availability_hint(),
        sender_name=pending.get("name"),
    )

    try:
        reply, provider = ai_providers.generate(messages)
    except ai_providers.AllProvidersFailed as exc:
        log("chat {}: no reply sent, every provider failed".format(chat_id))
        notify_admin(
            "Could not answer {} - every AI provider failed, so nothing was sent.\n\nThey wrote:\n{}\n\n({})".format(
                pending.get("name"), _last_incoming(record), exc
            )
        )
        return

    send(chat_id, reply, connection_id=pending.get("connection_id"))
    state.add_history(chat_id, "alvarez", reply)
    state.bump_reply(record)
    log("chat {}: replied to {} via {}".format(chat_id, pending.get("name"), provider))
    notify_admin(
        "{} wrote to Ms. Garcia:\n{}\n\nMr. Alvarez answered:\n{}\n\nStatus used: {} ({}) - via {}".format(
            pending.get("name"), _last_incoming(record) or "(no text)", reply, status, source, provider
        )
    )


def process_pending():
    data = state.load()
    now = time.time()
    changed = False

    for chat_id, record in list(data["chats"].items()):
        pending = record.get("pending")
        if not pending or pending.get("due_at", 0) > now:
            continue
        record["pending"] = None
        changed = True

        if data.get("paused"):
            log("chat {}: paused, not replying".format(chat_id))
            continue
        blocked = _blocked_reason(record)
        if blocked:
            log("chat {}: not replying - {}".format(chat_id, blocked))
            continue
        try:
            answer(chat_id, record, pending)
        except Exception as exc:
            log("chat {}: failed to reply - {}".format(chat_id, exc))
            notify_admin("Failed to reply to {}: {}".format(pending.get("name"), exc))

    if changed:
        state.save()


# ----------------------------------------------------------- admin commands ---

def parse_status(argument):
    match = DURATION_RE.search(argument)
    if not match:
        return argument.strip(), None
    seconds = int(match.group(1)) * UNIT_SECONDS[match.group(2)[0].lower()]
    return argument[:match.start()].strip(), time.time() + seconds


def status_report():
    data = state.load()
    override = data.get("override")
    status, source = schedule.current_status(override)
    lines = [
        "Right now he would say: she is {}".format(status),
        "Source: {}".format(source),
    ]
    if schedule.override_active(override) and override.get("expires_at"):
        lines.append("Manual status expires: {}".format(
            datetime.fromtimestamp(override["expires_at"]).strftime("%a %H:%M")
        ))
    connection = data.get("connection") or {}
    lines.append("Account connection: {}".format(
        "active" if connection.get("id") and connection.get("is_enabled", True) else "not connected yet"
    ))
    lines.append("Replying: {}".format("paused" if data.get("paused") else "on"))
    lines.append("Waiting to reply in {} chat(s)".format(
        sum(1 for c in data["chats"].values() if c.get("pending"))
    ))
    lines.append("Replies sent today: {}".format(
        sum(state.replies_today(c) for c in data["chats"].values())
    ))
    return "\n".join(lines)


def recent_messages(limit=10):
    inbox = state.load().get("inbox", [])
    if not inbox:
        return "No messages yet."
    lines = []
    for entry in inbox[-limit:]:
        stamp = datetime.fromtimestamp(entry.get("ts", 0)).strftime("%d %b %H:%M")
        lines.append("{} - {}:\n{}".format(stamp, entry.get("name"), entry.get("text")))
    return "Recent messages for Ms. Garcia:\n\n" + "\n\n".join(lines)


def handle_admin_message(message):
    chat_id = message.get("chat", {}).get("id")
    if not ADMIN_CHAT_ID or str(chat_id) != ADMIN_CHAT_ID:
        return

    text = (message.get("text") or "").strip()
    command, _, argument = text.partition(" ")
    command = command.lower().split("@")[0]
    data = state.load()

    if command in ("/start", "/help"):
        send(chat_id, HELP_TEXT)
    elif command == "/update":
        status, expires_at = parse_status(argument)
        if not status:
            send(chat_id, "Give me a status, e.g. /update in a meeting until 4pm")
            return
        data["override"] = {"status": status, "expires_at": expires_at, "set_at": time.time()}
        state.save()
        until = " until {}".format(datetime.fromtimestamp(expires_at).strftime("%a %H:%M")) if expires_at else ""
        send(chat_id, "Noted{}. He will tell people she is {}.".format(until, status))
    elif command == "/clear":
        data["override"] = None
        state.save()
        status, source = schedule.current_status(None)
        send(chat_id, "Manual status cleared. Back to the {}: she is {}.".format(source, status))
    elif command == "/status":
        send(chat_id, status_report())
    elif command == "/messages":
        send(chat_id, recent_messages())
    elif command == "/pause":
        data["paused"] = True
        state.save()
        send(chat_id, "Paused. Mr. Alvarez will not answer anyone until /resume.")
    elif command == "/resume":
        data["paused"] = False
        state.save()
        send(chat_id, "Back on. He will answer again after the {} min delay.".format(REPLY_DELAY_MINUTES))
    else:
        send(chat_id, "Not a command I know. Send /help for the list.")


def dispatch(update):
    if "business_connection" in update:
        handle_connection(update["business_connection"])
    elif "business_message" in update:
        handle_business_message(update["business_message"])
    elif "message" in update:
        handle_admin_message(update["message"])


# --------------------------------------------------------------------- run ---

def main():
    if not BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is missing - copy .env.example to .env and fill it in")
    if not ADMIN_CHAT_ID:
        log("warning: ADMIN_CHAT_ID is not set, nobody can run commands or see the audit trail")

    me = api("getMe", {})
    log("Mr. Alvarez online as @{}".format(me.get("username")))
    if not ai_providers.providers():
        log("warning: providers.json has no usable providers, replies will fail until it is filled in")
    notify_admin("Mr. Alvarez is online.\n\n" + HELP_TEXT)

    data = state.load()
    offset = data.get("offset")
    while True:
        try:
            response = requests.get(
                "{}/getUpdates".format(API_BASE),
                params={"timeout": 30, "offset": offset, "allowed_updates": json.dumps(ALLOWED_UPDATES)},
                timeout=40,
            )
            response.raise_for_status()
            for update in response.json().get("result", []):
                offset = update["update_id"] + 1
                data["offset"] = offset
                try:
                    dispatch(update)
                except Exception as exc:
                    log("failed to handle update {}: {}".format(update.get("update_id"), exc))
            state.save()
        except Exception as exc:
            log("polling error: {}".format(exc))
            time.sleep(5)

        try:
            process_pending()
        except Exception as exc:
            log("pending queue error: {}".format(exc))


if __name__ == "__main__":
    main()
