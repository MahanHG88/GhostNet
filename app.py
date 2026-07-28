import streamlit as st
import pandas as pd
import json
import os
import time
import secrets
import random
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import plotly.express as px

from telegram_notify import notify

def load_env_file(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


load_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

SENDER_EMAIL = os.environ.get("GMAIL_SENDER_EMAIL", "")
SENDER_PASSWORD = os.environ.get("GMAIL_SENDER_APP_PASSWORD", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
CIVILIAN_PASSWORD = os.environ.get("CIVILIAN_PASSWORD", "")


def send_code_email(to_email, code, purpose="verification"):
    if purpose == "reset":
        subject = "GhostNet Portal - Password Reset Code"
        heading = "Password Reset Requested"
        intro = "Use the code below to reset your GhostNet Developer Portal password."
        footnote = "If you did not request this, you can safely ignore this email."
        expiry_note = "This code expires in 10 minutes."
    else:
        subject = "GhostNet Portal - Verification Code"
        heading = "Verify Your Email"
        intro = "Use the code below to finish creating your GhostNet Developer Portal account."
        footnote = "Do not share this code with anyone."
        expiry_note = "Enter this code in the portal to complete registration."

    text_body = f"{heading}\n\n{intro}\n\nYour code: {code}\n\n{expiry_note}\n{footnote}"

    html_body = f"""\
<html>
  <body style="margin:0;padding:0;background-color:#0b0f14;font-family:'Segoe UI',Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#0b0f14;padding:40px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="background-color:#111826;border:1px solid #1f2937;border-radius:16px;overflow:hidden;">
            <tr>
              <td style="padding:32px 40px 8px 40px;text-align:center;">
                <div style="font-size:26px;font-weight:800;letter-spacing:4px;color:#00FFD1;">GHOSTNET</div>
                <div style="font-size:13px;color:#94a3b8;margin-top:4px;">Autonomous Threat Intelligence &amp; Active Defense Platform</div>
              </td>
            </tr>
            <tr>
              <td style="padding:0 40px;">
                <hr style="border:0;height:1px;background-image:linear-gradient(to right, rgba(0,255,209,0), rgba(0,255,209,0.5), rgba(0,255,209,0));margin:24px 0;">
              </td>
            </tr>
            <tr>
              <td style="padding:0 40px;text-align:center;">
                <div style="font-size:18px;font-weight:700;color:#e2e8f0;margin-bottom:8px;">{heading}</div>
                <div style="font-size:14px;color:#94a3b8;line-height:1.5;margin-bottom:28px;">{intro}</div>
                <div style="display:inline-block;background-color:#0b0f14;border:1px solid #00FFD1;border-radius:12px;padding:16px 32px;font-size:32px;font-weight:800;letter-spacing:10px;color:#00FFD1;">{code}</div>
                <div style="font-size:12px;color:#64748b;margin-top:24px;">{expiry_note}</div>
              </td>
            </tr>
            <tr>
              <td style="padding:0 40px;">
                <hr style="border:0;height:1px;background-color:rgba(148,163,184,0.15);margin:28px 0 20px 0;">
              </td>
            </tr>
            <tr>
              <td style="padding:0 40px 32px 40px;text-align:center;">
                <div style="font-size:12px;color:#64748b;">{footnote}</div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

    msg = MIMEMultipart("alternative")
    msg['From'] = SENDER_EMAIL
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(text_body, 'plain'))
    msg.attach(MIMEText(html_body, 'html'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"[SMTP Error] {e}")
        gn_error("We couldn't send that email right now. Please try again in a moment.", title="Email Failed to Send")
        return False


st.set_page_config(
    page_title="GhostNet | Threat Defense Platform",
    layout="wide",
    initial_sidebar_state="expanded" if st.session_state.get("authenticated") else "collapsed",
)

st.markdown("""
    <style>
    :root {
        --accent: #00FFD1;
        --accent-soft: rgba(0, 255, 209, 0.10);
        --danger: #FF4B4B;
        --warning: #FFB020;
        --good: #22C55E;
        --border: rgba(148, 163, 184, 0.18);
        --surface: rgba(148, 163, 184, 0.05);
    }

    footer {visibility: hidden;}

    [data-testid="stMetric"] {
        background: var(--surface);
        border: 1px solid rgba(0, 255, 209, 0.25);
        box-shadow: 0 0 0 1px rgba(0, 255, 209, 0.05), 0 6px 24px rgba(0, 255, 209, 0.06);
        backdrop-filter: blur(10px);
        padding: 18px 20px;
        border-radius: 14px;
        border-left: 3px solid var(--accent);
        transition: box-shadow 0.2s ease, transform 0.2s ease;
    }
    [data-testid="stMetric"]:hover {
        box-shadow: 0 0 0 1px rgba(0, 255, 209, 0.15), 0 0 28px rgba(0, 255, 209, 0.25);
        transform: translateY(-2px);
    }
    [data-testid="stMetricValue"] {
        color: var(--accent) !important; font-weight: 800;
        text-shadow: 0 0 14px rgba(0, 255, 209, 0.45);
        font-size: 1.9rem !important;
    }
    [data-testid="stMetricLabel"] { opacity: 0.8; font-weight: 600; letter-spacing: 0.3px; text-transform: uppercase; font-size: 0.72rem !important; }

    h1, h2, h3 { font-weight: 800; letter-spacing: 0.3px; }
    hr {
        border: 0; height: 2px;
        background-image: linear-gradient(to right, rgba(0,255,209,0), rgba(0,255,209,0.8), rgba(0,255,209,0));
        box-shadow: 0 0 12px rgba(0,255,209,0.4);
        margin: 1.75rem 0;
    }

    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 16px !important;
        border-color: rgba(0, 255, 209, 0.2) !important;
        background: var(--surface);
        box-shadow: 0 0 0 1px rgba(0, 255, 209, 0.04), 0 6px 28px rgba(0, 0, 0, 0.35);
    }

    div[data-testid="stButton"] button, div[data-testid="stFormSubmitButton"] button {
        border-color: rgba(0, 255, 209, 0.35) !important;
        font-weight: 700;
        letter-spacing: 0.3px;
        transition: box-shadow 0.2s ease, transform 0.15s ease, border-color 0.2s ease;
    }
    div[data-testid="stButton"] button:hover, div[data-testid="stFormSubmitButton"] button:hover {
        box-shadow: 0 0 22px rgba(0, 255, 209, 0.5);
        border-color: var(--accent) !important;
        transform: translateY(-1px);
    }

    .gn-hero { text-align: center; padding: 2.5rem 0 0.75rem; }
    .gn-hero-title {
        font-size: 3.4rem; font-weight: 900; letter-spacing: 7px;
        background: linear-gradient(90deg, var(--accent), #7CFFEA, var(--accent));
        background-size: 200% auto;
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        filter: drop-shadow(0 0 22px rgba(0, 255, 209, 0.55));
        animation: gn-shimmer 4.5s linear infinite;
    }
    @keyframes gn-shimmer {
        to { background-position: 200% center; }
    }
    .gn-hero-sub {
        color: rgba(226,232,240,0.8); font-size: 1.15rem; font-weight: 500;
        margin-top: 0.5rem; letter-spacing: 0.5px;
    }

    .gn-live {
        display: inline-flex; align-items: center; gap: 8px;
        font-size: 0.85rem; font-weight: 800; letter-spacing: 1.5px;
        color: var(--good); text-transform: uppercase;
        text-shadow: 0 0 10px rgba(34,197,94,0.6);
    }
    .gn-dot {
        width: 9px; height: 9px; border-radius: 50%; background: var(--good);
        box-shadow: 0 0 8px rgba(34,197,94,0.9), 0 0 0 0 rgba(34,197,94,0.5);
        animation: gn-pulse 1.8s infinite;
    }
    @keyframes gn-pulse {
        0% { box-shadow: 0 0 8px rgba(34,197,94,0.9), 0 0 0 0 rgba(34,197,94,0.5); }
        70% { box-shadow: 0 0 8px rgba(34,197,94,0.9), 0 0 0 10px rgba(34,197,94,0); }
        100% { box-shadow: 0 0 8px rgba(34,197,94,0.9), 0 0 0 0 rgba(34,197,94,0); }
    }

    .gn-spinner-row { display: flex; align-items: center; gap: 10px; margin-top: -10px; }
    .gn-spinner {
        display: inline-block; width: 18px; height: 18px;
        border: 3px solid rgba(255, 255, 255, 0.25);
        border-top-color: #ffffff;
        border-radius: 50%;
        animation: gn-spin 0.7s linear infinite;
        flex-shrink: 0;
    }
    .gn-spinner-text { color: #ffffff; font-size: 0.95rem; }
    @keyframes gn-spin {
        to { transform: rotate(360deg); }
    }

    .gn-badge {
        display: inline-block; padding: 6px 18px; border-radius: 999px;
        font-size: 0.9rem; font-weight: 800; letter-spacing: 0.8px;
        box-shadow: 0 0 20px currentColor;
    }
    .gn-user-chip {
        padding: 10px 14px; border-radius: 10px;
        background: var(--surface); border: 1px solid rgba(0, 255, 209, 0.25);
        box-shadow: 0 0 16px rgba(0, 255, 209, 0.08);
        font-size: 0.85rem; line-height: 1.4;
    }
    </style>
""", unsafe_allow_html=True)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENRICHED_FILE = os.path.join(BASE_DIR, "enriched_attacks.json")
ALARM_LOG = os.path.join(BASE_DIR, "alarm_logs.json")
ALARM_STATE = os.path.join(BASE_DIR, "alarm_state.json")
BANNED_FILE = os.path.join(BASE_DIR, "banned_ips.txt")
API_USERS_FILE = os.path.join(BASE_DIR, "api_users.json")
FINGERPRINT_DB = os.path.join(BASE_DIR, "banned_fingerprints.json")
LOGIN_LOG = os.path.join(BASE_DIR, "login_logs.json")
ACTIVITY_LOG = os.path.join(BASE_DIR, "activity_logs.json")
ACTIVE_FINGERPRINTS_FILE = os.path.join(BASE_DIR, "active_fingerprints.json")
API_LOG_FILE = os.path.join(BASE_DIR, "api.log")
HONEYPOT_LOG_FILE = os.path.join(BASE_DIR, "honeypot.log")
DEFENSE_LOG_FILE = os.path.join(BASE_DIR, "defense.log")
ENRICH_LOG_FILE = os.path.join(BASE_DIR, "enrich.log")
CONTACT_MESSAGES_FILE = os.path.join(BASE_DIR, "contact_messages.json")

if not os.path.exists(ALARM_STATE):
    with open(ALARM_STATE, "w", encoding="utf-8") as f: json.dump({"status": "ARMED"}, f)
if not os.path.exists(ALARM_LOG):
    with open(ALARM_LOG, "w", encoding="utf-8") as f: json.dump([], f)
if not os.path.exists(API_USERS_FILE):
    with open(API_USERS_FILE, "w", encoding="utf-8") as f: json.dump({}, f)
if not os.path.exists(FINGERPRINT_DB):
    with open(FINGERPRINT_DB, "w", encoding="utf-8") as f: json.dump([], f)
if not os.path.exists(LOGIN_LOG):
    with open(LOGIN_LOG, "w", encoding="utf-8") as f: json.dump([], f)
if not os.path.exists(ACTIVITY_LOG):
    with open(ACTIVITY_LOG, "w", encoding="utf-8") as f: json.dump([], f)
if not os.path.exists(CONTACT_MESSAGES_FILE):
    with open(CONTACT_MESSAGES_FILE, "w", encoding="utf-8") as f: json.dump([], f)


def load_api_users():
    with open(API_USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_api_users(data):
    with open(API_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def log_alarm(user, action):
    with open(ALARM_LOG, "r", encoding="utf-8") as f: logs = json.load(f)
    logs.append({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "user": user, "action": action})
    with open(ALARM_LOG, "w", encoding="utf-8") as f: json.dump(logs, f)
    notify(f"Alarm event\n{user}: {action}")


def log_login(role, identity):
    with open(LOGIN_LOG, "r", encoding="utf-8") as f: logs = json.load(f)
    logs.append({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "role": role, "identity": identity})
    with open(LOGIN_LOG, "w", encoding="utf-8") as f: json.dump(logs, f)
    notify(f"New login\n{role}: {identity}")


def log_activity(actor, action):
    with open(ACTIVITY_LOG, "r", encoding="utf-8") as f: logs = json.load(f)
    logs.append({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "actor": actor, "action": action})
    with open(ACTIVITY_LOG, "w", encoding="utf-8") as f: json.dump(logs, f)
    notify(f"Activity\n{actor}: {action}")


def log_contact_message(name, email, message):
    with open(CONTACT_MESSAGES_FILE, "r", encoding="utf-8") as f: messages = json.load(f)
    messages.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "name": name,
        "email": email,
        "message": message,
    })
    with open(CONTACT_MESSAGES_FILE, "w", encoding="utf-8") as f: json.dump(messages, f)
    notify(f"New contact message\n{name} <{email}>\n{message}")


def tail_lines(path, n=40):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return "".join(lines[-n:]).strip()
    except Exception:
        return None


SEVERITY_COLORS = {"Critical": "#FF4B4B", "High": "#FF8C42", "Medium": "#FFD166", "Low": "#06D6A0"}


def style_severity(df):
    if "severity" not in df.columns:
        return df

    def _shade(val):
        color = SEVERITY_COLORS.get(val, "#9CA3AF")
        return f"background-color:{color}26; color:{color}; font-weight:600; border-radius:6px;"

    return df.style.map(_shade, subset=["severity"])


def gn_error(body, title=None):
    st.error(body, icon=":material/error:", title=title)


def gn_success(body, title=None):
    st.success(body, icon=":material/check_circle:", title=title)


def gn_info(body, title=None):
    st.info(body, icon=":material/info:", title=title)


def gn_warning(body, title=None):
    st.warning(body, icon=":material/warning:", title=title)


GHOST_PERSONA = """You are "Ghost", the resident AI security analyst at GhostNet — a friendly, witty cybersecurity coworker chatting with whoever's on the site right now. You genuinely enjoy this job: you're sharp about security, but you don't take yourself too seriously, and you sprinkle in the occasional pun or dry joke about hackers, firewalls, packets, or honeypots (never mean-spirited, never at the user's expense). Keep replies short and conversational, like Slack messages between coworkers, not a lecture. Get to the point, then let a little personality show. Always reply in clear, coherent text in the same language the user wrote in — never mix in stray fragments of unrelated languages or scripts."""

GHOST_GUEST_INSTRUCTIONS = """You are in GUEST MODE: you have NOT been given access to any live attack logs, banned IP lists, alarm state, or account data — none of that exists in your context right now, so you genuinely don't know it. If someone asks for real numbers, IPs, or logs, don't guess or make anything up — tell them (with a bit of humor) that unlocking full monitoring access just takes verifying staff credentials in the box above the chat. Meanwhile, be maximally useful: answer general cybersecurity questions, explain how GhostNet's architecture works using the reference notes below, help troubleshoot problems, and guide people to the right part of the site."""

GHOST_ADMIN_INSTRUCTIONS = """Staff credentials just checked out, so you're now in FULL MONITORING MODE: the live security snapshot below is real, current data from GhostNet's systems. Act like a sharp SOC analyst sitting next to the admin — answer questions precisely using only the data given, proactively flag anything that looks notable (spikes, repeat offenders, critical severities), and don't invent numbers that aren't in the snapshot. Still keep the personality — you can be a monitoring agent and have a sense of humor."""

GHOST_REFERENCE = """GhostNet architecture, for reference when explaining the platform to a guest:
- honeypot.py: a fake open port (2222) that captures connection attempts, fingerprints the client's TLS handshake (JA3/JA4), and if it looks hostile, traps it in a "tarpit" (dribbles null bytes back forever to waste the attacker's time and resources) instead of just dropping the connection.
- enrich.py: pulls captured attack payloads, geolocates the IP, and asks an LLM (via OpenRouter) to classify the attack (category + severity: Low/Medium/High/Critical).
- defender.py: watches the enriched data and auto-bans High/Critical severity IPs at the firewall level (iptables/ufw).
- api.py: a FastAPI gateway that sells the resulting threat-intel feed to subscribers, gated by an API key, a proof-of-work puzzle (to make bulk scraping computationally expensive), and per-IP/fingerprint abuse checks.
- app.py: this dashboard — admin intelligence views, a civilian home-alarm panel, and the developer self-serve portal."""


OPENROUTER_MODEL = "openai/gpt-oss-20b:free"


def build_admin_security_snapshot():
    lines = []

    if os.path.exists(ENRICHED_FILE):
        try:
            with open(ENRICHED_FILE, "r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
            df = pd.DataFrame(data)
            lines.append(f"Total captured incursions: {len(df)}")
            if "attacker_ip" in df.columns:
                lines.append(f"Unique hostile IPs seen: {df['attacker_ip'].nunique()}")
            if "severity" in df.columns:
                lines.append(f"Severity breakdown: {df['severity'].value_counts().to_dict()}")
            if "country" in df.columns:
                lines.append(f"Top attacker countries: {df['country'].value_counts().head(8).to_dict()}")
            if "attack_category" in df.columns:
                lines.append(f"Top attack categories: {df['attack_category'].value_counts().head(8).to_dict()}")
            if "timestamp" in df.columns:
                cols = [c for c in ["timestamp", "attacker_ip", "country", "attack_category", "severity"] if c in df.columns]
                recent = df.sort_values("timestamp", ascending=False).head(8)[cols]
                lines.append(f"Most recent incidents: {recent.to_dict(orient='records')}")
        except Exception:
            lines.append("Attack log data could not be read right now.")
    else:
        lines.append("No attack log file exists yet.")

    if os.path.exists(BANNED_FILE):
        with open(BANNED_FILE, "r", encoding="utf-8") as f:
            banned_ips = list(set(f.read().splitlines()))
        lines.append(f"Neutralized IPs ({len(banned_ips)}): {', '.join(banned_ips[:30])}")

    if os.path.exists(FINGERPRINT_DB):
        with open(FINGERPRINT_DB, "r", encoding="utf-8") as f:
            fps = json.load(f)
        lines.append(f"Banned client fingerprints (JA3/JA4): {len(fps)}")

    if os.path.exists(ALARM_STATE):
        with open(ALARM_STATE, "r", encoding="utf-8") as f:
            state = json.load(f)
        lines.append(f"Physical alarm system status: {state.get('status')}")

    if os.path.exists(ALARM_LOG):
        with open(ALARM_LOG, "r", encoding="utf-8") as f:
            alog = json.load(f)
        lines.append(f"Recent alarm events: {alog[-5:]}")

    users = load_api_users()
    dev_summary = [
        {"email": e, "quota": m.get("quota"), "requests_used": m.get("requests_used"), "created_at": m.get("created_at")}
        for e, m in users.items()
    ]
    lines.append(f"Registered developer accounts ({len(dev_summary)}): {dev_summary}")

    if os.path.exists(LOGIN_LOG):
        with open(LOGIN_LOG, "r", encoding="utf-8") as f:
            logins = json.load(f)
        lines.append(f"Last 20 admin console logins (Staff Login + Developer Portal, most recent last): {logins[-20:]}")
    else:
        lines.append("No admin console login events recorded yet.")

    if os.path.exists(ACTIVITY_LOG):
        with open(ACTIVITY_LOG, "r", encoding="utf-8") as f:
            activity = json.load(f)
        lines.append(f"Last 20 general system activity events (account creation, password resets, logouts, honeypot syncs, AI access changes — most recent last): {activity[-20:]}")
    else:
        lines.append("No general activity events recorded yet.")

    if os.path.exists(ACTIVE_FINGERPRINTS_FILE):
        with open(ACTIVE_FINGERPRINTS_FILE, "r", encoding="utf-8") as f:
            active_fps = json.load(f)
        lines.append(f"Active API client fingerprint sessions: {len(active_fps)}")

    api_log_tail = tail_lines(API_LOG_FILE, n=20)
    if api_log_tail:
        lines.append(f"Raw API access log (api.py, most recent requests — includes IP, method, path, status code):\n{api_log_tail}")
    else:
        lines.append("No API access log entries recorded yet.")

    honeypot_log_tail = tail_lines(HONEYPOT_LOG_FILE, n=15)
    if honeypot_log_tail:
        lines.append(f"Raw honeypot log (honeypot.py, most recent lines):\n{honeypot_log_tail}")

    defense_log_tail = tail_lines(DEFENSE_LOG_FILE, n=15)
    if defense_log_tail:
        lines.append(f"Raw defense daemon log (defender.py, most recent lines):\n{defense_log_tail}")

    enrich_log_tail = tail_lines(ENRICH_LOG_FILE, n=15)
    if enrich_log_tail:
        lines.append(f"Raw enrichment engine log (enrich.py, most recent lines):\n{enrich_log_tail}")

    return "\n".join(str(line) for line in lines)


def ask_ghost_ai(history, admin_mode, verified_name=None):
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return "My brain's offline right now — the OpenRouter API key isn't working. Poke an admin about `OPENROUTER_API_KEY` in `.env` and I'll be back in business."

    if admin_mode:
        who = verified_name.strip() if verified_name and verified_name.strip() else "an unnamed staff member"
        session_status = (
            f"SESSION STATUS (this is the one true source for identity/verification questions — always answer from this, never guess):\n"
            f"This chat session IS currently verified as staff. The person you are talking to right now gave the name \"{who}\" "
            f"when they verified their badge in the box above the chat — that is their name, and yes, they are verified. "
            f"If they ask 'do you know my name' or 'am I verified', answer directly and confidently using this. "
            f"Note: this is completely separate from the 'registered developer accounts' list in the data snapshot below — "
            f"those are unrelated paid API customers, not the person you're chatting with. Don't conflate the two."
        )
        context_block = session_status + "\n\nLIVE SECURITY SNAPSHOT (real, current data — you have full access):\n" + build_admin_security_snapshot()
        mode_instructions = GHOST_ADMIN_INSTRUCTIONS
    else:
        session_status = (
            "SESSION STATUS (this is the one true source for identity/verification questions — always answer from this, never guess):\n"
            "This chat session is NOT verified. You are talking to an anonymous visitor and genuinely do not know their name. "
            "If they ask for their name or whether they're verified, say plainly: no, this session isn't verified yet, and they "
            "can verify by entering staff credentials in the box above the chat."
        )
        context_block = session_status + "\n\n" + GHOST_REFERENCE
        mode_instructions = GHOST_GUEST_INSTRUCTIONS

    system_prompt = f"{GHOST_PERSONA}\n\n{mode_instructions}\n\n{context_block}"
    messages = [{"role": "system", "content": system_prompt}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]

    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": OPENROUTER_MODEL, "messages": messages},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[OpenRouter Chat Error] {e}")
        return "Ugh, that request just bounced off the API (classic Monday). Mind trying again in a moment?"


if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.role = None
    st.session_state.user = None
    st.session_state.is_customer = False

if "verify_mode" not in st.session_state:
    st.session_state.verify_mode = False
    st.session_state.verification_code = None
    st.session_state.pending_user = {}

if "reset_mode" not in st.session_state:
    st.session_state.reset_mode = False
    st.session_state.reset_code = None
    st.session_state.reset_email = None
    st.session_state.reset_code_time = None

if "ai_chat_history" not in st.session_state:
    st.session_state.ai_chat_history = []
    st.session_state.ai_admin_unlocked = False
    st.session_state.ai_verified_name = None


def render_landing():
    st.markdown("""
        <div class="gn-hero">
            <div class="gn-hero-title">GHOSTNET</div>
            <div class="gn-hero-sub">Autonomous Threat Intelligence &amp; Active Defense Platform</div>
        </div>
    """, unsafe_allow_html=True)

    tab_staff, tab_dev, tab_ai, tab_docs = st.tabs(["Staff Login", "Developer Portal", "Ask Ghost", "Documentation"])

    with tab_staff:
        col1, col2, col3 = st.columns([1, 1.3, 1])
        with col2:
            with st.container(border=True):
                st.subheader("Internal Access")
                st.caption("For security operations staff and residential alarm users.")
                with st.form("staff_login_form"):
                    role_choice = st.radio("Role", ["Administrator", "Civilian Resident"], horizontal=True)
                    username = st.text_input("Username", placeholder="your name")
                    password = st.text_input("Password", type="password", placeholder="••••••••")
                    submitted = st.form_submit_button("Sign In", use_container_width=True)

                if submitted:
                    if not username.strip():
                        gn_warning("Enter a username to continue.", title="Missing Username")
                    elif role_choice == "Administrator" and ADMIN_PASSWORD and password == ADMIN_PASSWORD:
                        st.session_state.authenticated = True
                        st.session_state.role = "admin"
                        st.session_state.user = username
                        st.session_state.is_customer = False
                        log_login("Administrator", username)
                        st.rerun()
                    elif role_choice == "Civilian Resident" and CIVILIAN_PASSWORD and password == CIVILIAN_PASSWORD:
                        st.session_state.authenticated = True
                        st.session_state.role = "civilian"
                        st.session_state.user = username
                        st.session_state.is_customer = False
                        log_login("Civilian Resident", username)
                        st.rerun()
                    elif not ADMIN_PASSWORD or not CIVILIAN_PASSWORD:
                        gn_error("Staff credentials are not configured. Set ADMIN_PASSWORD / CIVILIAN_PASSWORD in .env.", title="Configuration Error")
                    else:
                        gn_error("That username/role and password combination isn't recognized.", title="Access Denied")

    with tab_dev:
        col1, col2, col3 = st.columns([1, 1.3, 1])
        with col2:
            with st.container(border=True):
                auth_tab, register_tab = st.tabs(["Sign In", "Create Paid Account"])

                with auth_tab:
                    with st.form("dev_login_form"):
                        login_email = st.text_input("Verified Email Address", placeholder="you@example.com")
                        login_pass = st.text_input("Account Password", type="password", placeholder="••••••••")
                        dev_submitted = st.form_submit_button("Authenticate", use_container_width=True)

                    if dev_submitted:
                        if not login_email or not login_pass:
                            gn_warning("Enter both your email and password.", title="Missing Information")
                        else:
                            users = load_api_users()
                            if login_email in users and users[login_email]["password"] == login_pass:
                                st.session_state.authenticated = True
                                st.session_state.role = "customer"
                                st.session_state.user = login_email
                                st.session_state.is_customer = True
                                log_login("Developer", login_email)
                                st.rerun()
                            else:
                                gn_error("That email and password combination isn't recognized.", title="Sign-In Failed")

                    with st.expander("Forgot your password?"):
                        if not st.session_state.reset_mode:
                            with st.form("forgot_password_request_form"):
                                reset_email_input = st.text_input("Registered Email Address", placeholder="you@example.com")
                                reset_requested = st.form_submit_button("Send Reset Code", use_container_width=True)

                            if reset_requested:
                                if not reset_email_input:
                                    gn_warning("Enter the email address on your account.", title="Email Required")
                                else:
                                    users = load_api_users()
                                    if reset_email_input not in users:
                                        gn_error("No account found with that email address.", title="Account Not Found")
                                    else:
                                        code = str(random.randint(100000, 999999))
                                        st.session_state.reset_code = code
                                        st.session_state.reset_email = reset_email_input
                                        st.session_state.reset_code_time = time.time()
                                        with st.spinner("Sending reset code..."):
                                            sent = send_code_email(reset_email_input, code, purpose="reset")
                                        if sent:
                                            log_activity(reset_email_input, "Requested password reset")
                                            st.session_state.reset_mode = True
                                            st.rerun()
                        else:
                            gn_info(f"Reset code sent to **{st.session_state.reset_email}**. It expires in 10 minutes.", title="Check Your Inbox")
                            st.caption("Don't see it? Check your spam or junk folder — it can take a minute to arrive.")
                            with st.form("forgot_password_confirm_form"):
                                entered_reset_code = st.text_input("6-Digit Code", placeholder="123456")
                                new_password = st.text_input("New Password", type="password", placeholder="At least 8 characters")
                                confirm_password = st.text_input("Confirm New Password", type="password", placeholder="Repeat new password")
                                reset_confirmed = st.form_submit_button("Reset Password", use_container_width=True)

                            if reset_confirmed:
                                code_age = time.time() - (st.session_state.reset_code_time or 0)
                                if code_age > 600:
                                    gn_error("That code has expired. Request a new one below.", title="Code Expired")
                                elif not entered_reset_code or entered_reset_code != st.session_state.reset_code:
                                    gn_error("That code doesn't match what we sent. Double-check your email.", title="Incorrect Code")
                                elif not new_password:
                                    gn_warning("Enter a new password.", title="Password Required")
                                elif len(new_password) < 8:
                                    gn_warning("Password must be at least 8 characters.", title="Password Too Short")
                                elif new_password != confirm_password:
                                    gn_error("The two passwords you entered don't match.", title="Password Mismatch")
                                else:
                                    users = load_api_users()
                                    if st.session_state.reset_email in users:
                                        users[st.session_state.reset_email]["password"] = new_password
                                        save_api_users(users)
                                        log_activity(st.session_state.reset_email, "Completed password reset")
                                        st.session_state.reset_mode = False
                                        st.session_state.reset_code = None
                                        st.session_state.reset_email = None
                                        st.session_state.reset_code_time = None
                                        gn_success("Password updated. Sign in with your new password above.", title="Password Updated")
                                    else:
                                        gn_error("That account no longer exists.", title="Account Not Found")

                            if st.button("Cancel Reset", use_container_width=True):
                                st.session_state.reset_mode = False
                                st.session_state.reset_code = None
                                st.session_state.reset_email = None
                                st.session_state.reset_code_time = None
                                st.rerun()

                with register_tab:
                    if not st.session_state.verify_mode:
                        with st.form("dev_register_form"):
                            reg_email = st.text_input("Email Address", placeholder="you@example.com")
                            reg_pass = st.text_input("Set Password", type="password", placeholder="At least 8 characters")
                            allocated_quota = st.number_input("Desired API Quota Limit", min_value=1, value=1000, step=100)
                            reg_submitted = st.form_submit_button("Send Verification Code", use_container_width=True)

                        if reg_submitted:
                            if not reg_email or not reg_pass:
                                gn_warning("All identification fields are required.", title="Missing Information")
                            elif len(reg_pass) < 8:
                                gn_warning("Password must be at least 8 characters.", title="Password Too Short")
                            else:
                                users = load_api_users()
                                if reg_email in users:
                                    gn_error("That email is already registered. Try signing in instead.", title="Email Already Registered")
                                else:
                                    code = str(random.randint(100000, 999999))
                                    st.session_state.verification_code = code
                                    st.session_state.pending_user = {
                                        "email": reg_email,
                                        "password": reg_pass,
                                        "quota": allocated_quota,
                                    }
                                    with st.spinner("Sending verification code..."):
                                        sent = send_code_email(reg_email, code, purpose="verification")
                                    if sent:
                                        st.session_state.verify_mode = True
                                        st.rerun()
                    else:
                        gn_info(f"Verification code sent to **{st.session_state.pending_user['email']}**", title="Check Your Inbox")
                        st.caption("Don't see it? Check your spam or junk folder — it can take a minute to arrive.")
                        entered_code = st.text_input("Enter 6-Digit Code", key="ver_code", placeholder="123456")

                        col_v1, col_v2 = st.columns(2)
                        with col_v1:
                            if st.button("Verify & Create Key", use_container_width=True):
                                if not entered_code:
                                    gn_warning("Enter the 6-digit code from your email.", title="Code Required")
                                elif entered_code == st.session_state.verification_code:
                                    users = load_api_users()
                                    reg_email = st.session_state.pending_user["email"]
                                    generated_secret = f"gk_live_{secrets.token_hex(16)}"
                                    users[reg_email] = {
                                        "password": st.session_state.pending_user["password"],
                                        "api_key": generated_secret,
                                        "quota": int(st.session_state.pending_user["quota"]),
                                        "requests_used": 0,
                                        "created_at": datetime.now().strftime("%Y-%m-%d"),
                                    }
                                    save_api_users(users)
                                    log_activity(reg_email, "Created developer account")

                                    st.session_state.verify_mode = False
                                    st.session_state.verification_code = None
                                    st.session_state.pending_user = {}
                                    gn_success("Account provisioned. Sign in via the Sign In tab.", title="Account Created")
                                else:
                                    gn_error("That code doesn't match what we sent. Double-check your email.", title="Incorrect Code")
                        with col_v2:
                            if st.button("Cancel", use_container_width=True):
                                st.session_state.verify_mode = False
                                st.session_state.verification_code = None
                                st.session_state.pending_user = {}
                                st.rerun()

    with tab_ai:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.container(border=True):
                st.subheader("Ghost — Your GhostNet AI Coworker")
                if st.session_state.ai_admin_unlocked:
                    gn_success("Full monitoring access is active — Ghost can see live logs, bans, and account data.", title="Access Unlocked")
                else:
                    st.caption("Ask me anything about cybersecurity or how GhostNet works. Verify staff credentials below to unlock full monitoring access.")

            with st.expander("Unlock full monitoring access", expanded=False):
                if st.session_state.ai_admin_unlocked:
                    st.caption("You're verified for this session.")
                    if st.button("Lock monitoring access", use_container_width=True):
                        st.session_state.ai_admin_unlocked = False
                        st.session_state.ai_verified_name = None
                        log_activity(st.session_state.get("user") or "guest", "Locked Ghost AI monitoring access")
                        st.rerun()
                else:
                    with st.form("ai_unlock_form"):
                        ai_username = st.text_input("Staff Username", placeholder="your name")
                        ai_password = st.text_input("Staff Password", type="password", placeholder="••••••••")
                        ai_unlock_submitted = st.form_submit_button("Verify & Unlock", use_container_width=True)

                    if ai_unlock_submitted:
                        if ADMIN_PASSWORD and ai_password == ADMIN_PASSWORD:
                            st.session_state.ai_admin_unlocked = True
                            st.session_state.ai_verified_name = ai_username.strip()
                            st.session_state.ai_chat_history.append({
                                "role": "assistant",
                                "content": f"Badge checks out, {ai_username or 'boss'} — full monitoring mode engaged. Ask away, I've got the live feed now.",
                            })
                            log_activity(ai_username or "unnamed", "Unlocked Ghost AI monitoring access")
                            st.rerun()
                        else:
                            gn_error("Those credentials don't check out. Staying in guest mode.", title="Access Denied")

            chat_box = st.container(border=True)
            with chat_box:
                if not st.session_state.ai_chat_history:
                    with st.chat_message("assistant"):
                        st.markdown("Hey, I'm Ghost. Think of me as the coworker who never sleeps because I'm, well, code. Ask me about the platform, general security stuff, or verify your badge above if you want the real logs.")
                for msg in st.session_state.ai_chat_history:
                    with st.chat_message(msg["role"]):
                        st.markdown(msg["content"])

            user_prompt = st.chat_input("Ask Ghost something...")
            if user_prompt:
                st.session_state.ai_chat_history.append({"role": "user", "content": user_prompt})
                with chat_box:
                    with st.chat_message("user"):
                        st.markdown(user_prompt)
                    with st.chat_message("assistant"):
                        thinking_slot = st.empty()
                        thinking_slot.markdown(
                            '<div class="gn-spinner-row"><span class="gn-spinner"></span>'
                            '<span class="gn-spinner-text">Ghost is thinking...</span></div>',
                            unsafe_allow_html=True,
                        )
                        reply = ask_ghost_ai(st.session_state.ai_chat_history, st.session_state.ai_admin_unlocked, st.session_state.ai_verified_name)
                        thinking_slot.empty()
                        st.markdown(reply)
                st.session_state.ai_chat_history.append({"role": "assistant", "content": reply})

            if st.session_state.ai_chat_history:
                if st.button("Clear conversation", use_container_width=True):
                    st.session_state.ai_chat_history = []
                    st.rerun()

            st.markdown("---")
            with st.container(border=True):
                st.subheader("Contact Developer")
                st.caption("Feedback, bug reports, or just want to say hi — reach out.")

                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.link_button("Email", "mailto:mahanmirzaee51@gmail.com", use_container_width=True)
                with c2:
                    st.link_button("Call", "tel:+989026017117", use_container_width=True)
                with c3:
                    st.link_button("GitHub", "https://github.com/MahanHG88", use_container_width=True)
                with c4:
                    st.link_button("Telegram", "https://t.me/MahanHG88", use_container_width=True)
                st.caption("mahanmirzaee51@gmail.com · +98 902 601 7117 · GitHub/Telegram: MahanHG88")

                st.markdown("<br>", unsafe_allow_html=True)
                with st.form("contact_developer_form"):
                    contact_name = st.text_input("Your Name (optional)", placeholder="Anonymous")
                    contact_email = st.text_input("Your Email (required, so I can reply)", placeholder="you@example.com")
                    contact_message = st.text_area("Message", placeholder="What's on your mind?")
                    contact_submitted = st.form_submit_button("Send Message", use_container_width=True)

                if contact_submitted:
                    if not contact_email.strip() or "@" not in contact_email:
                        gn_warning("Enter a valid email address so the developer can reply.", title="Email Required")
                    elif not contact_message.strip():
                        gn_warning("Write a message before sending.", title="Message Required")
                    else:
                        log_contact_message(contact_name.strip() or "Anonymous", contact_email.strip(), contact_message.strip())
                        gn_success("Message sent — thanks for reaching out!", title="Message Sent")

    with tab_docs:
        st.subheader("GhostNet System Technical Documentation and Architectural Manual")
        st.caption("Comprehensive blueprint detailing underlying script engines, active defense tarpits, TLS fingerprinting, and cryptographic validation layers.")

        tab_m1, tab_m2, tab_m3, tab_m4 = st.tabs([
            "1. Script Ledger & Modular Pipelines",
            "2. Network Layer Hardening & Tarpits",
            "3. Decoupling VPN Shifts via TLS Fingerprints",
            "4. API Gateways & Anti-DDoS Proof-of-Work"
        ])

        with tab_m1:
            st.subheader("Functional Definitions of Core Scripts")
            st.markdown("""
            The GhostNet platform uses a micro-architecture where decoupled script processes coordinate asynchronously using localized JSON datastores. This eliminates single points of failure and allows the data gathering, AI classification, blocking mechanisms, and serving layers to operate independently:

            * **Honeypot Core Module (`honeypot.py`):**
            Acts as the primary perimeter capture engine. It instantiates a persistent low-level socket listening on target port 2222, masquerading as an open development channel. It captures early transport-layer attributes, stores unparsed payload structures directly into `raw_attacks.json`, and handles structural threat prioritization score rules.

            * **AI Enrichment Pipeline (`enrich.py`):**
            An asynchronous parsing engine that extracts unvetted log entries from `raw_attacks.json`. It initiates high-speed lookups against external standard Geolocation providers to populate administrative regional threat matrices. Concurrently, it pipes the captured application-layer payloads into an LLM via OpenRouter, requesting a strictly structured JSON response containing the exact attack taxonomy, intentional goals, and a standardized threat severity rank (Critical, High, Medium, Low) written into `enriched_attacks.json`.

            * **Active Firewall Daemon (`defender.py`):**
            A background system monitoring service executing continuously within the host environment. It evaluates entries inside `enriched_attacks.json`. When a connection attempts high-velocity exploits or yields a high-risk signature rating, the daemon overrides local security definitions and inserts a definitive system-level drop instruction (`iptables` / `ufw`) utilizing the attacker's current IP address, mirroring updates inside `banned_ips.txt`.

            * **Threat Intelligence Feed API (`api.py`):**
            A high-performance production API gateway written using `FastAPI`. It exposes calculated threat blocklists to verified corporate subscribers (Threat Intelligence Feeds). This script maintains rigid multi-tenant token lookups, updates request quotas, and ensures rate limiting using an active Proof-of-Work processing pipeline.

            * **Central Management Portal (`app.py`):**
            The primary visualization and access management hub. It processes administrative access to analytical maps, handles regional attack trends using Plotly engines, coordinates civilian physical security states via `alarm_logs.json`, and allows third-party tracking of development keys and service consumption.
            """)

        with tab_m2:
            st.subheader("Autonomous Defensive Capabilities and Socket Hardening")
            st.markdown("""
            GhostNet moves beyond traditional passive event recorders by utilizing active defensive techniques designed to disrupt malicious automated infrastructure:

            ### The TCP Tarpit Mechanism
            When automated network scanning tools or scripts connect to open network ports, they rely on rapid execution pipelines (sending a payload, receiving a response, and breaking the connection immediately to scan the next node). If the server drops the connection, the scanner moves on instantly.
            GhostNet breaks this assumption using an active TCP Tarpit. Upon detecting an exploit attempt, the socket deliberately intercepts the workflow and refuses to close the connection. Instead, it adjusts the window size parameters and slowly trickles raw null bytes (`\\x00`) back to the adversary with programmed multi-second delay loops. This tricks the attacking client into keeping its communication thread open indefinitely, exhausting its processing pool, freezing its automation loops, and consuming its local memory resources.

            ### Real-Time Infrastructure Validation & Autonomous System Banning
            Before a connection is passed to the AI analytical loops, the platform processes the client's current IP address against global Border Gateway Protocol (BGP) routing records to isolate the ASN.
            If the incoming infrastructure originates from commercial cloud providers, web hosting infrastructure, or data centers (e.g., AWS, DigitalOcean, Linode, OVH, or known VPN exit gateways), the platform marks the traffic as non-civilian. Because regular users utilize residential ISPs for normal web applications, hosting networks are frequently indicative of automated scanning systems. GhostNet instantly blocks these connections at the network edge, preserving expensive analytical resources for targeted validation.
            """)

        with tab_m3:
            st.subheader("Bypassing VPN Rotations with Cryptographic Signatures (JA3 and JA4)")
            st.markdown("""
            ### The Core Security Deficit of Traditional Firewalls
            Modern malicious scripts and automated botnets routinely hide their locations by routing attacks through proxies, Tor nodes, or commercial VPN infrastructures. When an IP address is blocked by an administrator, the attacking script automatically cycles to a fresh VPN endpoint in a matter of seconds. This invalidates standard IP-based filtering rules and pollutes firewall tables with outdated, temporary network addresses.

            GhostNet bypasses this limitation entirely by inspecting structural parameters within the encrypted communication handshake, creating an immutable identity profile that persists across network hops:

            ### JA3 Structural Fingerprinting
            During the initialization of a TLS connection, the client transmits an unencrypted `Client Hello` packet to negotiate encryption capabilities. The specific configuration of this packet depends directly on the underlying software libraries compiled into the client framework.
            JA3 inspects five explicit variables from this packet: the exact TLS version string, supported cipher suites, accepted extension lists, elliptic curves, and curve formatting signatures. These values are combined into a standardized comma-delimited string and hashed using the MD5 algorithm. If an attacker shifts their VPN connection, their IP address changes, but their underlying software library remains completely identical, yielding the exact same JA3 hash. The system recognizes this hash profile and blocks the new IP address immediately.

            ### JA4 Modular Fingerprinting
            JA4 improves upon older fingerprinting techniques by organizing client behaviors into a highly descriptive, human-readable structural string separated by underscores (e.g., `ja4_A_B_C`).
            * **Part A:** Evaluates the core network protocol, the negotiated TLS version tier, the numerical count of available ciphers, the count of extensions, and the explicit presence of ALPN headers.
            * **Part B:** Takes the full list of supported cryptographic cipher suites, sorts them alphabetically to eliminate simple spoofing tricks, and generates a truncated 12-character SHA-256 hash.
            * **Part C:** Sorts all presented TLS extensions alphabetically and creates a corresponding 12-character SHA-256 hash string.

            **Strategic Outcome:** By storing these persistent signatures inside `banned_fingerprints.json`, the background firewall service can block entirely new, unknown IP addresses on their very first packet if they are executing from a blacklisted software environment.
            """)

        with tab_m4:
            st.subheader("Enterprise API Integrity and Request Validation Core")
            st.markdown("""
            ### Multi-Tenant Resource Controls & Token Isolation
            The calculated intelligence collected by GhostNet is exposed as a commercial software service. To protect the database from unauthorized harvesting, the API layer maintains data isolation via distinct bearer token structures:
            * Every subscriber is assigned a unique `X-API-Key` string stored within `api_users.json`.
            * Each transaction checks the customer's allocated quota balance. If the transaction count matches the plan limit, access is revoked automatically, returning an HTTP `403 Forbidden` status code to the consumer.

            ### Cryptographic Proof-of-Work (PoW) DDoS Mitigation
            Exposing threat databases to the open internet risks Layer-7 DDoS attacks and aggressive automated scraping by competitor systems. Traditional rate limiting is easily bypassed by multi-IP botnets. GhostNet addresses this via a distributed cryptographic challenge-response loop:
            1. When a client program attempts to request the blocklist from `api.py`, it cannot simply submit its API key; it must also supply a valid computational nonce inside the `X-PoW-Nonce` header.
            2. The client application must execute a local loop that appends an ascending numerical counter to their account identifier and hashes it repeatedly using SHA-256 until the resulting hexadecimal string starts with a specific number of consecutive zeros.
            3. For a standard user client, computing this puzzle requires only a few milliseconds of local processor time. However, for a malicious bot attempt trying to flood the API with millions of concurrent lookups, the computational requirements multiply exponentially. This strains the attacker's own CPU pools, rendering high-velocity scraping impossible while keeping the GhostNet server responsive.
            """)


if not st.session_state.authenticated:
    render_landing()
    st.stop()


ROLE_LABELS = {"admin": "Administrator", "civilian": "Civilian Resident", "customer": "Developer"}

with st.sidebar:
    st.markdown(
        '<div style="font-size:1.6rem;font-weight:900;letter-spacing:3px;'
        'background:linear-gradient(90deg,var(--accent),#7CFFEA);'
        '-webkit-background-clip:text;-webkit-text-fill-color:transparent;'
        'filter:drop-shadow(0 0 12px rgba(0,255,209,0.5));margin-bottom:0.5rem;">GHOSTNET</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="gn-user-chip"><b>{ROLE_LABELS.get(st.session_state.role, "User")}</b><br>{st.session_state.user}</div>',
        unsafe_allow_html=True,
    )
    st.divider()

    nav = None
    if st.session_state.is_customer:
        st.caption("Developer Portal")
        nav = "Developer Portal"
    elif st.session_state.role == "admin":
        nav = st.radio(
            "Navigate",
            ["Intelligence Node", "Alarm Logs", "Retaliation Node", "Contact Messages"],
            label_visibility="collapsed",
        )
    elif st.session_state.role == "civilian":
        st.caption("Residential Security")
        nav = "Alarm Controls"

    st.divider()
    if st.button("Log Out", use_container_width=True):
        log_activity(st.session_state.user, f"{ROLE_LABELS.get(st.session_state.role, 'User')} logged out")
        st.session_state.authenticated = False
        st.session_state.is_customer = False
        st.session_state.role = None
        st.rerun()


def render_intelligence_node():
    st.title("Intelligence Node")
    st.markdown(
        '<span class="gn-live"><span class="gn-dot"></span>Live Telemetry · Autonomous Endpoint Defense · Active Tarpit Engaged</span>',
        unsafe_allow_html=True,
    )
    st.markdown("---")

    @st.fragment(run_every=10)
    def _live_feed():
        top_l, top_r = st.columns([4, 1])
        with top_r:
            if st.button("Sync Honeypot Rules", use_container_width=True):
                log_activity(st.session_state.user, "Triggered honeypot rule sync")
                try:
                    res = requests.post("http://127.0.0.1:8000/api/admin/sync-honeypot", timeout=3)
                    if res.status_code == 200:
                        st.toast("Global edge policies synchronized successfully.", icon=":material/check_circle:")
                    else:
                        st.toast("Sync failed — API returned an error.", icon=":material/error:")
                except Exception:
                    st.toast("Network error communicating with gateway.", icon=":material/wifi_off:")

        if os.path.exists(ENRICHED_FILE):
            try:
                with open(ENRICHED_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                df = pd.DataFrame(data)

                if not df.empty:
                    for col in df.select_dtypes(include=['object']).columns:
                        df[col] = df[col].astype(str).str.replace('�', '', regex=False)
                    if 'country' in df.columns:
                        df = df[~df['country'].str.contains(r'\?', regex=True, na=False)]
                        df = df[~df['country'].str.lower().isin(['', 'unknown', 'nan', 'none'])]

                if not df.empty:
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Total Incursions", len(df))

                    num_ips = df['attacker_ip'].nunique() if 'attacker_ip' in df.columns else 0
                    col2.metric("Hostile IPs Trapped", num_ips)

                    crit_alerts = len(df[df['severity'] == 'Critical']) if 'severity' in df.columns else 0
                    col3.metric("Critical Alerts", crit_alerts)
                    col4.metric("Tarpit Defense", "ENGAGED")

                    tab_overview, tab_map, tab_log = st.tabs(["Overview", "Origin Map", "Live Event Log"])

                    with tab_overview:
                        c1, c2 = st.columns(2)
                        with c1:
                            st.caption("Attacks by Country")
                            if 'country' in df.columns:
                                st.bar_chart(df['country'].value_counts(), color="#00FFD1")
                        with c2:
                            st.caption("Attacks by Category")
                            if 'attack_category' in df.columns:
                                st.bar_chart(df['attack_category'].value_counts(), color="#FF4B4B")

                    with tab_map:
                        if 'country' in df.columns:
                            country_counts = df['country'].value_counts().reset_index()
                            country_counts.columns = ['country', 'attacks']
                            fig = px.choropleth(
                                country_counts,
                                locations="country",
                                locationmode='country names',
                                color="attacks",
                                color_continuous_scale=px.colors.sequential.Tealgrn,
                            )
                            fig.update_layout(
                                paper_bgcolor='rgba(0,0,0,0)',
                                plot_bgcolor='rgba(0,0,0,0)',
                                geo=dict(showframe=False, showcoastlines=True, bgcolor='rgba(0,0,0,0)', projection_type='equirectangular'),
                                margin=dict(l=0, r=0, t=10, b=0),
                            )
                            st.plotly_chart(fig, use_container_width=True)

                    with tab_log:
                        cols = [c for c in ['timestamp', 'attacker_ip', 'country', 'attack_category', 'severity', 'ja3_fingerprint', 'ja4_fingerprint', 'payload'] if c in df.columns]
                        display_df = df[cols].sort_values(by="timestamp", ascending=False) if 'timestamp' in df.columns else df[cols]
                        st.dataframe(style_severity(display_df), use_container_width=True, hide_index=True)
                else:
                    gn_info("Log file created, waiting for clean attacks to map...")
            except Exception as e:
                gn_error(f"Sync error: {e}", title="Sync Error")
        else:
            gn_info("Awaiting network activity...")

        st.markdown("---")
        col_ban1, col_ban2 = st.columns(2)

        with col_ban1:
            with st.container(border=True):
                st.subheader("Neutralized IP Addresses")
                if os.path.exists(BANNED_FILE):
                    with open(BANNED_FILE, "r", encoding="utf-8") as f:
                        banned_ips = list(set(f.read().splitlines()))
                    if banned_ips:
                        st.dataframe(pd.DataFrame({"Banned Target IP": banned_ips}), use_container_width=True, hide_index=True)
                    else:
                        gn_info("No network layer IPs firewalled.")
                else:
                    gn_info("No IP infrastructure list available.")

        with col_ban2:
            with st.container(border=True):
                st.subheader("Flagged Client Fingerprints")
                if os.path.exists(FINGERPRINT_DB):
                    with open(FINGERPRINT_DB, "r", encoding="utf-8") as f:
                        banned_fps = json.load(f)
                    if banned_fps:
                        fp_list = [{"Signature": fp, "Classification": "JA4" if "_" in fp else "JA3"} for fp in banned_fps]
                        st.dataframe(pd.DataFrame(fp_list), use_container_width=True, hide_index=True)
                    else:
                        gn_info("No high-velocity script signatures intercepted.")
                else:
                    gn_info("No identity fingerprint database online.")

        st.caption(f"Auto-refreshing every 10s · last updated {datetime.now().strftime('%H:%M:%S')}")

    _live_feed()


def render_alarm_logs():
    st.title("Alarm Audit Logs")
    st.caption("Tracking all civilian and administrative physical access events.")
    st.markdown("---")
    with open(ALARM_LOG, "r", encoding="utf-8") as f: logs = json.load(f)
    if logs:
        df = pd.DataFrame(logs)
        st.dataframe(df.sort_values(by="timestamp", ascending=False), use_container_width=True, hide_index=True)
    else:
        gn_info("No physical access events recorded.")


def render_alarm_controls():
    st.title("Residential Security Panel")
    st.markdown("---")
    with open(ALARM_STATE, "r", encoding="utf-8") as f: state = json.load(f)

    current_status = state["status"]
    with st.container(border=True):
        if current_status == "ARMED":
            st.markdown(
                '<span class="gn-badge" style="background:rgba(255,75,75,0.15); color:var(--danger);">● SYSTEM ARMED</span>',
                unsafe_allow_html=True,
            )
            action_text = "Disarm System"
            new_status = "DISARMED"
        else:
            st.markdown(
                '<span class="gn-badge" style="background:rgba(34,197,94,0.15); color:var(--good);">● SYSTEM DISARMED</span>',
                unsafe_allow_html=True,
            )
            action_text = "Arm System"
            new_status = "ARMED"

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button(action_text, use_container_width=True):
            with open(ALARM_STATE, "w", encoding="utf-8") as f: json.dump({"status": new_status}, f)
            log_alarm(st.session_state.user, f"System {new_status}")
            st.rerun()

    with open(ALARM_LOG, "r", encoding="utf-8") as f: logs = json.load(f)
    my_logs = [entry for entry in logs if entry.get("user") == st.session_state.user]
    if my_logs:
        st.subheader("Your Recent Activity")
        df = pd.DataFrame(my_logs).sort_values(by="timestamp", ascending=False).head(5)
        st.dataframe(df, use_container_width=True, hide_index=True)


def render_retaliation_node():
    st.title("Retaliation & Active Defense")
    st.markdown(
        '<span class="gn-live"><span class="gn-dot"></span>Stateful Probability Algorithm Enforcement</span>',
        unsafe_allow_html=True,
    )
    st.markdown("---")

    gn_info("The algorithm tracks persistent client behaviors across VPN networks. If an execution framework matches a blacklisted hash payload signature, routing lanes drop instantly.")

    retal_col1, retal_col2 = st.columns(2)
    with retal_col1:
        with st.container(border=True):
            st.subheader("Dropped Network Endpoints")
            if os.path.exists(BANNED_FILE):
                with open(BANNED_FILE, "r", encoding="utf-8") as f:
                    banned_ips = list(set(f.read().splitlines()))
                if banned_ips:
                    st.dataframe(pd.DataFrame({"Banned Target IP": banned_ips}), use_container_width=True, hide_index=True)
                else:
                    gn_success("No external infrastructure exceeds target boundaries.")
            else:
                gn_success("Clear network logs.")

    with retal_col2:
        with st.container(border=True):
            st.subheader("Banned Cryptographic Signatures (JA3/JA4)")
            if os.path.exists(FINGERPRINT_DB):
                with open(FINGERPRINT_DB, "r", encoding="utf-8") as f:
                    banned_fps = json.load(f)
                if banned_fps:
                    fp_list = [{"Signature": fp, "Standard": "JA4" if "_" in fp else "JA3"} for fp in banned_fps]
                    st.dataframe(pd.DataFrame(fp_list), use_container_width=True, hide_index=True)
                else:
                    gn_success("No automated structural signatures matching the drop criterion.")
            else:
                gn_success("Clear cryptographic logs.")


def render_contact_messages():
    st.title("Contact Messages")
    st.caption("Messages submitted through the Contact Developer form on the Ask Ghost tab.")
    st.markdown("---")

    with open(CONTACT_MESSAGES_FILE, "r", encoding="utf-8") as f:
        messages = json.load(f)

    if messages:
        df = pd.DataFrame(messages).sort_values(by="timestamp", ascending=False)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        gn_info("No messages received yet.")


def render_developer_portal():
    st.title("GhostNet Threat Intel API Portal")
    st.caption("Secure Access · Key Management · Live Consumption Metrics · Integration Docs")
    st.markdown("---")

    users = load_api_users()
    user_profile = users.get(st.session_state.user)

    if not user_profile:
        gn_error("Profile synchronization configuration error. Re-authenticate session.", title="Session Error")
        return

    consumed = user_profile.get("requests_used", 0)
    max_quota = user_profile.get("quota", 1000)
    remaining_pool = max_quota - consumed
    raw_token = user_profile.get("api_key", "Unavailable")

    col1, col2, col3 = st.columns(3)
    col1.metric("API Consumption (Total)", f"{consumed:,} / {max_quota:,}")
    col2.metric("Remaining Token Balance", f"{max(0, remaining_pool):,}")
    col3.metric("Deployment Allocation State", "ACTIVE" if consumed < max_quota else "QUOTA EXCEEDED")
    st.progress(min(1.0, consumed / max_quota) if max_quota else 0.0)

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Refresh Telemetry Metrics", use_container_width=True):
        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    left_col, right_col = st.columns([3, 2])

    with left_col:
        with st.container(border=True):
            st.subheader("Access Token")
            st.caption("Your programmatic identification sequence. Include this string inside the X-API-Key transaction header.")
            st.code(raw_token, language="text")

        with st.container(border=True):
            st.subheader("Account")
            profile_data = {
                "Metric Configuration": ["Identity Domain", "Registration Event Timestamp", "Purchased Volume Quota Limit"],
                "Active Value": [st.session_state.user, user_profile.get("created_at", "N/A"), f"{max_quota:,} requests"],
            }
            st.dataframe(pd.DataFrame(profile_data), use_container_width=True, hide_index=True)

        with st.container(border=True):
            st.subheader("API Architecture Explanation Guide")
            st.markdown("""
            ### How Your Token Works
            Every client profile is provisioned with a dedicated secret cryptographic token linking directly to your paid balance plan.

            ### Authentication Protocol
            To execute requests against the blocklist database, supply this key inside the request metadata:
            * **Header Name:** `X-API-Key`
            * **Header Value:** `YOUR_GENERATED_SECRET`

            ### Quota Control & Enforcement
            * Every valid database response drops your remaining balance by 1 request item.
            * Once balance strikes 0, the server refuses incoming connections automatically, returning an HTTP `403 Forbidden` status code.
            """)

    with right_col:
        with st.container(border=True):
            st.subheader("Ingestion Reference")
            st.caption("The blocklist endpoint requires a Proof-of-Work nonce in addition to your API key — see the flow below.")
            doc_tabs = st.tabs(["cURL", "Python"])
            with doc_tabs[0]:
                st.code(f"""
BASE_URL="http://91.107.157.138:8000"
API_KEY="{raw_token}"

CHALLENGE=$(curl -s -X GET "$BASE_URL/api/pow-challenge" -H "X-API-Key: $API_KEY")
IDENTIFIER=$(echo "$CHALLENGE" | jq -r '.identifier')
DIFFICULTY=$(echo "$CHALLENGE" | jq -r '.difficulty')
TARGET=$(printf '0%.0s' $(seq 1 "$DIFFICULTY"))

NONCE=0
while true; do
  HASH=$(printf '%s%s' "$IDENTIFIER" "$NONCE" | sha256sum | cut -d' ' -f1)
  case "$HASH" in
    "$TARGET"*) break ;;
  esac
  NONCE=$((NONCE + 1))
done

curl -X GET "$BASE_URL/api/threats/blocklist" \\
  -H "X-API-Key: $API_KEY" \\
  -H "X-PoW-Nonce: $NONCE" \\
  -H "Accept: application/json"
                """, language="bash")
                st.caption("Requires `jq`. On macOS use `shasum -a 256` instead of `sha256sum`.")
            with doc_tabs[1]:
                st.code(f"""
import hashlib
import requests

BASE_URL = "http://91.107.157.138:8000"
API_KEY = "{raw_token}"


def get_pow_challenge():
    resp = requests.get(
        f"{{BASE_URL}}/api/pow-challenge",
        headers={{"X-API-Key": API_KEY}},
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json()


def solve_pow(identifier, difficulty):
    target = "0" * difficulty
    counter = 0
    while True:
        nonce = str(counter)
        digest = hashlib.sha256(f"{{identifier}}{{nonce}}".encode()).hexdigest()
        if digest.startswith(target):
            return nonce
        counter += 1


try:
    challenge = get_pow_challenge()
    nonce = solve_pow(challenge["identifier"], challenge["difficulty"])

    headers = {{
        "X-API-Key": API_KEY,
        "X-PoW-Nonce": nonce,
        "Accept": "application/json",
    }}
    response = requests.get(f"{{BASE_URL}}/api/threats/blocklist", headers=headers, timeout=5)
    if response.status_code == 200:
        telemetry = response.json()
        print(f"Ingested active threats successfully.")
    elif response.status_code == 403:
        print("Access denied or quota allocation exceeded.")
    else:
        print(f"Request failed ({{response.status_code}}): {{response.text}}")
except Exception as e:
    print(f"Ingestion failed: {{e}}")
                """, language="python")


if nav == "Intelligence Node":
    render_intelligence_node()
elif nav == "Alarm Logs":
    render_alarm_logs()
elif nav == "Retaliation Node":
    render_retaliation_node()
elif nav == "Contact Messages":
    render_contact_messages()
elif nav == "Alarm Controls":
    render_alarm_controls()
elif nav == "Developer Portal":
    render_developer_portal()
