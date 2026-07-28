import os
import time
import json
import requests
from datetime import datetime


def load_env_file(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_env_file(os.path.join(BASE_DIR, ".env"))

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = "openai/gpt-oss-20b:free"

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

ENRICHED_FILE = os.path.join(BASE_DIR, "enriched_attacks.json")
ALARM_LOG = os.path.join(BASE_DIR, "alarm_logs.json")
ALARM_STATE = os.path.join(BASE_DIR, "alarm_state.json")
BANNED_FILE = os.path.join(BASE_DIR, "banned_ips.txt")
API_USERS_FILE = os.path.join(BASE_DIR, "api_users.json")
FINGERPRINT_DB = os.path.join(BASE_DIR, "banned_fingerprints.json")
ACTIVITY_LOG = os.path.join(BASE_DIR, "activity_logs.json")
CONTACT_MESSAGES_FILE = os.path.join(BASE_DIR, "contact_messages.json")
AUTH_STATE_FILE = os.path.join(BASE_DIR, "telegram_auth.json")
API_LOG_FILE = os.path.join(BASE_DIR, "api.log")
HONEYPOT_LOG_FILE = os.path.join(BASE_DIR, "honeypot.log")
DEFENSE_LOG_FILE = os.path.join(BASE_DIR, "defense.log")
ENRICH_LOG_FILE = os.path.join(BASE_DIR, "enrich.log")

GHOST_PERSONA = (
    "You are \"Ghost\", the resident AI security analyst at GhostNet, now chatting over Telegram "
    "directly with the platform's admin. You're sharp about security, a little dry wit, never a lecture. "
    "Keep replies short and conversational, like a Slack message from a coworker. Reply in the same "
    "language the admin writes in."
)

HELP_TEXT = (
    "GhostNet Admin Bot\n\n"
    "Send /start or /menu any time for the button menu — everything below also works as a typed command.\n\n"
    "/status - live threat intel snapshot\n"
    "/banned - banned IPs & fingerprints\n"
    "/alarm - show alarm state\n"
    "/arm /disarm - change alarm state\n"
    "/alarmlogs - recent alarm events\n"
    "/devs - list developer accounts\n"
    "/devkey <email> - show one dev's API key\n"
    "/messages - recent contact messages\n"
    "/logs <api|honeypot|defense|enrich> - tail a log file\n"
    "/sync - trigger honeypot rule sync\n"
    "/ask <question> - ask Ghost AI (or just send any plain message, no command needed)\n"
    "/logout - lock this chat again"
)

# chat_id -> pending state ("awaiting_password"). In-memory only, resets on restart.
PENDING = {}
# last-rendered developer email list, so tapped "dev:<idx>" buttons can resolve back to an email.
_DEVS_CACHE = []


# ---------------------------------------------------------------- storage ---

def read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def tail_lines(path, n=20):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return "".join(lines[-n:]).strip()
    except Exception:
        return None


def log_activity(actor, action):
    logs = read_json(ACTIVITY_LOG, [])
    logs.append({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "actor": actor, "action": action})
    write_json(ACTIVITY_LOG, logs)


def log_alarm(user, action):
    logs = read_json(ALARM_LOG, [])
    logs.append({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "user": user, "action": action})
    write_json(ALARM_LOG, logs)


def is_authorized(chat_id):
    state = read_json(AUTH_STATE_FILE, {"authorized_chats": []})
    return str(chat_id) in state.get("authorized_chats", [])


def set_authorized(chat_id, value):
    state = read_json(AUTH_STATE_FILE, {"authorized_chats": []})
    chats = set(state.get("authorized_chats", []))
    if value:
        chats.add(str(chat_id))
    else:
        chats.discard(str(chat_id))
    write_json(AUTH_STATE_FILE, {"authorized_chats": list(chats)})


# ------------------------------------------------------------- Telegram IO ---

def send_message(chat_id, text, reply_markup=None):
    if not text:
        text = "(empty)"
    payload = {"chat_id": chat_id, "text": str(text)[:3900]}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        print(f"[Telegram send error] {e}")


def edit_message(chat_id, message_id, text, reply_markup=None):
    if not text:
        text = "(empty)"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": str(text)[:3900]}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(f"{API_BASE}/editMessageText", json=payload, timeout=10)
        if not r.json().get("ok"):
            send_message(chat_id, text, reply_markup)
    except Exception as e:
        print(f"[Telegram edit error] {e}")
        send_message(chat_id, text, reply_markup)


def answer_callback(callback_query_id, text=None):
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    try:
        requests.post(f"{API_BASE}/answerCallbackQuery", json=payload, timeout=10)
    except Exception as e:
        print(f"[Telegram answer_callback error] {e}")


def delete_message(chat_id, message_id):
    try:
        requests.post(f"{API_BASE}/deleteMessage", json={"chat_id": chat_id, "message_id": message_id}, timeout=10)
    except Exception as e:
        print(f"[Telegram delete error] {e}")


# ------------------------------------------------------------- keyboards ---

def _btn(text, data):
    return {"text": text, "callback_data": data}


def _kb(rows):
    return {"inline_keyboard": rows}


def unlock_kb():
    return _kb([[_btn("🔑 Unlock", "act:unlock")]])


def main_menu_kb():
    return _kb([
        [_btn("📊 Status", "menu:status"), _btn("🚫 Banned", "menu:banned")],
        [_btn("🚨 Alarm", "menu:alarm"), _btn("📜 Alarm Log", "menu:alarmlogs")],
        [_btn("👥 Devs", "menu:devs"), _btn("✉️ Messages", "menu:messages")],
        [_btn("📄 Logs", "menu:logs"), _btn("🔄 Sync", "act:sync")],
        [_btn("🤖 Ask Ghost", "menu:ask")],
        [_btn("🔒 Logout", "act:logout")],
    ])


def alarm_kb():
    return _kb([
        [_btn("Arm", "act:arm"), _btn("Disarm", "act:disarm")],
        [_btn("◀ Back", "menu:main")],
    ])


def logs_kb():
    return _kb([
        [_btn("api", "log:api"), _btn("honeypot", "log:honeypot")],
        [_btn("defense", "log:defense"), _btn("enrich", "log:enrich")],
        [_btn("◀ Back", "menu:logs")],
    ])


def back_kb(target="menu:main"):
    return _kb([[_btn("◀ Back", target)]])


def devs_kb(emails):
    rows = [[_btn(email, f"dev:{i}")] for i, email in enumerate(emails)]
    rows.append([_btn("◀ Back", "menu:main")])
    return _kb(rows)


# ------------------------------------------------------------ data views ---

def build_snapshot():
    lines = []
    data = read_json(ENRICHED_FILE, [])
    lines.append(f"Total captured incursions: {len(data)}")
    if data:
        ips = {d.get("attacker_ip") for d in data if d.get("attacker_ip")}
        lines.append(f"Unique hostile IPs: {len(ips)}")

        sev_counts, cat_counts, country_counts = {}, {}, {}
        for d in data:
            sev_counts[d.get("severity", "Unknown")] = sev_counts.get(d.get("severity", "Unknown"), 0) + 1
            cat_counts[d.get("attack_category", "Unknown")] = cat_counts.get(d.get("attack_category", "Unknown"), 0) + 1
            country_counts[d.get("country", "Unknown")] = country_counts.get(d.get("country", "Unknown"), 0) + 1

        lines.append(f"Severity breakdown: {sev_counts}")
        lines.append(f"Top categories: {sorted(cat_counts.items(), key=lambda x: -x[1])[:5]}")
        lines.append(f"Top countries: {sorted(country_counts.items(), key=lambda x: -x[1])[:5]}")

        recent = sorted(data, key=lambda d: d.get("timestamp", ""), reverse=True)[:5]
        lines.append("Most recent incidents:")
        for r in recent:
            lines.append(f"  {r.get('timestamp')} | {r.get('attacker_ip')} | {r.get('country')} | {r.get('attack_category')} | {r.get('severity')}")

    banned_ips = []
    if os.path.exists(BANNED_FILE):
        with open(BANNED_FILE, "r", encoding="utf-8") as f:
            banned_ips = list(set(f.read().splitlines()))
    lines.append(f"Neutralized IPs: {len(banned_ips)}")

    fps = read_json(FINGERPRINT_DB, [])
    lines.append(f"Banned fingerprints: {len(fps)}")

    state = read_json(ALARM_STATE, {})
    lines.append(f"Alarm status: {state.get('status', 'UNKNOWN')}")

    return "\n".join(lines)


def ask_ghost(question):
    if not OPENROUTER_API_KEY:
        return "OPENROUTER_API_KEY isn't set in .env - my brain's offline."
    system_prompt = GHOST_PERSONA + "\n\nLIVE SECURITY SNAPSHOT (real, current data):\n" + build_snapshot()
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            json={
                "model": OPENROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"That request bounced off the API: {e}"


def render_main_menu():
    return "GhostNet Admin — tap a button or type a command (/help for the list).", main_menu_kb()


def render_status():
    return build_snapshot(), back_kb()


def render_banned():
    banned_ips = []
    if os.path.exists(BANNED_FILE):
        with open(BANNED_FILE, "r", encoding="utf-8") as f:
            banned_ips = list(set(f.read().splitlines()))
    fps = read_json(FINGERPRINT_DB, [])
    msg = f"Banned IPs ({len(banned_ips)}):\n" + "\n".join(banned_ips[:30] or ["(none)"])
    msg += f"\n\nBanned fingerprints ({len(fps)}):\n" + "\n".join(fps[:20] or ["(none)"])
    return msg, back_kb()


def render_alarm():
    state = read_json(ALARM_STATE, {})
    return f"Alarm status: {state.get('status', 'UNKNOWN')}", alarm_kb()


def set_alarm(new_status):
    write_json(ALARM_STATE, {"status": new_status})
    log_alarm("telegram-admin", f"System {new_status}")


def render_alarmlogs():
    logs = read_json(ALARM_LOG, [])
    recent = logs[-10:]
    msg = "\n".join(f"{l['timestamp']} | {l['user']} | {l['action']}" for l in recent) or "No alarm events yet."
    return msg, back_kb()


def render_devs():
    global _DEVS_CACHE
    users = read_json(API_USERS_FILE, {})
    _DEVS_CACHE = list(users.keys())
    if not _DEVS_CACHE:
        return "No developer accounts yet.", back_kb()
    lines = [f"{email} | quota {m.get('quota')} | used {m.get('requests_used')} | since {m.get('created_at')}" for email, m in users.items()]
    return "\n".join(lines), devs_kb(_DEVS_CACHE)


def render_dev_detail(email):
    users = read_json(API_USERS_FILE, {})
    m = users.get(email)
    if not m:
        return "No account with that email.", back_kb("menu:devs")
    text = f"{email}\nQuota: {m.get('quota')}\nUsed: {m.get('requests_used')}\nSince: {m.get('created_at')}\nKey: {m.get('api_key')}"
    return text, back_kb("menu:devs")


def render_messages():
    msgs = read_json(CONTACT_MESSAGES_FILE, [])
    recent = msgs[-10:]
    msg = "\n\n".join(f"{m['timestamp']} | {m['name']} <{m['email']}>\n{m['message']}" for m in recent) or "No messages yet."
    return msg, back_kb()


def render_logs_menu():
    return "Pick a log:", logs_kb()


def render_log(which):
    log_map = {"api": API_LOG_FILE, "honeypot": HONEYPOT_LOG_FILE, "defense": DEFENSE_LOG_FILE, "enrich": ENRICH_LOG_FILE}
    target = log_map.get(which)
    if not target:
        return "Unknown log.", logs_kb()
    return tail_lines(target, 20) or "Log is empty.", back_kb("menu:logs")


def do_sync():
    try:
        res = requests.post("http://127.0.0.1:8000/api/admin/sync-honeypot", timeout=5)
        text = "Synced." if res.status_code == 200 else f"Sync failed ({res.status_code})."
    except Exception as e:
        text = f"Sync error: {e}"
    return text, back_kb()


def render_ask_hint():
    return "Type your question and send it as a normal message — I'll answer right here. (/ask also works.)", back_kb()


# ------------------------------------------------------------- dispatch ---

def handle_command(chat_id, text, message_id=None):
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().split("@")[0]
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/login":
        ok = bool(arg) and bool(ADMIN_PASSWORD) and arg == ADMIN_PASSWORD
        if message_id:
            delete_message(chat_id, message_id)  # don't leave the password sitting in chat history
        if ok:
            set_authorized(chat_id, True)
            log_activity("telegram", "Logged in via Telegram bot")
            t, kb_ = render_main_menu()
            send_message(chat_id, "Unlocked.\n\n" + t, kb_)
        else:
            send_message(chat_id, "Wrong password.", unlock_kb())
        return

    if cmd in ("/start", "/menu", "/help"):
        if is_authorized(chat_id):
            if cmd == "/help":
                send_message(chat_id, HELP_TEXT, main_menu_kb())
            else:
                t, kb_ = render_main_menu()
                send_message(chat_id, t, kb_)
        else:
            send_message(chat_id, "GhostNet Admin Bot. Tap Unlock or send /login <password>.", unlock_kb())
        return

    if not is_authorized(chat_id):
        send_message(chat_id, "Locked. Tap Unlock or send /login <password>.", unlock_kb())
        return

    if cmd == "/logout":
        set_authorized(chat_id, False)
        log_activity("telegram", "Logged out of Telegram bot")
        send_message(chat_id, "Locked.", unlock_kb())
    elif cmd == "/status":
        t, kb_ = render_status(); send_message(chat_id, t, kb_)
    elif cmd == "/banned":
        t, kb_ = render_banned(); send_message(chat_id, t, kb_)
    elif cmd == "/alarm":
        t, kb_ = render_alarm(); send_message(chat_id, t, kb_)
    elif cmd in ("/arm", "/disarm"):
        set_alarm("ARMED" if cmd == "/arm" else "DISARMED")
        t, kb_ = render_alarm(); send_message(chat_id, t, kb_)
    elif cmd == "/alarmlogs":
        t, kb_ = render_alarmlogs(); send_message(chat_id, t, kb_)
    elif cmd == "/devs":
        t, kb_ = render_devs(); send_message(chat_id, t, kb_)
    elif cmd == "/devkey":
        if not arg:
            send_message(chat_id, "Usage: /devkey <email>", back_kb())
        else:
            t, kb_ = render_dev_detail(arg); send_message(chat_id, t, kb_)
    elif cmd == "/messages":
        t, kb_ = render_messages(); send_message(chat_id, t, kb_)
    elif cmd == "/logs":
        if not arg:
            t, kb_ = render_logs_menu()
        else:
            t, kb_ = render_log(arg.lower())
        send_message(chat_id, t, kb_)
    elif cmd == "/sync":
        t, kb_ = do_sync(); send_message(chat_id, t, kb_)
    elif cmd == "/ask":
        if not arg:
            send_message(chat_id, "Usage: /ask <question> — or just send me a plain message any time.", back_kb())
        else:
            send_message(chat_id, ask_ghost(arg), back_kb())
    else:
        t, kb_ = render_main_menu()
        send_message(chat_id, "Unknown command.\n\n" + t, kb_)


def handle_callback(callback_query):
    cq_id = callback_query["id"]
    data = callback_query.get("data", "")
    message = callback_query.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    message_id = message.get("message_id")

    print(f"[Telegram] callback chat={chat_id} data={data}", flush=True)
    answer_callback(cq_id)

    if chat_id is None:
        return

    if str(chat_id) != ADMIN_CHAT_ID:
        send_message(chat_id, "Unauthorized.")
        send_message(ADMIN_CHAT_ID, f"Unknown chat {chat_id} tapped a button on the GhostNet bot.")
        return

    if data == "act:unlock":
        PENDING[chat_id] = "awaiting_password"
        edit_message(chat_id, message_id, "Send the admin password now, as a normal message.")
        return

    if not is_authorized(chat_id):
        edit_message(chat_id, message_id, "Locked. Tap Unlock or send /login <password>.", unlock_kb())
        return

    if data == "menu:main":
        t, kb_ = render_main_menu()
    elif data == "menu:status":
        t, kb_ = render_status()
    elif data == "menu:banned":
        t, kb_ = render_banned()
    elif data == "menu:alarm":
        t, kb_ = render_alarm()
    elif data in ("act:arm", "act:disarm"):
        set_alarm("ARMED" if data == "act:arm" else "DISARMED")
        t, kb_ = render_alarm()
    elif data == "menu:alarmlogs":
        t, kb_ = render_alarmlogs()
    elif data == "menu:devs":
        t, kb_ = render_devs()
    elif data.startswith("dev:"):
        try:
            idx = int(data.split(":", 1)[1])
            email = _DEVS_CACHE[idx]
        except (ValueError, IndexError):
            t, kb_ = "That list is stale — reopen Devs.", back_kb("menu:devs")
        else:
            t, kb_ = render_dev_detail(email)
    elif data == "menu:messages":
        t, kb_ = render_messages()
    elif data == "menu:logs":
        t, kb_ = render_logs_menu()
    elif data.startswith("log:"):
        t, kb_ = render_log(data.split(":", 1)[1])
    elif data == "act:sync":
        t, kb_ = do_sync()
    elif data == "menu:ask":
        t, kb_ = render_ask_hint()
    elif data == "act:logout":
        set_authorized(chat_id, False)
        log_activity("telegram", "Logged out of Telegram bot")
        t, kb_ = "Locked.", unlock_kb()
    else:
        t, kb_ = render_main_menu()

    edit_message(chat_id, message_id, t, kb_)


def handle_message(message):
    chat_id = message["chat"]["id"]
    message_id = message["message_id"]
    text = (message.get("text") or "").strip()

    print(f"[Telegram] message chat={chat_id} text={text!r}", flush=True)

    if str(chat_id) != ADMIN_CHAT_ID:
        send_message(chat_id, "Unauthorized.")
        send_message(ADMIN_CHAT_ID, f"Unknown chat {chat_id} tried to use the GhostNet bot:\n{text}")
        return

    if text.startswith("/"):
        handle_command(chat_id, text, message_id)
        return

    if PENDING.get(chat_id) == "awaiting_password":
        PENDING.pop(chat_id, None)
        delete_message(chat_id, message_id)  # don't leave the password sitting in chat history
        if text and ADMIN_PASSWORD and text == ADMIN_PASSWORD:
            set_authorized(chat_id, True)
            log_activity("telegram", "Logged in via Telegram bot")
            t, kb_ = render_main_menu()
            send_message(chat_id, "Unlocked.\n\n" + t, kb_)
        else:
            send_message(chat_id, "Wrong password.", unlock_kb())
        return

    if not is_authorized(chat_id):
        send_message(chat_id, "Locked. Tap Unlock or send /login <password>.", unlock_kb())
        return

    # Authorized, plain text, nothing pending: talk to Ghost directly (same as the website's chat box).
    send_message(chat_id, ask_ghost(text), back_kb())


def poll_loop():
    print("[*] GhostNet Telegram Bot Online.", flush=True)
    offset = None
    while True:
        try:
            resp = requests.get(f"{API_BASE}/getUpdates", params={"timeout": 30, "offset": offset}, timeout=40)
            resp.raise_for_status()
            updates = resp.json().get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                if "callback_query" in update:
                    handle_callback(update["callback_query"])
                    continue
                message = update.get("message") or update.get("edited_message")
                if not message or "text" not in message:
                    continue
                handle_message(message)
        except Exception as e:
            print(f"[Telegram poll error] {e}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_ADMIN_CHAT_ID not set in .env")
    poll_loop()
