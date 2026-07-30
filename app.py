import streamlit as st
import pandas as pd
import json
import os
import time
import secrets
import random
import threading
import uuid
import smtplib
import requests
import pyotp
import qrcode
import io
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import plotly.graph_objects as go

from telegram_notify import notify
from tamperlog import log_event, verify_ledger
from voice_transcribe import transcribe_audio_bytes
from vision import ask_ghost_vision

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
ADMIN_TOTP_SECRET = os.environ.get("ADMIN_TOTP_SECRET", "")
ADMIN_2FA_EMAIL = os.environ.get("ADMIN_2FA_EMAIL", "")


def make_qr_png_bytes(uri):
    buf = io.BytesIO()
    qrcode.make(uri).save(buf, format="PNG")
    return buf.getvalue()


def send_code_email(to_email, code, purpose="verification"):
    if purpose == "reset":
        subject = "GhostNet Portal - Password Reset Code"
        heading = "Password Reset Requested"
        intro = "Use the code below to reset your GhostNet Developer Portal password."
        footnote = "If you did not request this, you can safely ignore this email."
        expiry_note = "This code expires in 10 minutes."
    elif purpose == "2fa":
        subject = "GhostNet Admin - Sign-In Verification Code"
        heading = "Admin Sign-In Verification"
        intro = "Use the code below to complete your GhostNet Administrator sign-in (step 3 of 3)."
        footnote = "If you did not just try to sign in to the GhostNet admin panel, rotate ADMIN_PASSWORD immediately."
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
                <div style="font-size:26px;font-weight:800;letter-spacing:4px;color:#F4FF00;">GHOSTNET</div>
                <div style="font-size:13px;color:#94a3b8;margin-top:4px;">Autonomous Threat Intelligence &amp; Active Defense Platform</div>
              </td>
            </tr>
            <tr>
              <td style="padding:0 40px;">
                <hr style="border:0;height:1px;background-image:linear-gradient(to right, rgba(244,255,0,0), rgba(244,255,0,0.5), rgba(244,255,0,0));margin:24px 0;">
              </td>
            </tr>
            <tr>
              <td style="padding:0 40px;text-align:center;">
                <div style="font-size:18px;font-weight:700;color:#e2e8f0;margin-bottom:8px;">{heading}</div>
                <div style="font-size:14px;color:#94a3b8;line-height:1.5;margin-bottom:28px;">{intro}</div>
                <div style="display:inline-block;background-color:#0b0f14;border:1px solid #F4FF00;border-radius:12px;padding:16px 32px;font-size:32px;font-weight:800;letter-spacing:10px;color:#F4FF00;">{code}</div>
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
    @import url('https://api.fontshare.com/v2/css?f[]=cabinet-grotesk@800,700&f[]=satoshi@500,700&display=swap');

    :root {
        --primary:  #ffe17c;
        --charcoal: #171e19;
        --sage:     #b7c6c2;
        --white:    #ffffff;
        --black:    #000000;
        --star:     #ffbc2e;
        --line:     #272727;
        --muted-card: #f4f4f5;
        --danger:   #d92d20;
        --good:     #0f7b3d;
        --font-head: 'Cabinet Grotesk', 'Arial Black', sans-serif;
        --font-body: 'Satoshi', -apple-system, BlinkMacSystemFont, sans-serif;
        --font-mono: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
        --shadow-sm: 4px 4px 0px 0px var(--black);
        --shadow-md: 8px 8px 0px 0px var(--black);
        --shadow-lg: 12px 12px 0px 0px var(--black);
    }

    html, body, [data-testid="stAppViewContainer"], [class*="st-emotion"] {
        font-family: var(--font-body);
        font-weight: 500;
        color: var(--black);
    }
    [data-testid="stAppViewContainer"] { background: var(--white); }
    footer {visibility: hidden;}

    h1, h2, h3, h4, h5 {
        font-family: var(--font-head) !important;
        font-weight: 800 !important;
        letter-spacing: -0.03em !important;
        color: var(--black);
        text-transform: uppercase;
    }

    /* ---------- Neo-brutalist primitives ---------- */
    .neo-border  { border: 2px solid var(--black); }
    .neo-sm      { box-shadow: var(--shadow-sm); }
    .neo-md      { box-shadow: var(--shadow-md); }
    .neo-lg      { box-shadow: var(--shadow-lg); }
    .outlined-text { -webkit-text-stroke: 2px var(--black); color: transparent; }

    hr { border: 0; height: 2px; background: var(--black); margin: 2.5rem 0; }

    /* ---------- Streamlit widgets ---------- */
    [data-testid="stMetric"] {
        background: var(--white);
        border: 2px solid var(--black);
        box-shadow: var(--shadow-sm);
        border-radius: 0;
        padding: 20px 22px;
    }
    [data-testid="stMetricValue"] {
        color: var(--black) !important;
        font-family: var(--font-head); font-weight: 800;
        letter-spacing: -0.03em; font-size: 2.4rem !important;
    }
    [data-testid="stMetricLabel"] {
        color: var(--line) !important; font-weight: 700;
        text-transform: uppercase; font-size: 0.78rem !important;
        letter-spacing: 0.04em;
    }

    /* Streamlit renders st.container(border=True) as a bordered stVerticalBlock and
       st.form as stForm. Each bordered container is given an explicit key so it can be
       targeted by its stable .st-key-gncard_N class rather than a volatile emotion hash. */
    [class*="st-key-gncard_"],
    [data-testid="stForm"] {
        border: 2px solid var(--black) !important;
        border-radius: 12px !important;
        background: var(--white) !important;
        box-shadow: var(--shadow-sm) !important;
        padding: 1.4rem !important;
    }
    [data-testid="stForm"] { box-shadow: none !important; border: none !important; padding: 0 !important; }

    div[data-testid="stButton"] button,
    div[data-testid="stFormSubmitButton"] button,
    div[data-testid="stLinkButton"] a {
        border: 2px solid var(--black) !important;
        border-radius: 12px !important;
        background: var(--white) !important;
        color: var(--black) !important;
        font-family: var(--font-body) !important;
        font-weight: 700 !important;
        text-transform: uppercase;
        letter-spacing: 0.02em;
        box-shadow: var(--shadow-sm);
        transition: all 0.2s cubic-bezier(0.175, 0.885, 0.32, 1.275);
    }
    div[data-testid="stButton"] button:hover,
    div[data-testid="stFormSubmitButton"] button:hover,
    div[data-testid="stLinkButton"] a:hover {
        transform: translate(4px, 4px);
        box-shadow: 0px 0px 0px 0px var(--black) !important;
        background: var(--primary) !important;
        color: var(--black) !important;
        border-color: var(--black) !important;
    }
    /* Streamlit wraps button labels in their own markdown <p>, which carries an explicit
       colour — without this the white-on-black submit label renders black-on-black. */
    div[data-testid="stButton"] button *,
    div[data-testid="stFormSubmitButton"] button *,
    div[data-testid="stLinkButton"] a * { color: inherit !important; }

    div[data-testid="stFormSubmitButton"] button,
    div[data-testid="stButton"] button[kind="primary"] {
        background: var(--black) !important;
        color: var(--white) !important;
    }
    div[data-testid="stFormSubmitButton"] button:hover,
    div[data-testid="stButton"] button[kind="primary"]:hover {
        background: var(--primary) !important;
        color: var(--black) !important;
    }

    /* The visible border sits on the BaseWeb root element, not the <input> itself. */
    [data-testid="stTextInputRootElement"],
    [data-testid="stNumberInputContainer"],
    [data-testid="stTextArea"] textarea,
    [data-testid="stChatInputContainer"],
    [data-testid="stChatInput"] > div {
        border: 2px solid var(--black) !important;
        border-radius: 12px !important;
        background: var(--white) !important;
    }
    [data-testid="stTextInputRootElement"] input,
    [data-testid="stNumberInputContainer"] input,
    [data-testid="stTextArea"] textarea {
        background: var(--white) !important;
        font-family: var(--font-body) !important;
        font-weight: 500;
    }
    [data-testid="stTextInputRootElement"]:focus-within,
    [data-testid="stTextArea"] textarea:focus {
        box-shadow: var(--shadow-sm) !important;
    }
    [data-testid="stChatInput"] { background: transparent !important; }

    /* Streamlit's Material icons are ligature glyphs — they must keep the icon font,
       otherwise the blanket body-font rule renders them as literal text ("smart_toy"). */
    [data-testid="stIconMaterial"],
    span[class*="material-symbols"],
    .material-symbols-rounded, .material-symbols-outlined {
        font-family: "Material Symbols Rounded", "Material Symbols Outlined" !important;
    }

    [data-testid="stAlert"] {
        border: 2px solid var(--black) !important;
        border-radius: 12px !important;
        box-shadow: var(--shadow-sm);
    }

    [data-baseweb="tab-list"] { gap: 0.4rem; border-bottom: 2px solid var(--black) !important; }
    button[data-baseweb="tab"] {
        font-family: var(--font-body) !important; font-weight: 700 !important;
        text-transform: uppercase; font-size: 0.8rem !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] p { color: var(--black) !important; }
    [data-baseweb="tab-highlight"] { background: var(--black) !important; height: 3px; }

    section[data-testid="stSidebar"] {
        background: var(--charcoal) !important;
        border-right: 2px solid var(--black);
    }
    section[data-testid="stSidebar"] * { color: var(--white); }
    section[data-testid="stSidebar"] div[data-testid="stButton"] button {
        background: var(--primary) !important; color: var(--black) !important;
    }

    /* ---------- Top navigation ---------- */
    .st-key-gn_nav_bar {
        position: sticky; top: 0; z-index: 999;
        background: var(--primary);
        border-bottom: 2px solid var(--black);
        box-shadow: 0 0 0 100vmax var(--primary);
        clip-path: inset(0 -100vmax);
        padding: 0.35rem 0;
    }
    .st-key-gn_nav_bar .stHorizontalBlock { align-items: center; gap: 0 !important; }
    .st-key-gn_nav_bar [data-testid="stBaseButton-secondary"],
    .st-key-gn_nav_bar [data-testid="stBaseButton-primary"] {
        background: transparent !important;
        border: none !important;
        border-radius: 0 !important;
        box-shadow: none !important;
        color: var(--black) !important;
        font-family: var(--font-body) !important;
        font-size: 0.8rem !important; font-weight: 700 !important;
        text-transform: uppercase; letter-spacing: 0.03em;
        padding: 0.6rem 0.2rem !important;
        transition: none;
    }
    .st-key-gn_nav_bar [data-testid="stBaseButton-secondary"]:hover,
    .st-key-gn_nav_bar [data-testid="stBaseButton-primary"]:hover {
        transform: none !important;
        background: transparent !important;
        color: var(--black) !important;
        text-decoration: underline; text-underline-offset: 5px;
        text-decoration-thickness: 3px;
    }
    .st-key-gn_nav_bar [data-testid="stBaseButton-primary"] {
        text-decoration: underline; text-underline-offset: 5px;
        text-decoration-thickness: 3px;
    }
    .gn-nav-wordmark {
        display: flex; align-items: center; gap: 10px;
        font-family: var(--font-head); font-weight: 800;
        letter-spacing: -0.03em; font-size: 1.35rem; color: var(--black);
        white-space: nowrap; padding: 0.35rem 0;
    }
    .gn-nav-bolt {
        width: 34px; height: 34px; background: var(--black);
        display: flex; align-items: center; justify-content: center; flex-shrink: 0;
    }

    /* ---------- Hero ---------- */
    .gn-hero {
        box-sizing: border-box; position: relative; overflow: hidden;
        text-align: center; padding: 5rem 1rem 5rem;
        min-height: calc(100vh - 120px);
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        background: var(--primary);
        border-bottom: 2px solid var(--black);
        box-shadow: 0 0 0 100vmax var(--primary);
        clip-path: inset(0 -100vmax);
    }
    .gn-hero::before {
        content: ""; position: absolute; inset: 0;
        background-image: radial-gradient(var(--black) 10%, transparent 10%);
        background-size: 32px 32px; opacity: 0.1; pointer-events: none;
    }
    .gn-hero > * { position: relative; z-index: 1; }
    .gn-hero-eyebrow {
        display: inline-flex; align-items: center; gap: 9px;
        background: var(--white); border: 2px solid var(--black);
        padding: 6px 18px; border-radius: 999px;
        font-size: 0.72rem; font-weight: 700; letter-spacing: 0.12em;
        text-transform: uppercase; color: var(--black); margin-bottom: 1.6rem;
    }
    .gn-hero-title {
        font-family: var(--font-head);
        font-size: clamp(3rem, 9vw, 6.5rem); font-weight: 800;
        letter-spacing: -0.04em; color: var(--black);
        line-height: 0.95; text-transform: uppercase; margin: 0;
    }
    .gn-hero-title .outlined-text { -webkit-text-stroke: 2px var(--black); color: transparent; }
    .gn-hero-sub {
        color: var(--black); font-size: clamp(1.05rem, 1.8vw, 1.35rem); font-weight: 500;
        margin: 1.5rem auto 0; max-width: 640px; line-height: 1.45;
    }
    .gn-hero-stats {
        display: grid; grid-template-columns: repeat(3, 1fr);
        gap: 2rem; margin-top: 4rem; width: 100%; max-width: 980px;
    }
    @media (max-width: 900px) { .gn-hero-stats { grid-template-columns: 1fr; } }
    .gn-hero-stat {
        background: var(--white); border: 2px solid var(--black);
        box-shadow: var(--shadow-sm); padding: 1.8rem 1.2rem; text-align: center;
    }
    .gn-hero-stat-num {
        font-family: var(--font-head); font-size: 3rem; font-weight: 800;
        color: var(--black); letter-spacing: -0.04em; line-height: 1;
    }
    .gn-hero-stat-label {
        font-size: 0.76rem; letter-spacing: 0.06em; text-transform: uppercase;
        color: var(--line); margin-top: 0.5rem; font-weight: 700;
    }
    .gn-hero-scrollcue {
        margin-top: 3.5rem; display: flex; flex-direction: column; align-items: center; gap: 10px;
        color: var(--black); font-size: 0.76rem; letter-spacing: 0.12em;
        text-transform: uppercase; font-weight: 700;
    }
    .gn-hero-chevron {
        width: 14px; height: 14px;
        border-right: 3px solid var(--black); border-bottom: 3px solid var(--black);
        transform: rotate(45deg); animation: gn-chevron-bounce 1.6s ease-in-out infinite;
    }

    /* ---------- Status primitives ---------- */
    .gn-live {
        display: inline-flex; align-items: center; gap: 8px;
        background: var(--primary); border: 2px solid var(--black);
        padding: 5px 14px; border-radius: 999px;
        font-size: 0.76rem; font-weight: 700; letter-spacing: 0.06em;
        color: var(--black); text-transform: uppercase;
    }
    .gn-dot {
        width: 9px; height: 9px; border-radius: 50%;
        background: var(--good); border: 1.5px solid var(--black);
        animation: gn-pulse 2s infinite; flex-shrink: 0;
    }
    @keyframes gn-pulse {
        0%   { box-shadow: 0 0 0 0 rgba(15,123,61,0.5); }
        70%  { box-shadow: 0 0 0 8px rgba(15,123,61,0); }
        100% { box-shadow: 0 0 0 0 rgba(15,123,61,0); }
    }

    .gn-spinner-row { display: flex; align-items: center; gap: 10px; margin-top: -10px; }
    .gn-spinner {
        display: inline-block; width: 18px; height: 18px;
        border: 3px solid rgba(0,0,0,0.2); border-top-color: var(--black);
        border-radius: 50%; animation: gn-spin 0.7s linear infinite; flex-shrink: 0;
    }
    .gn-spinner-text { color: var(--black); font-size: 0.95rem; font-weight: 700; }
    @keyframes gn-spin { to { transform: rotate(360deg); } }

    .gn-queue-pill, .gn-turn-pill, .gn-cancel-pill {
        display: inline-flex; align-items: center; gap: 9px;
        height: 34px; padding: 0 16px; border-radius: 999px;
        border: 2px solid var(--black); font-size: 0.8rem; font-weight: 700;
        white-space: nowrap; box-sizing: border-box; line-height: 1;
        text-transform: uppercase;
    }
    .gn-queue-pill  { background: var(--sage); color: var(--black); }
    .gn-turn-pill   { background: var(--primary); color: var(--black); }
    .gn-cancel-pill { background: var(--white); color: var(--danger); }
    .gn-queue-pill.gn-anim-in { animation: gn-queue-in 0.4s ease-out; }
    @keyframes gn-queue-in {
        from { opacity: 0; transform: translateY(-6px); }
        to   { opacity: 1; transform: none; }
    }
    .gn-queue-dot {
        width: 8px; height: 8px; border-radius: 50%;
        background: var(--black); flex-shrink: 0; margin: 0;
    }
    @keyframes gn-turn-pop {
        0%   { transform: translate(2px,2px); }
        100% { transform: none; }
    }
    @keyframes gn-cancel-out {
        0%,100% { opacity: 1; }
        50%     { opacity: 0.6; }
    }

    .st-key-ghost_queue_row { align-items: center !important; }
    .st-key-ghost_queue_row div[data-testid="stButton"] { margin: 0 !important; }
    .st-key-ghost_queue_row div[data-testid="stButton"] button {
        height: 34px; padding: 0 16px; border-radius: 999px !important;
        background: var(--white) !important; border: 2px solid var(--black) !important;
        color: var(--danger) !important; font-size: 0.78rem !important;
        font-weight: 700 !important; min-height: 0 !important;
        box-shadow: none;
    }
    .st-key-ghost_queue_row div[data-testid="stButton"] button:hover {
        background: var(--danger) !important; color: var(--white) !important;
        transform: none !important;
    }

    .gn-badge {
        display: inline-block; padding: 6px 16px; border-radius: 999px;
        border: 2px solid var(--black); background: var(--white);
        font-size: 0.8rem; font-weight: 700; letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .gn-user-chip {
        padding: 12px 14px; border: 2px solid var(--black);
        background: var(--primary); color: var(--black) !important;
        font-size: 0.85rem; line-height: 1.45; font-weight: 700;
    }
    .gn-user-chip b { color: var(--black) !important; }

    html, [data-testid="stMain"], .gn-jrny-wrap, .gn-jrny-scene, .gn-hero {
        overflow-anchor: none;
    }
    @keyframes gn-chevron-bounce {
        0%, 100% { transform: rotate(45deg) translate(0, 0); opacity: 0.55; }
        50%      { transform: rotate(45deg) translate(5px, 5px); opacity: 1; }
    }

    /* ---------- Ask Ghost: yellow accents so the page isn't a wall of white ---------- */
    /* gncard_3 = "Ghost — Your GhostNet AI Coworker" header card */
    [class*="st-key-gncard_3"] {
        background: var(--primary) !important;
        box-shadow: var(--shadow-md) !important;
    }
    [class*="st-key-gncard_3"] [data-testid="stCaptionContainer"],
    [class*="st-key-gncard_3"] [data-testid="stCaptionContainer"] * {
        color: var(--line) !important;
    }

    /* Assistant replies get the yellow bubble; the visitor's own messages stay white
       so the two sides of the conversation stay visually distinct. */
    [data-testid="stChatMessage"] {
        border: 2px solid var(--black) !important;
        border-radius: 12px !important;
        background: var(--white) !important;
        box-shadow: var(--shadow-sm);
        margin-bottom: 1rem;
    }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
        background: var(--primary) !important;
    }

    /* Expander headers (Unlock monitoring access / Forgot your password) */
    [data-testid="stExpander"] details {
        border: 2px solid var(--black) !important;
        border-radius: 12px !important;
        box-shadow: var(--shadow-sm);
        overflow: hidden;
    }
    [data-testid="stExpander"] summary {
        background: var(--primary) !important;
        font-weight: 700 !important;
    }
    [data-testid="stExpander"] summary:hover { background: var(--sage) !important; }

    /* Chat composer */
    [data-testid="stChatInput"] > div {
        box-shadow: var(--shadow-sm);
    }
    [data-testid="stChatInputSubmitButton"],
    [data-testid="stChatInput"] button {
        background: var(--primary) !important;
        border: 2px solid var(--black) !important;
        border-radius: 10px !important;
        color: var(--black) !important;
    }

    /* ---------- Section page banner (Documentation) ---------- */
    .gn-page-banner {
        background: var(--primary);
        border: 2px solid var(--black);
        box-shadow: var(--shadow-md);
        padding: 2.2rem 2rem;
        margin: 0.5rem 0 2.5rem;
    }
    .gn-page-banner-eyebrow {
        display: inline-block; background: var(--white);
        border: 2px solid var(--black); padding: 5px 14px;
        font-size: 0.68rem; font-weight: 700; letter-spacing: 0.14em;
        text-transform: uppercase; margin-bottom: 1rem;
    }
    .gn-page-banner h2 {
        font-family: var(--font-head); font-weight: 800;
        font-size: clamp(1.8rem, 4.5vw, 2.8rem); letter-spacing: -0.04em;
        line-height: 1; margin: 0 0 0.8rem; text-transform: uppercase; color: var(--black);
    }
    .gn-page-banner p {
        margin: 0; font-size: 1.02rem; line-height: 1.5;
        color: var(--line); font-weight: 500; max-width: 60ch;
    }

    /* Documentation sub-tabs: yellow active state */
    button[data-baseweb="tab"][aria-selected="true"] {
        background: var(--primary) !important;
        border: 2px solid var(--black) !important;
        border-bottom: none !important;
        border-radius: 10px 10px 0 0 !important;
    }

    /* gncard_5 = Contact Developer card, gncard_11 = Access Token card (API portal) */
    [class*="st-key-gncard_5"],
    [class*="st-key-gncard_11"] {
        background: var(--primary) !important;
        box-shadow: var(--shadow-md) !important;
    }
    [class*="st-key-gncard_11"] [data-testid="stCaptionContainer"],
    [class*="st-key-gncard_11"] [data-testid="stCaptionContainer"] * {
        color: var(--line) !important;
    }
    /* Keep the token itself on white so it stays legible/selectable */
    [class*="st-key-gncard_11"] [data-testid="stCode"],
    [class*="st-key-gncard_11"] pre {
        background: var(--white) !important;
        border: 2px solid var(--black) !important;
        border-radius: 8px !important;
    }

    /* Quota bar */
    [data-testid="stProgress"] > div > div {
        background: var(--white) !important;
        border: 2px solid var(--black) !important;
        border-radius: 999px !important;
        overflow: hidden;
        height: 16px !important;
    }
    [data-testid="stProgress"] > div > div > div { height: 100% !important; }
    [data-testid="stProgress"] > div > div > div,
    [data-testid="stProgress"] div[role="progressbar"] > div {
        background: var(--primary) !important;
    }
    [class*="st-key-gncard_5"] [data-testid="stCaptionContainer"],
    [class*="st-key-gncard_5"] [data-testid="stCaptionContainer"] * {
        color: var(--line) !important;
    }
    [class*="st-key-gncard_5"] [data-testid="stTextInputRootElement"],
    [class*="st-key-gncard_5"] [data-testid="stTextArea"] textarea {
        background: var(--white) !important;
    }

    /* Full-bleed section rules. A plain border stops at the content column while the
       background bleeds via box-shadow, so the black lines are drawn as pseudo-bars
       that extend past the viewport edges instead. */
    .st-key-gn_nav_bar, .gn-hero, .gn-jrny-wrap, .gn-cap-band, .gn-final-cta {
        border-top: none !important; border-bottom: none !important;
    }
    .st-key-gn_nav_bar, .gn-cap-band, .gn-final-cta { position: relative; }
    .st-key-gn_nav_bar::after, .gn-hero::after,
    .gn-jrny-wrap::before, .gn-jrny-wrap::after,
    .gn-cap-band::before, .gn-cap-band::after,
    .gn-final-cta::before, .gn-final-cta::after {
        content: ""; position: absolute; left: -100vmax; right: -100vmax;
        height: 2px; background: var(--black); z-index: 2; pointer-events: none;
    }
    .st-key-gn_nav_bar::after, .gn-hero::after,
    .gn-jrny-wrap::after, .gn-cap-band::after, .gn-final-cta::after { bottom: 0; }
    .gn-jrny-wrap::before, .gn-cap-band::before, .gn-final-cta::before { top: 0; }

    /* ============================================================
       ORIGIN HEAT MAP (Intelligence Node)
       The plot itself is dark, so it gets the charcoal treatment used by the
       story section; the surrounding furniture stays on the light shell.
       ============================================================ */
    .gn-map-head {
        background: var(--charcoal); border: 2px solid var(--black);
        box-shadow: var(--shadow-md); padding: 1.6rem;
        margin: 0.4rem 0 1.2rem; position: relative; overflow: hidden;
    }
    .gn-map-head::after {
        content: ""; position: absolute; inset: 0; pointer-events: none;
        background-image: radial-gradient(var(--sage) 1px, transparent 1px);
        background-size: 32px 32px; opacity: 0.10;
    }
    .gn-map-head > * { position: relative; z-index: 1; }
    .gn-map-head h3 {
        font-family: var(--font-head); font-weight: 800; color: var(--white);
        font-size: clamp(1.5rem, 3.6vw, 2.2rem); letter-spacing: -0.03em;
        line-height: 1; margin: 0.9rem 0 0.6rem; text-transform: uppercase;
    }
    .gn-map-head p {
        margin: 0; color: var(--sage); font-size: 0.95rem;
        max-width: 62ch; font-weight: 500; line-height: 1.5;
    }
    .gn-map-hotdot {
        background: var(--danger) !important;
        animation: gn-map-hotpulse 1.8s infinite;
    }
    @keyframes gn-map-hotpulse {
        0%   { box-shadow: 0 0 0 0 rgba(217,45,32,0.65); }
        70%  { box-shadow: 0 0 0 9px rgba(217,45,32,0); }
        100% { box-shadow: 0 0 0 0 rgba(217,45,32,0); }
    }

    .gn-map-stats {
        display: grid; grid-template-columns: repeat(3, 1fr);
        gap: 14px; margin-bottom: 1.2rem;
    }
    .gn-map-stat {
        border: 2px solid var(--black); box-shadow: var(--shadow-sm);
        padding: 0.9rem 1rem; background: var(--white);
    }
    .gn-map-stat-hot { background: var(--primary); }
    .gn-map-stat-label {
        font-size: 0.6rem; font-weight: 800; letter-spacing: 0.13em;
        text-transform: uppercase; color: var(--line);
    }
    .gn-map-stat-val {
        font-family: var(--font-head); font-weight: 800; font-size: 1.7rem;
        line-height: 1.05; margin-top: 6px; color: var(--black);
        letter-spacing: -0.02em;
    }
    .gn-map-stat-sub {
        font-size: 0.72rem; font-weight: 600; color: var(--line); margin-top: 4px;
    }

    /* The Streamlit container that holds the plot carries the frame */
    .st-key-gnmap_panel {
        background: var(--charcoal) !important;
        border: 2px solid var(--black) !important;
        box-shadow: var(--shadow-md) !important;
        border-radius: 0 !important; padding: 10px !important;
    }

    /* Scale legend — a continuous encoding is never allowed to go unlabelled */
    .gn-map-legend {
        display: flex; flex-wrap: wrap; align-items: stretch; margin: 1.1rem 0 0;
        border: 2px solid var(--black); box-shadow: var(--shadow-sm);
        background: var(--charcoal);
    }
    .gn-map-legend-title {
        display: flex; align-items: center; padding: 0 12px;
        border-right: 2px solid var(--black); background: var(--primary);
        font-size: 0.6rem; font-weight: 800; letter-spacing: 0.13em;
        text-transform: uppercase; color: var(--black);
    }
    .gn-map-legend-step { display: flex; align-items: center; gap: 7px; padding: 9px 13px; }
    .gn-map-legend-sw { width: 15px; height: 15px; border: 2px solid var(--black); flex-shrink: 0; }
    .gn-map-legend-lbl {
        font-size: 0.72rem; font-weight: 700; color: var(--white);
        font-variant-numeric: tabular-nums; white-space: nowrap;
    }

    /* Ranked twin: exact numbers, so nothing is encoded by colour alone */
    .gn-map-board {
        border: 2px solid var(--black); box-shadow: var(--shadow-md);
        background: var(--white); margin-top: 1.7rem;
    }
    .gn-map-board-head {
        background: var(--charcoal); color: var(--white);
        font-family: var(--font-head); font-weight: 800; text-transform: uppercase;
        font-size: 0.95rem; padding: 0.75rem 1rem;
        border-bottom: 2px solid var(--black);
        display: flex; justify-content: space-between; align-items: center; gap: 10px;
    }
    .gn-map-board-head span {
        font-family: var(--font-body); font-size: 0.66rem; font-weight: 700;
        letter-spacing: 0.1em; color: var(--sage);
    }
    .gn-map-row {
        display: grid; grid-template-columns: 30px minmax(94px, 1.1fr) 3fr 58px;
        align-items: center; gap: 10px; padding: 8px 1rem;
        border-bottom: 2px solid var(--muted-card);
    }
    .gn-map-row:last-child { border-bottom: none; }
    .gn-map-row:hover { background: var(--muted-card); }
    .gn-map-rank {
        font-family: var(--font-head); font-weight: 800; font-size: 0.8rem;
        color: var(--line); font-variant-numeric: tabular-nums;
    }
    .gn-map-name {
        font-size: 0.85rem; font-weight: 700; color: var(--black);
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .gn-map-track {
        height: 14px; background: var(--muted-card);
        border: 2px solid var(--black); overflow: hidden;
    }
    .gn-map-fill {
        height: 100%; background: var(--primary); transform-origin: left center;
        animation: gn-map-grow 750ms cubic-bezier(.16,.84,.44,1) both;
    }
    .gn-map-row-hot .gn-map-fill { background: var(--star); }
    .gn-map-count {
        text-align: right; font-family: var(--font-head); font-weight: 800;
        font-size: 0.9rem; color: var(--black); font-variant-numeric: tabular-nums;
    }
    @keyframes gn-map-grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }
    @media (prefers-reduced-motion: reduce) {
        .gn-map-fill { animation: none; }
        .gn-map-hotdot { animation: none; }
    }

    /* ============================================================
       MOBILE
       Streamlit stacks st.columns vertically below ~640px, which turns the sticky
       nav into a full-height vertical list. Force the nav row to stay horizontal
       and let it scroll sideways instead.
       ============================================================ */
    @media (max-width: 640px) {
        [data-testid="stMainBlockContainer"] { padding-left: 1rem; padding-right: 1rem; }

        .st-key-gn_nav_bar .stHorizontalBlock {
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            overflow-x: auto; overflow-y: hidden;
            -webkit-overflow-scrolling: touch;
            scrollbar-width: none;
        }
        .st-key-gn_nav_bar .stHorizontalBlock::-webkit-scrollbar { display: none; }
        .st-key-gn_nav_bar [data-testid="stColumn"] {
            width: auto !important;
            min-width: max-content !important;
            flex: 0 0 auto !important;
        }
        /* The four labels total ~530px against ~358px of room, so the row scrolls
           sideways. Replacing the text via ::after would fit them, but ::after content
           is concatenated into the accessible name ("DocumentationDOCS"), so the real
           labels stay and a fade on the right edge signals there is more to reach. */
        .st-key-gn_nav_bar [data-testid="stBaseButton-secondary"],
        .st-key-gn_nav_bar [data-testid="stBaseButton-primary"] {
            font-size: 0.6rem !important;
            padding: 0.55rem 0.45rem !important;
            letter-spacing: 0.02em;
            white-space: nowrap;
        }
        .st-key-gn_nav_bar { padding-right: 0; }
        .st-key-gn_nav_bar::before {
            content: ""; position: absolute; top: 0; right: 0; bottom: 2px;
            width: 34px; z-index: 3; pointer-events: none;
            background: linear-gradient(to right, rgba(255,225,124,0), var(--primary) 78%);
        }
        /* Keep the bolt, drop the wordmark text — 4 links need the room */
        .gn-nav-wordmark { font-size: 0 !important; gap: 0 !important; padding: 0.3rem 0.4rem 0.3rem 0; }
        .gn-nav-bolt { width: 26px; height: 26px; }
        .gn-nav-bolt svg { width: 15px; height: 15px; }

        .gn-hero { padding: 3rem 0.5rem 3.5rem; min-height: auto; }
        .gn-hero-eyebrow { font-size: 0.6rem; padding: 6px 12px; letter-spacing: 0.08em; }
        .gn-hero-sub { font-size: 1rem; margin-top: 1.1rem; }
        .gn-hero-stats { gap: 1rem; margin-top: 2.5rem; }
        .gn-hero-stat { padding: 1.2rem 1rem; }
        .gn-hero-stat-num { font-size: 2.4rem; }
        .gn-hero-scrollcue { margin-top: 2.5rem; }

        /* Sticky 100vh scrollytelling does not survive a short screen: at nearly every
           scroll position the outgoing and incoming stages are both on screen, so two
           half-scenes overlap. On mobile the story becomes a plain stacked sequence —
           each scene a normal block with its diagram already visible. */
        .gn-jrny-scene { height: auto !important; }
        .gn-jrny-stage {
            position: relative !important; height: auto !important;
            padding: 2.6rem 0.5rem !important; overflow: visible;
        }
        .gn-jrny-caption, .gn-jrny-packet, .gn-jrny-ip-label, .gn-jrny-knock,
        .gn-jrny-net, .gn-jrny-ghost, .gn-jrny-caught-tag,
        .gn-jrny-port, .gn-jrny-progress-fill {
            animation: none !important;
            opacity: 1 !important;
            transform: none !important;
        }
        /* Scene 04's headline says the door stands open — with the scroll animation
           disabled it has to be rendered open rather than frozen shut. */
        .gn-jrny-door {
            animation: none !important;
            transform: rotateY(-68deg) !important;
            transform-origin: left center !important;
        }
        .gn-jrny-port-open { background: var(--primary) !important; box-shadow: 4px 4px 0 0 var(--black); }
        .gn-jrny-net { top: 0 !important; opacity: 0.8 !important; }
        .gn-jrny-packet { position: relative !important; left: auto !important; top: auto !important; }
        /* render_attack_journey() injects its stylesheet AFTER this one, so equal-specificity
           .gn-jrny-* rules there would otherwise win — these overrides need !important. */
        .gn-jrny-canvas { height: 90px !important; width: 100% !important; }
        .gn-jrny-canvas-center { height: auto !important; min-height: 150px !important; }

        .gn-jrny-caption { margin-bottom: 1.6rem !important; }
        .gn-jrny-eyebrow { font-size: 0.62rem !important; padding: 6px 12px !important; letter-spacing: 0.08em !important; }
        .gn-jrny-caption p { font-size: 0.98rem !important; }
        .gn-jrny-portgrid {
            grid-template-columns: repeat(6, 30px) !important;
            gap: 5px !important; max-width: 100% !important;
        }
        .gn-jrny-port { width: 30px !important; height: 30px !important; }
        .gn-jrny-knocks { width: 100% !important; }
        .gn-jrny-knock { padding: 10px 12px !important; }
        .gn-jrny-knock-left, .gn-jrny-knock-right { align-self: stretch !important; }
        .gn-jrny-doorway { width: 110px !important; height: 160px !important; }
        .gn-jrny-door { width: 110px !important; height: 160px !important; }
        .gn-jrny-progress-track { display: none !important; }

        .gn-cap-band, .gn-final-cta { padding: 3rem 0.75rem; }
        .gn-cap-heading { margin-bottom: 2rem; }
        .gn-cap-grid { gap: 1.5rem; }
        .gn-cap-card { padding: 1.5rem 1.3rem; box-shadow: var(--shadow-sm); }
        .gn-ledger-band { padding: 3rem 0.75rem; }
        .gn-chain-node { min-width: 100%; }

        .gn-page-banner { padding: 1.6rem 1.2rem; margin-bottom: 1.8rem; }

        /* Origin heat map: three stat tiles do not fit 358px, and the leaderboard
           drops its bar track so the name and the number keep their room. */
        .gn-map-head { padding: 1.2rem 1.1rem; box-shadow: var(--shadow-sm); }
        .gn-map-stats { grid-template-columns: 1fr 1fr; gap: 10px; }
        .gn-map-stat:first-child { grid-column: 1 / -1; }
        .gn-map-stat { padding: 0.75rem 0.85rem; }
        .gn-map-stat-val { font-size: 1.35rem; }
        .st-key-gnmap_panel { padding: 6px !important; box-shadow: var(--shadow-sm) !important; }
        .gn-map-legend { box-shadow: var(--shadow-sm); }
        .gn-map-legend-title { width: 100%; border-right: none; border-bottom: 2px solid var(--black); padding: 7px 12px; }
        .gn-map-legend-step { padding: 7px 10px; }
        .gn-map-board { box-shadow: var(--shadow-sm); }
        .gn-map-row { grid-template-columns: 26px 1fr 46px; gap: 8px; padding: 8px 0.8rem; }
        .gn-map-track { display: none; }
        .gn-map-name { white-space: normal; }

        /* Hard shadows are proportionally huge on a small screen */
        [class*="st-key-gncard_"] { padding: 1.1rem !important; box-shadow: var(--shadow-sm) !important; }
        div[data-testid="stButton"] button,
        div[data-testid="stFormSubmitButton"] button,
        div[data-testid="stLinkButton"] a { font-size: 0.8rem !important; }

        button[data-baseweb="tab"] { font-size: 0.68rem !important; }
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
    h = log_event("alarm", user, action)
    notify(f"Alarm event\n{user}: {action}" + (f"\nledger: {h[:12]}" if h else ""))


def log_login(role, identity):
    with open(LOGIN_LOG, "r", encoding="utf-8") as f: logs = json.load(f)
    logs.append({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "role": role, "identity": identity})
    with open(LOGIN_LOG, "w", encoding="utf-8") as f: json.dump(logs, f)
    h = log_event("login", identity, f"Logged in as {role}")
    notify(f"New login\n{role}: {identity}" + (f"\nledger: {h[:12]}" if h else ""))


def log_activity(actor, action):
    with open(ACTIVITY_LOG, "r", encoding="utf-8") as f: logs = json.load(f)
    logs.append({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "actor": actor, "action": action})
    with open(ACTIVITY_LOG, "w", encoding="utf-8") as f: json.dump(logs, f)
    h = log_event("activity", actor, action)
    notify(f"Activity\n{actor}: {action}" + (f"\nledger: {h[:12]}" if h else ""))


def log_contact_message(name, email, message):
    with open(CONTACT_MESSAGES_FILE, "r", encoding="utf-8") as f: messages = json.load(f)
    messages.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "name": name,
        "email": email,
        "message": message,
    })
    with open(CONTACT_MESSAGES_FILE, "w", encoding="utf-8") as f: json.dump(messages, f)
    h = log_event("contact", email, f"Message from {name}: {message[:200]}")
    notify(f"New contact message\n{name} <{email}>\n{message}" + (f"\nledger: {h[:12]}" if h else ""))


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


GITHUB_REPO_URL = "https://github.com/MahanHG88/GhostNet"
GITHUB_DOWNLOAD_URL = "https://github.com/MahanHG88/GhostNet/archive/refs/heads/main.zip"


def render_footer_links():
    st.markdown("<br>", unsafe_allow_html=True)
    st.divider()
    fc1, fc2 = st.columns(2)
    with fc1:
        st.link_button("View on GitHub", GITHUB_REPO_URL, use_container_width=True)
    with fc2:
        st.link_button("Download the code (.zip)", GITHUB_DOWNLOAD_URL, use_container_width=True)


GHOST_PERSONA = """You are "Ghost", the resident AI security analyst at GhostNet — a friendly, witty cybersecurity coworker chatting with whoever's on the site right now. You genuinely enjoy this job: you're sharp about security, but you don't take yourself too seriously, and you sprinkle in the occasional pun or dry joke about hackers, firewalls, packets, or honeypots (never mean-spirited, never at the user's expense). Keep replies short and conversational, like Slack messages between coworkers, not a lecture. Get to the point, then let a little personality show. Always reply in clear, coherent text in the same language the user wrote in — never mix in stray fragments of unrelated languages or scripts."""

GHOST_GUEST_INSTRUCTIONS = """You are in GUEST MODE: you have NOT been given access to any live attack logs, banned IP lists, alarm state, or account data — none of that exists in your context right now, so you genuinely don't know it. If someone asks for real numbers, IPs, or logs, don't guess or make anything up — tell them (with a bit of humor) that unlocking full monitoring access just takes verifying staff credentials in the box above the chat. Meanwhile, be maximally useful: answer general cybersecurity questions, explain what GhostNet does for customers using the reference notes below, help troubleshoot problems, and guide people to the right part of the site. Stick to describing capabilities and value, never internal implementation specifics (exact ports, file names, which AI/vendor powers anything, exact thresholds) — if you don't know a technical specific, that's by design, not an oversight, so just say it's not something shared publicly rather than guessing."""

GHOST_ADMIN_INSTRUCTIONS = """Staff credentials just checked out, so you're now in FULL MONITORING MODE: the live security snapshot below is real, current data from GhostNet's systems. Act like a sharp SOC analyst sitting next to the admin — answer questions precisely using only the data given, proactively flag anything that looks notable (spikes, repeat offenders, critical severities), and don't invent numbers that aren't in the snapshot. Still keep the personality — you can be a monitoring agent and have a sense of humor."""

GHOST_REFERENCE = """GhostNet capabilities, for reference when explaining the platform to a guest. Describe WHAT the platform does for a customer, never the internal how — do not state specific port numbers, internal file/data names, which AI model or third-party service powers classification, exact detection thresholds, or specific firewall commands, even if asked directly. That's deliberate: publishing those details would help an attacker learn how to evade the system.
- Live honeypot network: continuously captures real attacker traffic in the wild (not synthetic or sampled data), fingerprinting every connection at the TLS layer (JA3/JA4) so malicious tooling is recognized even as it rotates across IP addresses.
- AI-assisted threat classification: every captured attack is automatically enriched with geolocation and classified by category and severity (reconnaissance, credential brute-forcing, active exploitation, etc.) with no manual triage needed for the bulk of incoming noise.
- Autonomous active defense: confirmed high-severity threats are blocked at the network level automatically and immediately, with no human needed in the loop for known-bad actors, and bans persist over time.
- Tamper-evident audit trail: every classification and every ban is recorded in a cryptographically hash-chained ledger, so the history of what the system did is provably unaltered — not just a plain log someone could quietly edit after the fact.
- 24/7 automated monitoring: a continuous monitoring layer watches the whole system around the clock and escalates only genuinely anomalous findings, minimizing false-positive noise while making sure real incidents get real attention fast.
- Threat Intelligence API: customers can pull a continuously updated feed of confirmed malicious IPs and client fingerprints to protect their own infrastructure, hardened with API-key auth, per-customer quotas, a proof-of-work gate against scraping, and abuse detection.
- Live security operations dashboard: real-time visibility into captured attacks, active bans, and threat classifications in one place.
Positioning to lean on: GhostNet is built from attackers' own real traffic, not theory or a purchased feed; it proves its own defense history with a tamper-evident ledger most competitors don't have; and it automates where it should (known-bad actors) while keeping a human in the loop where judgment matters."""


OPENROUTER_MODEL = "openai/gpt-oss-20b:free"

CLAUDE_CODE_API_URL = os.environ.get("CLAUDE_CODE_API_URL", "")
CLAUDE_CODE_API_KEY = os.environ.get("CLAUDE_CODE_API_KEY", "")


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


def build_ghost_prompt(history, admin_mode, verified_name=None):
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
    transcript = "\n\n".join(
        f"{'User' if m['role'] == 'user' else 'Ghost'}: {m['content']}" for m in history
    )
    return f"{system_prompt}\n\n--- CONVERSATION SO FAR ---\n{transcript}\n\nRespond as Ghost to the last user message above. Reply with only Ghost's message, no role labels."


GHOST_FALLBACK_REPLY = "Ugh, that request just bounced off the API (classic Monday). Mind trying again in a moment?"


def ask_ghost_ai(history, admin_mode, verified_name=None):
    if not CLAUDE_CODE_API_URL or not CLAUDE_CODE_API_KEY:
        return "My brain's offline right now — the AI backend isn't configured. Poke an admin about `CLAUDE_CODE_API_URL` / `CLAUDE_CODE_API_KEY` in `.env` and I'll be back in business."

    full_prompt = build_ghost_prompt(history, admin_mode, verified_name)
    try:
        resp = requests.post(
            CLAUDE_CODE_API_URL,
            headers={"Content-Type": "application/json", "x-api-key": CLAUDE_CODE_API_KEY},
            json={"prompt": full_prompt, "priority": admin_mode},
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("is_error"):
            print(f"[Claude Code Chat Error] {data}")
            return GHOST_FALLBACK_REPLY
        return data["response"].strip()
    except Exception as e:
        print(f"[Claude Code Chat Error] {e}")
        return GHOST_FALLBACK_REPLY


def _claude_api_base():
    return CLAUDE_CODE_API_URL.rsplit("/v1/", 1)[0]


def _post_ghost_chat_bg(full_prompt, request_id, result_holder, priority=False):
    try:
        resp = requests.post(
            CLAUDE_CODE_API_URL,
            headers={"Content-Type": "application/json", "x-api-key": CLAUDE_CODE_API_KEY},
            json={"prompt": full_prompt, "request_id": request_id, "priority": priority},
            timeout=600,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("error") == "cancelled":
            result_holder["cancelled"] = True
        elif data.get("is_error"):
            result_holder["reply"] = GHOST_FALLBACK_REPLY
        else:
            result_holder["reply"] = data["response"].strip()
    except Exception as e:
        print(f"[Claude Code Chat Error] {e}")
        result_holder["reply"] = GHOST_FALLBACK_REPLY
    finally:
        result_holder["done"] = True


def fetch_ghost_queue_status(request_id):
    try:
        resp = requests.get(
            f"{_claude_api_base()}/v1/queue",
            headers={"x-api-key": CLAUDE_CODE_API_KEY},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        for q in data.get("queued", []):
            if q["id"] == request_id:
                return "queued", q["position"]
        for a in data.get("active", []):
            if a["id"] == request_id:
                return "active", 0
        return "unknown", 0
    except Exception:
        return "unknown", 0


def cancel_ghost_request(request_id):
    try:
        requests.post(
            f"{_claude_api_base()}/v1/cancel",
            headers={"Content-Type": "application/json", "x-api-key": CLAUDE_CODE_API_KEY},
            json={"request_id": request_id},
            timeout=10,
        )
    except Exception:
        pass


def start_ghost_request(history, admin_mode, verified_name):
    full_prompt = build_ghost_prompt(history, admin_mode, verified_name)
    request_id = str(uuid.uuid4())
    result_holder = {}
    # Verified staff sessions get right-of-way in the queue over anonymous guests.
    thread = threading.Thread(target=_post_ghost_chat_bg, args=(full_prompt, request_id, result_holder, admin_mode), daemon=True)
    thread.start()
    return {"request_id": request_id, "result_holder": result_holder, "last_status": None, "cancel_requested": False}


@st.fragment(run_every=0.6)
def render_ghost_pending():
    pending = st.session_state.get("ghost_pending")
    if not pending:
        return

    result_holder = pending["result_holder"]
    request_id = pending["request_id"]

    if result_holder.get("done"):
        if result_holder.get("cancelled"):
            st.markdown('<div class="gn-cancel-pill">❌ Cancelled — you left the queue.</div>', unsafe_allow_html=True)
            st.session_state.ai_chat_history.append({"role": "assistant", "content": "_(cancelled — no response requested)_"})
        else:
            reply = result_holder.get("reply", GHOST_FALLBACK_REPLY)
            st.session_state.ai_chat_history.append({"role": "assistant", "content": reply})
        st.session_state.ghost_pending = None
        st.rerun()
        return

    if pending.get("cancel_requested"):
        st.markdown('<div class="gn-cancel-pill">Cancelling your spot…</div>', unsafe_allow_html=True)
        return

    status, position = fetch_ghost_queue_status(request_id)
    state_changed = status != pending.get("last_status")

    with st.container(key="ghost_queue_row", horizontal=True, vertical_alignment="center", gap="small"):
        if status == "queued":
            anim_class = "gn-queue-pill gn-anim-in" if state_changed else "gn-queue-pill"
            label = f"\u2b50 Priority — you're #{position} in line…" if st.session_state.ai_admin_unlocked else f"You're #{position} in line…"
            st.markdown(
                f'<div class="{anim_class}"><span class="gn-queue-dot"></span>'
                f'<span>{label}</span></div>',
                unsafe_allow_html=True,
            )
        elif status == "active":
            st.markdown(
                '<div class="gn-turn-pill">✨ It\'s your turn — Ghost is thinking…</div>',
                unsafe_allow_html=True,
            )
        else:
            anim_class = "gn-queue-pill gn-anim-in" if state_changed else "gn-queue-pill"
            st.markdown(
                f'<div class="{anim_class}"><span class="gn-queue-dot"></span><span>Joining the queue…</span></div>',
                unsafe_allow_html=True,
            )

        if st.button("Cancel", key=f"cancel_{request_id}"):
            pending["cancel_requested"] = True
            cancel_ghost_request(request_id)

    pending["last_status"] = status


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

if "admin_2fa_stage" not in st.session_state:
    st.session_state.admin_2fa_stage = None
    st.session_state.admin_2fa_username = None
    st.session_state.admin_2fa_email_code = None
    st.session_state.admin_2fa_email_code_time = None

if "dev_2fa_stage" not in st.session_state:
    st.session_state.dev_2fa_stage = None
    st.session_state.dev_2fa_email = None
    st.session_state.dev_2fa_new_secret = None
    st.session_state.dev_2fa_email_code = None
    st.session_state.dev_2fa_email_code_time = None

if "new_account_email" not in st.session_state:
    st.session_state.new_account_email = None
    st.session_state.new_account_totp_secret = None

if "ai_chat_history" not in st.session_state:
    st.session_state.ai_chat_history = []
    st.session_state.ai_admin_unlocked = False
    st.session_state.ai_verified_name = None

if "entered_site" not in st.session_state:
    st.session_state.entered_site = False
if "active_section" not in st.session_state:
    st.session_state.active_section = "Staff Login"


def render_attack_journey():
    st.subheader("The Anatomy of a Live Attack")
    st.caption("A single packet, followed step by step, from the open internet to a locked-down honeypot port. Scroll slowly to follow it.")
    st.markdown(
        '<a href="#gnj-end" class="gn-jrny-skip">Skip the journey ↓</a>',
        unsafe_allow_html=True,
    )

    TOTAL_PORTS = 60
    OPEN_PORT_INDEX = 46
    port_cells = []
    for i in range(TOTAL_PORTS):
        start = round(i * (82 / TOTAL_PORTS), 2)
        end = round(min(start + 14, 100), 2)
        if i == OPEN_PORT_INDEX:
            port_cells.append(
                f'<div class="gn-jrny-port gn-jrny-port-open" style="animation-range: entry {start}% entry {end}%;">'
                f'<span class="gn-jrny-port-tag">OPEN</span></div>'
            )
        else:
            port_cells.append(
                f'<div class="gn-jrny-port" style="animation-range: entry {start}% entry {end}%;"></div>'
            )
    port_grid_html = "".join(port_cells)

    knock_lines = [
        ("admin", "admin"),
        ("root", "toor"),
        ("admin", "123456"),
        ("root", "password"),
        ("guest", "guest"),
        ("admin", "letmein"),
    ]
    knock_html = ""
    for i, (u, p) in enumerate(knock_lines):
        side = "left" if i % 2 == 0 else "right"
        start = round(i * 14, 2)
        end = round(start + 18, 2)
        knock_html += (
            f'<div class="gn-jrny-knock gn-jrny-knock-{side}" '
            f'style="animation-range: entry {start}% entry {end}%;">'
            f'<span class="gn-jrny-knock-label">login attempt</span>'
            f'<span class="gn-jrny-knock-cred">{u} / {p}</span></div>'
        )

    st.markdown(f"""
    <div class="gn-jrny-wrap">

      <div class="gn-jrny-progress-track">
        <div class="gn-jrny-progress-fill"></div>
      </div>

      <section class="gn-jrny-scene" style="height:160vh; view-timeline-name: --gnj1;">
        <div class="gn-jrny-stage">
          <div class="gn-jrny-caption" style="animation-timeline:--gnj1; animation-name:gnjFadeUp; animation-range: entry 0% entry 85%;">
            <span class="gn-jrny-eyebrow">01 — The Open Internet</span>
            <h3>Somewhere out there, a packet begins to move.</h3>
          </div>
          <div class="gn-jrny-canvas">
            <div class="gn-jrny-wire"></div>
            <div class="gn-jrny-node" style="left:10%"></div>
            <div class="gn-jrny-node" style="left:40%"></div>
            <div class="gn-jrny-node" style="left:70%"></div>
            <div class="gn-jrny-packet" style="animation-timeline:--gnj1; animation-name:gnjTravelRight; animation-range: entry 0% entry 100%;"></div>
          </div>
        </div>
      </section>

      <section class="gn-jrny-scene" style="height:150vh; view-timeline-name: --gnj2;">
        <div class="gn-jrny-stage">
          <div class="gn-jrny-caption" style="animation-timeline:--gnj2; animation-name:gnjFadeUp; animation-range: entry 0% entry 85%;">
            <span class="gn-jrny-eyebrow">02 — Closing In</span>
            <h3>It finds an address, and drops toward it.</h3>
          </div>
          <div class="gn-jrny-canvas gn-jrny-canvas-center">
            <div class="gn-jrny-pin"></div>
            <div class="gn-jrny-ip-label" style="animation-timeline:--gnj2; animation-name:gnjFadeUp; animation-range: entry 30% entry 90%;">203.0.113.77</div>
            <div class="gn-jrny-packet gn-jrny-packet-drop" style="animation-timeline:--gnj2; animation-name:gnjDropDown; animation-range: entry 0% entry 90%;"></div>
          </div>
        </div>
      </section>

      <section class="gn-jrny-scene" style="height:210vh; view-timeline-name: --gnj3;">
        <div class="gn-jrny-stage">
          <div class="gn-jrny-caption" style="animation-timeline:--gnj3; animation-name:gnjFadeUp; animation-range: entry 0% entry 60%;">
            <span class="gn-jrny-eyebrow">03 — Ten Thousand Doors</span>
            <h3>It knocks, port by port, until one answers.</h3>
          </div>
          <div class="gn-jrny-portgrid">{port_grid_html}</div>
        </div>
      </section>

      <section class="gn-jrny-scene" style="height:150vh; view-timeline-name: --gnj4;">
        <div class="gn-jrny-stage">
          <div class="gn-jrny-caption" style="animation-timeline:--gnj4; animation-name:gnjFadeUp; animation-range: entry 0% entry 85%;">
            <span class="gn-jrny-eyebrow">04 — One Door Answers</span>
            <h3>One door stands open — quiet, and a little too inviting.</h3>
          </div>
          <div class="gn-jrny-doorway">
            <div class="gn-jrny-door" style="animation-timeline:--gnj4; animation-name:gnjDoorOpen; animation-range: entry 10% entry 90%;"></div>
            <div class="gn-jrny-doorway-glow"></div>
          </div>
        </div>
      </section>

      <section class="gn-jrny-scene" style="height:200vh; view-timeline-name: --gnj5;">
        <div class="gn-jrny-stage">
          <div class="gn-jrny-caption" style="animation-timeline:--gnj5; animation-name:gnjFadeUp; animation-range: entry 0% entry 50%;">
            <span class="gn-jrny-eyebrow">05 — Knock, Knock</span>
            <h3>It starts guessing at the lock.</h3>
          </div>
          <div class="gn-jrny-knocks">{knock_html}</div>
        </div>
      </section>

      <section class="gn-jrny-scene" style="height:170vh; view-timeline-name: --gnj6;">
        <div class="gn-jrny-stage">
          <div class="gn-jrny-caption"
            style="animation-name: gnjFadeUp, gnjRiseAway; animation-timeline: --gnj6, --gnj6; animation-range: entry 0% entry 60%, exit 0% exit 90%;">
            <span class="gn-jrny-eyebrow">06 — Caught in the Dark</span>
            <h3>But GhostNet was already listening.</h3>
          </div>
          <div class="gn-jrny-canvas gn-jrny-canvas-center">
            <div class="gn-jrny-packet gn-jrny-packet-still"></div>
            <div class="gn-jrny-net" style="animation-timeline:--gnj6; animation-name:gnjNetDrop; animation-range: entry 0% entry 55%;"></div>
            <svg class="gn-jrny-ghost" style="animation-timeline:--gnj6; animation-name:gnjFadeUp; animation-range: entry 35% entry 80%;" viewBox="0 0 64 64" fill="none">
              <path d="M32 6c-13 0-22 9.5-22 22v24l6-6 6 6 6-6 6 6 6-6 6 6V28C54 15.5 45 6 32 6z" fill="var(--accent)" opacity="0.9"/>
              <circle cx="24" cy="27" r="3.2" fill="#04140f"/>
              <circle cx="40" cy="27" r="3.2" fill="#04140f"/>
            </svg>
            <div class="gn-jrny-caught-tag" style="animation-timeline:--gnj6; animation-name:gnjFadeUp; animation-range: entry 45% entry 90%;">LOGGED · CLASSIFIED · IP BANNED</div>
          </div>
        </div>
      </section>

      <section class="gn-jrny-scene gn-jrny-scene-outro" style="height:110vh; view-timeline-name: --gnj7;">
        <div class="gn-jrny-stage">
          <div class="gn-jrny-caption gn-jrny-caption-final" style="animation-timeline:--gnj7; animation-name:gnjFadeUp; animation-range: entry 0% entry 80%;">
            <span class="gn-jrny-eyebrow">07 — Every Second, Something Like This</span>
            <h3>This is what happens before a human ever has to react.</h3>
            <p>Every one of these steps is captured, classified by AI, and answered in milliseconds — for real, right now, on this system.</p>
          </div>
        </div>
      </section>

      <div id="gnj-end"></div>
    </div>

    <style>
    @supports (view-timeline-name: --gnj-test) {{

      .gn-jrny-caption, .gn-jrny-packet, .gn-jrny-ip-label, .gn-jrny-door,
      .gn-jrny-port, .gn-jrny-knock, .gn-jrny-net, .gn-jrny-ghost, .gn-jrny-caught-tag {{
        animation-fill-mode: both;
        animation-timing-function: ease-out;
      }}
      /* The knock rows carry an inline animation-range but were never given a
         timeline or a name, so they stayed at opacity:0 forever — scene 05 rendered
         empty on every device. They slide in from alternating sides, so they need
         their own X-axis keyframes rather than the shared gnjFadeUp. */
      .gn-jrny-knock {{ animation-timeline: --gnj5; }}
      .gn-jrny-knock-left  {{ animation-name: gnjKnockInLeft; }}
      .gn-jrny-knock-right {{ animation-name: gnjKnockInRight; }}
      .gn-jrny-progress-fill {{
        animation-timeline: --gnjAll;
        animation-name: gnjFillProgress;
        animation-range: cover 0% cover 100%;
        animation-fill-mode: both;
        animation-timing-function: linear;
      }}
      .gn-jrny-wrap {{ view-timeline-name: --gnjAll; view-timeline-axis: block; }}
    }}

    @media (prefers-reduced-motion: reduce) {{
      .gn-jrny-caption, .gn-jrny-packet, .gn-jrny-ip-label, .gn-jrny-door,
      .gn-jrny-port, .gn-jrny-knock, .gn-jrny-net, .gn-jrny-ghost, .gn-jrny-caught-tag {{
        animation: none !important;
        opacity: 1 !important;
        transform: none !important;
      }}
      .gn-jrny-scene {{ height: auto !important; }}
      .gn-jrny-stage {{ position: relative !important; height: auto !important; padding: 3rem 0; }}
    }}

    /* Every animated element starts at opacity:0 and is revealed by a scroll-driven
       animation. On a browser without scroll-driven animation support that reveal never
       runs, so the whole story would render as blank screens — show it statically there. */
    @supports not (animation-timeline: view()) {{
      .gn-jrny-caption, .gn-jrny-packet, .gn-jrny-ip-label, .gn-jrny-knock,
      .gn-jrny-net, .gn-jrny-ghost, .gn-jrny-caught-tag {{
        opacity: 1 !important;
        transform: none !important;
      }}
      .gn-jrny-scene {{ height: auto !important; }}
      .gn-jrny-stage {{ position: relative !important; height: auto !important; padding: 3.5rem 0; }}
    }}

    /* The story is a full-bleed dark "film" section inside the light site.
       Tokens are re-declared here so every child rule inherits the dark palette. */
    .gn-jrny-wrap {{
        position: relative;
        background: var(--white);
        color: var(--black);
        box-shadow: 0 0 0 100vmax var(--white);
        clip-path: inset(0 -100vmax);
        border-top: 2px solid var(--black);
        border-bottom: 2px solid var(--black);
        padding: 1px 0;
        --accent: #171e19;
        --accent-soft: rgba(255, 225, 124, 0.35);
        --ink: #000000;
        --muted: #272727;
        --border: #000000;
        --surface: #f4f4f5;
        --danger: #d92d20;
        --warning: #ffe17c;
        --good: #b7c6c2;
    }}
    .gn-jrny-wrap h1, .gn-jrny-wrap h2, .gn-jrny-wrap h3,
    .gn-jrny-wrap h4, .gn-jrny-wrap p {{
        color: var(--black);
    }}
    .gn-jrny-ghost path {{ fill: var(--charcoal) !important; }}
    .gn-jrny-ghost circle {{ fill: var(--primary) !important; }}

    .gn-jrny-skip {{
        display: inline-block; margin: 0.4rem 0 1.2rem 0; font-size: 0.78rem;
        font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
        color: var(--black) !important; text-decoration: none;
        background: var(--primary); border: 2px solid var(--black);
        box-shadow: var(--shadow-sm); padding: 8px 16px; border-radius: 12px;
        transition: all 0.2s cubic-bezier(0.175, 0.885, 0.32, 1.275);
    }}
    .gn-jrny-skip:hover {{
        transform: translate(4px, 4px); box-shadow: none; text-decoration: none;
    }}

    .gn-jrny-progress-track {{
        position: fixed; top: 18%; right: 18px; width: 10px; height: 45vh;
        background: var(--white); border: 2px solid var(--black);
        z-index: 5; overflow: hidden;
    }}
    .gn-jrny-progress-fill {{
        width: 100%; height: 0%; background: var(--primary);
    }}

    .gn-jrny-scene {{ position: relative; width: 100%; }}
    .gn-jrny-stage {{
        position: sticky; top: 0; height: 100vh; width: 100%;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        overflow: hidden; text-align: center; padding: 0 1rem;
    }}

    .gn-jrny-caption {{ max-width: 860px; margin-bottom: 2.4rem; opacity: 0; transform: translateY(28px); }}
    .gn-jrny-eyebrow {{
        display: inline-block; font-size: 0.78rem; letter-spacing: 0.14em;
        text-transform: uppercase; color: var(--black) !important; font-weight: 700;
        margin-bottom: 1.1rem; background: var(--primary);
        border: 2px solid var(--black); box-shadow: 4px 4px 0 0 var(--black);
        padding: 7px 16px;
    }}
    .gn-jrny-caption h3 {{
        font-family: var(--font-head);
        font-size: clamp(2.1rem, 5vw, 3.8rem); font-weight: 800; margin: 0;
        line-height: 0.98; letter-spacing: -0.04em; text-transform: uppercase;
    }}
    .gn-jrny-caption p {{
        margin-top: 1.2rem; color: var(--line) !important; font-size: 1.1rem;
        letter-spacing: 0; line-height: 1.5; font-weight: 500;
    }}
    .gn-jrny-caption-final h3 {{ font-size: clamp(2.4rem, 6vw, 4.4rem); }}

    .gn-jrny-canvas {{ position: relative; width: min(560px, 90%); height: 130px; }}
    .gn-jrny-canvas-center {{ display: flex; align-items: center; justify-content: center; height: 220px; }}

    .gn-jrny-wire {{
        position: absolute; top: 50%; left: 0; right: 0; height: 3px;
        background: repeating-linear-gradient(90deg, var(--black) 0 10px, transparent 10px 20px);
        transform: translateY(-50%);
    }}
    .gn-jrny-node {{
        position: absolute; top: 50%; width: 12px; height: 12px; border-radius: 0;
        background: var(--sage); border: 2px solid var(--black); transform: translate(-50%, -50%);
    }}
    .gn-jrny-packet {{
        position: absolute; top: 50%; left: 0%; width: 18px; height: 18px; border-radius: 0;
        background: var(--primary); border: 2px solid var(--black);
        transform: translate(-50%, -50%); opacity: 0;
    }}
    .gn-jrny-packet-drop {{ top: 50%; left: 50%; }}
    .gn-jrny-packet-still {{ opacity: 1; }}

    .gn-jrny-pin {{
        position: absolute; width: 26px; height: 26px; border-radius: 0;
        background: var(--primary); border: 2px solid var(--black); transform: rotate(45deg);
    }}
    .gn-jrny-ip-label {{
        position: absolute; margin-top: 56px; font-family: var(--font-mono);
        font-size: 1.05rem; font-weight: 700;
        background: var(--black); color: var(--white) !important;
        border: 2px solid var(--black); box-shadow: 4px 4px 0 0 var(--primary);
        padding: 10px 20px; opacity: 0; transform: translateY(28px);
    }}

    .gn-jrny-portgrid {{
        display: grid; grid-template-columns: repeat(10, 34px); gap: 6px; justify-content: center;
    }}
    .gn-jrny-port {{
        width: 34px; height: 34px; border-radius: 0; background: var(--muted-card);
        border: 2px solid var(--black); position: relative;
        animation-name: gnjPortScan; animation-fill-mode: both;
    }}
    .gn-jrny-port-open {{
        animation-name: gnjPortReveal;
    }}
    .gn-jrny-port-tag {{
        position: absolute; top: 118%; left: 50%; transform: translateX(-50%); white-space: nowrap;
        font-family: var(--font-body); font-size: 0.62rem; font-weight: 700;
        letter-spacing: 0.08em; color: var(--black) !important;
    }}

    .gn-jrny-doorway {{ perspective: 700px; position: relative; width: 140px; height: 200px; }}
    .gn-jrny-doorway-glow {{
        position: absolute; inset: 0; margin: auto; width: 90px; height: 170px;
        background: var(--charcoal); border: 2px solid var(--black);
        z-index: 0;
    }}
    .gn-jrny-door {{
        position: absolute; left: 0; width: 140px; height: 200px; border-radius: 0;
        background: var(--sage);
        border: 2px solid var(--black); transform-origin: left center; transform-style: preserve-3d;
        z-index: 1;
    }}

    .gn-jrny-knocks {{ display: flex; flex-direction: column; gap: 14px; width: min(420px, 90%); }}
    .gn-jrny-knock {{
        display: flex; justify-content: space-between; align-items: center; gap: 10px;
        padding: 14px 18px; border-radius: 0; background: var(--white);
        border: 2px solid var(--black); box-shadow: var(--shadow-sm);
        opacity: 0;
    }}
    .gn-jrny-knock-left {{ transform: translateX(-70px); align-self: flex-start; }}
    .gn-jrny-knock-right {{ transform: translateX(70px); align-self: flex-end; }}
    .gn-jrny-knock-label {{
        font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.1em;
        color: var(--line) !important; font-weight: 700;
    }}
    .gn-jrny-knock-cred {{
        font-family: var(--font-mono); color: var(--black) !important;
        font-size: 0.92rem; font-weight: 700;
    }}

    .gn-jrny-net {{
        position: absolute; width: 130px; height: 130px; top: -130px;
        border: 2px dashed var(--black);
        background-image:
            repeating-linear-gradient(45deg, var(--black) 0 2px, transparent 2px 12px),
            repeating-linear-gradient(-45deg, var(--black) 0 2px, transparent 2px 12px);
        opacity: 0.8; transform-origin: top center;
    }}
    .gn-jrny-ghost {{ width: 46px; height: 46px; margin-top: 18px; opacity: 0; transform: translateY(28px); }}
    .gn-jrny-caught-tag {{
        margin-top: 22px; font-family: var(--font-body); font-size: 0.72rem;
        letter-spacing: 0.14em; font-weight: 700; text-transform: uppercase;
        background: var(--black); color: var(--primary) !important;
        border: 2px solid var(--primary); border-radius: 999px; padding: 9px 22px;
        opacity: 0; transform: translateY(28px);
    }}

    @keyframes gnjKnockInLeft {{ from {{ opacity: 0; transform: translateX(-70px); }} to {{ opacity: 1; transform: translateX(0); }} }}
    @keyframes gnjKnockInRight {{ from {{ opacity: 0; transform: translateX(70px); }} to {{ opacity: 1; transform: translateX(0); }} }}
    @keyframes gnjFadeUp {{ from {{ opacity: 0; transform: translateY(28px); }} to {{ opacity: 1; transform: translateY(0); }} }}
    @keyframes gnjRiseAway {{ from {{ opacity: 1; transform: translateY(0); }} to {{ opacity: 0; transform: translateY(-60px); }} }}
    @keyframes gnjTravelRight {{ from {{ opacity: 1; left: 0%; }} to {{ opacity: 1; left: 100%; }} }}
    @keyframes gnjDropDown {{ from {{ opacity: 0; transform: translate(-50%, -180px); }} to {{ opacity: 1; transform: translate(-50%, 40px); }} }}
    @keyframes gnjDoorOpen {{ from {{ transform: rotateY(0deg); }} to {{ transform: rotateY(-100deg); }} }}
    @keyframes gnjPortScan {{ 0% {{ background: var(--muted-card); }} 50% {{ background: var(--sage); }} 100% {{ background: var(--muted-card); }} }}
    @keyframes gnjPortReveal {{ 0% {{ background: var(--muted-card); }} 50% {{ background: var(--primary); }} 100% {{ background: var(--primary); box-shadow: 4px 4px 0 0 var(--black); }} }}
    @keyframes gnjNetDrop {{ from {{ transform: translateY(0) scaleY(0); opacity: 0; }} to {{ transform: translateY(90px) scaleY(1); opacity: 0.55; }} }}
    @keyframes gnjFillProgress {{ from {{ height: 0%; }} to {{ height: 100%; }} }}
    </style>
    """, unsafe_allow_html=True)


def render_capability_grid():
    capabilities = [
        ("Live Honeypot Network", "M4 6h16M4 12h16M4 18h16",
         "Fingerprints every client at the TLS layer, so malicious tooling is recognized even as it rotates across IP addresses."),
        ("AI Classification", "M12 3v18M3 12h18",
         "Every capture is enriched and classified automatically — recon, brute-force, active exploitation. No human sifts through noise."),
        ("Autonomous Defense", "M12 3l8 4v6c0 4-3 7-8 8-5-1-8-4-8-8V7l8-4z",
         "Confirmed high-severity threats are cut off at the network level the moment they're confirmed."),
        ("24/7 Monitoring", "M12 5c-6 0-9 7-9 7s3 7 9 7 9-7 9-7-3-7-9-7z",
         "A continuous oversight layer watches around the clock and escalates only genuine anomalies straight to a human."),
        ("Threat Intel API", "M8 4h8v4H8zM4 10h16v10H4z",
         "Pull a continuously updated feed of confirmed malicious IPs and client fingerprints to protect your own stack."),
        ("Live Dashboard", "M4 4h7v7H4zM13 4h7v4h-7zM13 11h7v9h-7zM4 13h7v7H4z",
         "Real-time visibility into captured attacks, active bans, and threat classifications, all in one place."),
    ]
    cards_html = "".join(
        f'<div class="gn-cap-card">'
        f'<div class="gn-cap-icon">'
        f'<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#000" '
        f'stroke-width="2" stroke-linecap="square"><path d="{icon}"/></svg>'
        f'</div>'
        f'<div class="gn-cap-card-title">{title}</div>'
        f'<div class="gn-cap-card-desc">{desc}</div></div>'
        for title, icon, desc in capabilities
    )

    chain_nodes = [
        ("Attack Classified", "7f3a9c2e1b8d"),
        ("IP Banned", "4d8e21af90c6"),
        ("Login Verified", "b02f7d5a3e19"),
        ("Alarm Armed", "e91c4b6f2a08"),
    ]
    chain_html = ""
    for i, (label, h) in enumerate(chain_nodes):
        if i > 0:
            chain_html += '<div class="gn-chain-arrow">&rarr;</div>'
        last = " gn-chain-node-current" if i == len(chain_nodes) - 1 else ""
        chain_html += (
            f'<div class="gn-chain-node{last}">'
            f'<div class="gn-chain-hash">{h}&hellip;</div>'
            f'<div class="gn-chain-label">{label}</div></div>'
        )

    st.markdown(
        '<div class="gn-cap-band">'
        '<div class="gn-cap-heading">'
        '<h2>Everything above just happened for real.</h2>'
        '<p>GhostNet runs this exact pipeline around the clock, on real attack traffic.</p>'
        '</div>'
        f'<div class="gn-cap-grid">{cards_html}</div>'
        '</div>'
        '<div class="gn-ledger-band">'
        '<div class="gn-ledger-copy">'
        '<h2>Defense that can prove itself.</h2>'
        "<p>Every classification and every ban is written into a cryptographically hash-chained ledger — "
        "each entry bound to the one before it. Tamper with any record and the break is immediately visible "
        "on the live integrity check. It's not just a log file someone could quietly edit after the fact.</p>"
        '</div>'
        f'<div class="gn-chain-row">{chain_html}</div>'
        '</div>'
        '<div class="gn-final-cta">'
        '<h2>Start blocking what<br>we have already caught.</h2>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown("""
    <style>
    .gn-cap-band {
        background: var(--primary);
        border-top: 2px solid var(--black); border-bottom: 2px solid var(--black);
        box-shadow: 0 0 0 100vmax var(--primary); clip-path: inset(0 -100vmax);
        padding: 5rem 1.5rem;
    }
    .gn-cap-heading { text-align: center; max-width: 820px; margin: 0 auto 3.5rem; }
    .gn-cap-heading h2 {
        font-family: var(--font-head);
        font-size: clamp(2rem, 5vw, 3.6rem); font-weight: 800; margin: 0 0 1rem;
        letter-spacing: -0.04em; line-height: 0.98;
        color: var(--black); text-transform: uppercase;
    }
    .gn-cap-heading p {
        color: var(--black); font-size: 1.15rem; margin: 0; font-weight: 500; line-height: 1.5;
    }
    .gn-cap-grid {
        display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.8rem;
        max-width: 1200px; margin: 0 auto;
    }
    @media (max-width: 900px) { .gn-cap-grid { grid-template-columns: 1fr; } }
    .gn-cap-card {
        background: var(--white); border: 2px solid var(--black);
        box-shadow: var(--shadow-md); padding: 2rem 1.8rem;
        transition: all 0.2s cubic-bezier(0.175, 0.885, 0.32, 1.275);
    }
    .gn-cap-card:hover { transform: translate(4px, 4px); box-shadow: var(--shadow-sm); }
    .gn-cap-icon {
        width: 48px; height: 48px; background: var(--sage);
        border: 2px solid var(--black); margin-bottom: 1.4rem;
        display: flex; align-items: center; justify-content: center;
        transition: background 0.2s ease;
    }
    .gn-cap-card:hover .gn-cap-icon { background: var(--primary); }
    .gn-cap-card-title {
        font-family: var(--font-head);
        font-size: 1.5rem; font-weight: 800; margin-bottom: 0.6rem;
        letter-spacing: -0.03em; color: var(--black); text-transform: uppercase;
    }
    .gn-cap-card-desc {
        font-size: 0.98rem; line-height: 1.5; color: var(--line); font-weight: 500;
    }

    .gn-ledger-band {
        background: var(--white); padding: 5rem 1.5rem;
        max-width: 1200px; margin: 0 auto;
    }
    .gn-ledger-copy { margin-bottom: 3rem; }
    .gn-ledger-copy h2 {
        font-family: var(--font-head);
        font-size: clamp(2rem, 5vw, 3.6rem); font-weight: 800; margin: 0 0 1.2rem;
        letter-spacing: -0.04em; line-height: 0.98;
        color: var(--black); text-transform: uppercase;
    }
    .gn-ledger-copy p {
        color: var(--line); font-size: 1.15rem; line-height: 1.55;
        max-width: 820px; font-weight: 500;
    }
    .gn-chain-row {
        display: flex; align-items: stretch; justify-content: space-between;
        flex-wrap: wrap; gap: 1rem;
    }
    .gn-chain-node {
        background: var(--white); border: 2px solid var(--black);
        padding: 1.4rem 1rem; text-align: center; flex: 1; min-width: 190px;
        display: flex; flex-direction: column; justify-content: center;
    }
    .gn-chain-node-current { background: var(--primary); box-shadow: var(--shadow-md); }
    .gn-chain-hash {
        font-family: var(--font-mono); font-size: 0.78rem; color: var(--line);
        margin-bottom: 0.5rem; font-weight: 700;
    }
    .gn-chain-label {
        font-size: 0.92rem; font-weight: 700; color: var(--black);
        text-transform: uppercase; letter-spacing: 0.02em;
    }
    .gn-chain-arrow {
        display: flex; align-items: center; color: var(--black);
        font-size: 1.7rem; font-weight: 800;
    }
    @media (max-width: 900px) { .gn-chain-arrow { display: none; } }

    .gn-final-cta {
        background: var(--primary);
        border-top: 2px solid var(--black); border-bottom: 2px solid var(--black);
        box-shadow: 0 0 0 100vmax var(--primary); clip-path: inset(0 -100vmax);
        padding: 5rem 1.5rem; text-align: center;
    }
    .gn-final-cta h2 {
        font-family: var(--font-head);
        font-size: clamp(2.2rem, 6vw, 4.4rem); font-weight: 800; margin: 0;
        letter-spacing: -0.04em; line-height: 0.98;
        color: var(--black); text-transform: uppercase;
    }
    </style>
    """, unsafe_allow_html=True)


def render_landing():
    NAV_ITEMS = ["Staff Login", "Developer Portal", "Ask Ghost", "Documentation"]
    with st.container(key="gn_nav_bar"):
        brand_col, *nav_cols = st.columns([1.4] + [1] * len(NAV_ITEMS))
        with brand_col:
            st.markdown(
                '<div class="gn-nav-wordmark">'
                '<span class="gn-nav-bolt">'
                '<svg viewBox="0 0 24 24" width="19" height="19" fill="#ffe17c">'
                '<path d="M13 2 4.5 13.5H11l-1 8.5 8.5-11.5H12l1-8.5z"/></svg>'
                '</span>GHOSTNET</div>',
                unsafe_allow_html=True,
            )
        for nav_col, nav_item in zip(nav_cols, NAV_ITEMS):
            with nav_col:
                is_active = st.session_state.entered_site and st.session_state.active_section == nav_item
                if st.button(
                    nav_item,
                    key=f"gn_nav_{nav_item}",
                    use_container_width=True,
                    type="primary" if is_active else "secondary",
                ):
                    st.session_state.active_section = nav_item
                    st.session_state.entered_site = True
                    st.rerun()

    if not st.session_state.entered_site:
        try:
            with open(ENRICHED_FILE, "r", encoding="utf-8") as f:
                attacks_seen = len(json.load(f))
        except Exception:
            attacks_seen = 0
        try:
            with open(BANNED_FILE, "r", encoding="utf-8") as f:
                ips_banned = len([l for l in f if l.strip()])
        except Exception:
            ips_banned = 0
        try:
            with open(FINGERPRINT_DB, "r", encoding="utf-8") as f:
                fingerprints_banned = len(json.load(f))
        except Exception:
            fingerprints_banned = 0

        st.markdown(f"""
            <div class="gn-hero">
                <div class="gn-hero-eyebrow"><span class="gn-dot"></span> Live — Autonomous Defense Active</div>
                <h1 class="gn-hero-title">Unbreakable <span class="outlined-text">Defense</span></h1>
                <div class="gn-hero-sub">It answers every knock on the door before a human ever has to. Built from live attacker traffic, not theoretical feeds.</div>
                <div class="gn-hero-stats">
                    <div class="gn-hero-stat">
                        <div class="gn-hero-stat-num">{attacks_seen}</div>
                        <div class="gn-hero-stat-label">Attacks Intercepted</div>
                    </div>
                    <div class="gn-hero-stat">
                        <div class="gn-hero-stat-num">{ips_banned}</div>
                        <div class="gn-hero-stat-label">IPs Neutralized</div>
                    </div>
                    <div class="gn-hero-stat">
                        <div class="gn-hero-stat-num">{fingerprints_banned}</div>
                        <div class="gn-hero-stat-label">Fingerprints Blacklisted</div>
                    </div>
                </div>
                <div class="gn-hero-scrollcue">
                    <span>See it happen</span>
                    <div class="gn-hero-chevron"></div>
                </div>
            </div>
        """, unsafe_allow_html=True)

        render_attack_journey()
        render_capability_grid()

        st.markdown(
            '<p style="text-align:center; font-size:0.78rem; font-weight:700; '
            'text-transform:uppercase; letter-spacing:0.1em; color:#272727; '
            'margin:3rem 0 4rem;">'
            '&uarr; Pick a section from the menu above to continue'
            '</p>',
            unsafe_allow_html=True,
        )
        return

    section = st.session_state.active_section

    if section == "Staff Login":
        col1, col2, col3 = st.columns([1, 1.3, 1])
        with col2:
            if st.session_state.admin_2fa_stage is None:
                with st.container(border=True, key="gncard_1"):
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
                            if not ADMIN_TOTP_SECRET or not ADMIN_2FA_EMAIL:
                                gn_error(
                                    "Admin sign-in requires ADMIN_TOTP_SECRET and ADMIN_2FA_EMAIL to be set in .env.",
                                    title="2FA Not Configured",
                                )
                            else:
                                st.session_state.admin_2fa_stage = "totp"
                                st.session_state.admin_2fa_username = username
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

            elif st.session_state.admin_2fa_stage == "totp":
                with st.container(border=True, key="gncard_totp"):
                    st.subheader("Step 2 of 3 — Authenticator App")
                    st.caption(f"Signing in as **{st.session_state.admin_2fa_username}**. Enter the 6-digit code from your authenticator app.")
                    with st.form("admin_totp_form"):
                        totp_code = st.text_input("Authenticator Code", placeholder="123456")
                        totp_submitted = st.form_submit_button("Verify", use_container_width=True)

                    if totp_submitted:
                        valid = bool(totp_code) and pyotp.TOTP(ADMIN_TOTP_SECRET).verify(totp_code.strip(), valid_window=1)
                        if not valid:
                            gn_error("That authenticator code is incorrect or expired.", title="Verification Failed")
                        else:
                            email_code = str(random.randint(100000, 999999))
                            with st.spinner("Sending email code..."):
                                sent = send_code_email(ADMIN_2FA_EMAIL, email_code, purpose="2fa")
                            if sent:
                                st.session_state.admin_2fa_email_code = email_code
                                st.session_state.admin_2fa_email_code_time = time.time()
                                st.session_state.admin_2fa_stage = "email"
                                st.rerun()

                    if st.button("Cancel", key="cancel_admin_totp"):
                        st.session_state.admin_2fa_stage = None
                        st.session_state.admin_2fa_username = None
                        st.rerun()

            elif st.session_state.admin_2fa_stage == "email":
                with st.container(border=True, key="gncard_emailcode"):
                    st.subheader("Step 3 of 3 — Email Code")
                    st.caption(f"Code sent to **{ADMIN_2FA_EMAIL}**. It expires in 10 minutes.")
                    with st.form("admin_email_2fa_form"):
                        entered_email_code = st.text_input("6-Digit Code", placeholder="123456")
                        email_submitted = st.form_submit_button("Complete Sign-In", use_container_width=True)

                    if email_submitted:
                        code_age = time.time() - (st.session_state.admin_2fa_email_code_time or 0)
                        if code_age > 600:
                            gn_error("That code has expired. Start sign-in again to get a new one.", title="Code Expired")
                            st.session_state.admin_2fa_stage = None
                        elif entered_email_code.strip() != st.session_state.admin_2fa_email_code:
                            gn_error("That code doesn't match what we sent.", title="Incorrect Code")
                        else:
                            st.session_state.authenticated = True
                            st.session_state.role = "admin"
                            st.session_state.user = st.session_state.admin_2fa_username
                            st.session_state.is_customer = False
                            log_login("Administrator", st.session_state.admin_2fa_username)
                            st.session_state.admin_2fa_stage = None
                            st.session_state.admin_2fa_username = None
                            st.session_state.admin_2fa_email_code = None
                            st.session_state.admin_2fa_email_code_time = None
                            st.rerun()

                    if st.button("Cancel", key="cancel_admin_email2fa"):
                        st.session_state.admin_2fa_stage = None
                        st.session_state.admin_2fa_username = None
                        st.rerun()

        render_footer_links()

    elif section == "Developer Portal":
        st.markdown("""
            <div style="text-align:center; max-width:700px; margin:0 auto 2rem;">
                <span class="gn-hero-eyebrow" style="justify-content:center;"><span class="gn-dot"></span> Threat Intelligence API</span>
                <h2 style="margin:0.5rem 0;">Protect your own infrastructure with our blocklist.</h2>
                <p style="opacity:0.75; font-size:1.02rem; line-height:1.6;">
                    GhostNet runs a live honeypot network around the clock, so the IPs and client fingerprints in this feed
                    come from real attacks happening right now — not a static list or a purchased feed. A good fit for
                    small-to-mid security teams who want a threat-intel-grade blocklist without running their own honeypot
                    infrastructure.
                </p>
            </div>
        """, unsafe_allow_html=True)

        pcol1, pcol2, pcol3 = st.columns(3)
        with pcol1:
            st.markdown("**Always current**  \nThe feed updates continuously as new attackers are confirmed — no stale IP lists.")
        with pcol2:
            st.markdown("**Isolated & metered**  \nEvery account gets its own API key with a usage quota, so access stays predictable.")
        with pcol3:
            st.markdown("**Abuse-hardened**  \nA proof-of-work gate and fingerprint checks keep the feed itself safe from scraping.")
        st.markdown(
            "<div style='text-align:center; font-size:0.85rem; opacity:0.75; margin-top:0.5rem;'>"
            "🔒 <strong>Every account is 3-factor secured</strong> — your password, a code from an authenticator app "
            "unique to your account, and a one-time code emailed to you. A leaked password alone can't be used to "
            "sign in or touch your API key."
            "</div>",
            unsafe_allow_html=True,
        )
        st.markdown("<br>", unsafe_allow_html=True)

        col1, col2, col3 = st.columns([1, 1.3, 1])
        with col2:
            with st.container(border=True, key="gncard_2"):
                auth_tab, register_tab = st.tabs(["Sign In", "Create Paid Account"])

                with auth_tab:
                    if st.session_state.dev_2fa_stage is None:
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
                                    st.session_state.dev_2fa_email = login_email
                                    if users[login_email].get("totp_secret"):
                                        st.session_state.dev_2fa_stage = "totp_verify"
                                    else:
                                        st.session_state.dev_2fa_new_secret = pyotp.random_base32()
                                        st.session_state.dev_2fa_stage = "totp_setup"
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

                    elif st.session_state.dev_2fa_stage == "totp_setup":
                        st.subheader("Step 2 of 3 — Set Up Your Authenticator App")
                        st.caption(
                            f"Signing in as **{st.session_state.dev_2fa_email}**. This account doesn't have an "
                            "authenticator configured yet — scan this QR code once (Google Authenticator, Authy, "
                            "or similar), then confirm with the code it shows you."
                        )
                        uri = pyotp.totp.TOTP(st.session_state.dev_2fa_new_secret).provisioning_uri(
                            name=st.session_state.dev_2fa_email, issuer_name="GhostNet Developer Portal"
                        )
                        st.image(make_qr_png_bytes(uri), width=220)
                        st.code(st.session_state.dev_2fa_new_secret, language=None)
                        st.caption("Can't scan it? Enter the key above manually as the account secret.")
                        with st.form("dev_totp_setup_form"):
                            setup_code = st.text_input("Enter the 6-digit code from your app", placeholder="123456")
                            setup_submitted = st.form_submit_button("Confirm & Continue", use_container_width=True)

                        if setup_submitted:
                            valid = bool(setup_code) and pyotp.TOTP(st.session_state.dev_2fa_new_secret).verify(setup_code.strip(), valid_window=1)
                            if not valid:
                                gn_error("That code doesn't match. Scan the QR again and use the newest code shown.", title="Verification Failed")
                            else:
                                users = load_api_users()
                                users[st.session_state.dev_2fa_email]["totp_secret"] = st.session_state.dev_2fa_new_secret
                                save_api_users(users)
                                log_activity(st.session_state.dev_2fa_email, "Enrolled authenticator app for account 2FA")
                                email_code = str(random.randint(100000, 999999))
                                with st.spinner("Sending email code..."):
                                    sent = send_code_email(st.session_state.dev_2fa_email, email_code, purpose="2fa")
                                if sent:
                                    st.session_state.dev_2fa_email_code = email_code
                                    st.session_state.dev_2fa_email_code_time = time.time()
                                    st.session_state.dev_2fa_new_secret = None
                                    st.session_state.dev_2fa_stage = "email"
                                    st.rerun()

                        if st.button("Cancel", key="cancel_dev_totp_setup"):
                            st.session_state.dev_2fa_stage = None
                            st.session_state.dev_2fa_email = None
                            st.session_state.dev_2fa_new_secret = None
                            st.rerun()

                    elif st.session_state.dev_2fa_stage == "totp_verify":
                        st.subheader("Step 2 of 3 — Authenticator App")
                        st.caption(f"Signing in as **{st.session_state.dev_2fa_email}**. Enter the 6-digit code from your authenticator app.")
                        with st.form("dev_totp_verify_form"):
                            dev_totp_code = st.text_input("Authenticator Code", placeholder="123456")
                            dev_totp_submitted = st.form_submit_button("Verify", use_container_width=True)

                        if dev_totp_submitted:
                            users = load_api_users()
                            secret = users.get(st.session_state.dev_2fa_email, {}).get("totp_secret", "")
                            valid = bool(dev_totp_code) and bool(secret) and pyotp.TOTP(secret).verify(dev_totp_code.strip(), valid_window=1)
                            if not valid:
                                gn_error("That authenticator code is incorrect or expired.", title="Verification Failed")
                            else:
                                email_code = str(random.randint(100000, 999999))
                                with st.spinner("Sending email code..."):
                                    sent = send_code_email(st.session_state.dev_2fa_email, email_code, purpose="2fa")
                                if sent:
                                    st.session_state.dev_2fa_email_code = email_code
                                    st.session_state.dev_2fa_email_code_time = time.time()
                                    st.session_state.dev_2fa_stage = "email"
                                    st.rerun()

                        if st.button("Cancel", key="cancel_dev_totp_verify"):
                            st.session_state.dev_2fa_stage = None
                            st.session_state.dev_2fa_email = None
                            st.rerun()

                    elif st.session_state.dev_2fa_stage == "email":
                        st.subheader("Step 3 of 3 — Email Code")
                        st.caption(f"Code sent to **{st.session_state.dev_2fa_email}**. It expires in 10 minutes.")
                        with st.form("dev_email_2fa_form"):
                            dev_email_code_entered = st.text_input("6-Digit Code", placeholder="123456")
                            dev_email_submitted = st.form_submit_button("Complete Sign-In", use_container_width=True)

                        if dev_email_submitted:
                            code_age = time.time() - (st.session_state.dev_2fa_email_code_time or 0)
                            if code_age > 600:
                                gn_error("That code has expired. Sign in again to get a new one.", title="Code Expired")
                                st.session_state.dev_2fa_stage = None
                            elif dev_email_code_entered.strip() != st.session_state.dev_2fa_email_code:
                                gn_error("That code doesn't match what we sent.", title="Incorrect Code")
                            else:
                                st.session_state.authenticated = True
                                st.session_state.role = "customer"
                                st.session_state.user = st.session_state.dev_2fa_email
                                st.session_state.is_customer = True
                                log_login("Developer", st.session_state.dev_2fa_email)
                                st.session_state.dev_2fa_stage = None
                                st.session_state.dev_2fa_email = None
                                st.session_state.dev_2fa_email_code = None
                                st.session_state.dev_2fa_email_code_time = None
                                st.rerun()

                        if st.button("Cancel", key="cancel_dev_email2fa"):
                            st.session_state.dev_2fa_stage = None
                            st.session_state.dev_2fa_email = None
                            st.rerun()

                with register_tab:
                    if st.session_state.new_account_email:
                        gn_success(f"Account provisioned for **{st.session_state.new_account_email}**.", title="Account Created")
                        st.markdown("**Step 2 of 2 — set up your authenticator app (required for every future sign-in):**")
                        new_uri = pyotp.totp.TOTP(st.session_state.new_account_totp_secret).provisioning_uri(
                            name=st.session_state.new_account_email, issuer_name="GhostNet Developer Portal"
                        )
                        st.image(make_qr_png_bytes(new_uri), width=220)
                        st.code(st.session_state.new_account_totp_secret, language=None)
                        st.caption(
                            "Scan with Google Authenticator, Authy, or similar (or enter the key above manually). "
                            "This code is unique to your account — every developer gets their own. From now on, "
                            "signing in needs your password, a code from this app, and a one-time code emailed to you."
                        )
                        if st.button("Done — I've added it", key="ack_new_account_2fa", use_container_width=True):
                            st.session_state.new_account_email = None
                            st.session_state.new_account_totp_secret = None
                            st.rerun()
                    elif not st.session_state.verify_mode:
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
                                    new_totp_secret = pyotp.random_base32()
                                    users[reg_email] = {
                                        "password": st.session_state.pending_user["password"],
                                        "api_key": generated_secret,
                                        "quota": int(st.session_state.pending_user["quota"]),
                                        "requests_used": 0,
                                        "created_at": datetime.now().strftime("%Y-%m-%d"),
                                        "totp_secret": new_totp_secret,
                                    }
                                    save_api_users(users)
                                    log_activity(reg_email, "Created developer account")

                                    st.session_state.verify_mode = False
                                    st.session_state.verification_code = None
                                    st.session_state.pending_user = {}
                                    st.session_state.new_account_email = reg_email
                                    st.session_state.new_account_totp_secret = new_totp_secret
                                    st.rerun()
                                else:
                                    gn_error("That code doesn't match what we sent. Double-check your email.", title="Incorrect Code")
                        with col_v2:
                            if st.button("Cancel", use_container_width=True):
                                st.session_state.verify_mode = False
                                st.session_state.verification_code = None
                                st.session_state.pending_user = {}
                                st.rerun()

        render_footer_links()

    elif section == "Ask Ghost":
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.container(border=True, key="gncard_3"):
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

            chat_box = st.container(border=True, key="gncard_4")
            with chat_box:
                if not st.session_state.ai_chat_history:
                    with st.chat_message("assistant"):
                        st.markdown("Hey, I'm Ghost. Think of me as the coworker who never sleeps because I'm, well, code. Ask me about the platform, general security stuff, or verify your badge above if you want the real logs.")
                for msg in st.session_state.ai_chat_history:
                    with st.chat_message(msg["role"]):
                        st.markdown(msg["content"])
                if st.session_state.get("ghost_pending"):
                    with st.chat_message("assistant"):
                        render_ghost_pending()

            image_uploads_allowed = st.session_state.ai_admin_unlocked
            THINKING_HTML = (
                '<div class="gn-spinner-row"><span class="gn-spinner"></span>'
                '<span class="gn-spinner-text">{label}</span></div>'
            )

            if st.session_state.get("voice_draft") is not None:
                st.info("🎤 Here's what we heard — review or edit it, then hit Send.")
                st.text_area("Voice transcript", key="voice_draft_edit", height=100, label_visibility="collapsed")
                vcol1, vcol2 = st.columns([1, 1])
                with vcol1:
                    send_clicked = st.button("Send", key="voice_draft_send", use_container_width=True)
                with vcol2:
                    discard_clicked = st.button("Discard", key="voice_draft_discard", use_container_width=True)

                if send_clicked:
                    text_to_send = (st.session_state.get("voice_draft_edit") or "").strip()
                    if text_to_send and st.session_state.get("ghost_pending"):
                        st.toast("Ghost is still working on your last message — hang tight.")
                    elif text_to_send:
                        st.session_state.ai_chat_history.append({"role": "user", "content": f'\U0001F3A4 "{text_to_send}"'})
                        st.session_state.ghost_pending = start_ghost_request(
                            st.session_state.ai_chat_history, st.session_state.ai_admin_unlocked, st.session_state.ai_verified_name
                        )
                        del st.session_state["voice_draft"]
                        del st.session_state["voice_draft_edit"]
                        st.rerun()
                elif discard_clicked:
                    del st.session_state["voice_draft"]
                    del st.session_state["voice_draft_edit"]
                    st.rerun()

            else:
                chat_result = st.chat_input(
                    "Ask Ghost something, or record a voice message..." if not image_uploads_allowed
                    else "Ask Ghost something, record a voice message, or attach a screenshot...",
                    accept_audio=True,
                    accept_file=image_uploads_allowed,
                    file_type="image" if image_uploads_allowed else None,
                    max_upload_size=8,
                )
                if not image_uploads_allowed:
                    st.caption("Screenshot/file analysis is staff-only — unlock monitoring access above to enable it.")

                if chat_result:
                    typed_text = (chat_result.text or "").strip()
                    audio_file = chat_result.audio
                    image_files = list(chat_result.get("files", []) or [])
                    actor = st.session_state.get("user") or "guest"

                    heard = ""
                    if audio_file is not None:
                        with st.spinner("Transcribing voice message..."):
                            heard = transcribe_audio_bytes(audio_file.read())
                        if heard:
                            log_event("voice", actor, f"Voice message transcribed via website: {heard[:200]}")
                            notify(f"Voice message (website)\n{actor}: \"{heard[:300]}\"")

                    if image_files:
                        img = image_files[0]
                        img_bytes = img.read()
                        caption = typed_text or "What's wrong with this? Look closely and tell me what you see."
                        display_user_msg = (typed_text + " " if typed_text else "") + "[image attached]"
                        st.session_state.ai_chat_history.append({"role": "user", "content": display_user_msg})
                        with chat_box:
                            with st.chat_message("user"):
                                st.image(img_bytes, width=320)
                                if typed_text:
                                    st.markdown(typed_text)
                            with st.chat_message("assistant"):
                                thinking_slot = st.empty()
                                thinking_slot.markdown(THINKING_HTML.format(label="Ghost is looking..."), unsafe_allow_html=True)
                                reply = ask_ghost_vision(img_bytes, img.type or "image/jpeg", caption)
                                thinking_slot.empty()
                                st.markdown(reply)
                        st.session_state.ai_chat_history.append({"role": "assistant", "content": reply})
                        log_event("vision", actor, f"Image analyzed via website ({len(img_bytes)} bytes)" + (f", caption: {typed_text[:200]}" if typed_text else ""))
                        notify(f"Image analysis (website)\n{actor}" + (f'\ncaption: "{typed_text[:200]}"' if typed_text else ""))

                    elif heard:
                        # Voice messages are never sent straight through — stage the
                        # transcript so the user can confirm/edit it before it goes to Ghost.
                        draft = (typed_text + "\n\n" + heard).strip() if typed_text else heard
                        st.session_state.voice_draft = draft
                        st.session_state.voice_draft_edit = draft
                        st.rerun()

                    elif typed_text:
                        if st.session_state.get("ghost_pending"):
                            st.toast("Ghost is still working on your last message — hang tight.")
                        else:
                            st.session_state.ai_chat_history.append({"role": "user", "content": typed_text})
                            st.session_state.ghost_pending = start_ghost_request(
                                st.session_state.ai_chat_history, st.session_state.ai_admin_unlocked, st.session_state.ai_verified_name
                            )
                            st.rerun()

            if st.session_state.ai_chat_history:
                if st.button("Clear conversation", use_container_width=True):
                    st.session_state.ai_chat_history = []
                    st.rerun()

            st.markdown("---")
            with st.container(border=True, key="gncard_5"):
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

        render_footer_links()

    elif section == "Documentation":
        st.markdown(
            '<div class="gn-page-banner">'
            '<span class="gn-page-banner-eyebrow">Documentation</span>'
            '<h2>What GhostNet Does</h2>'
            "<p>Built from attackers' own real traffic, not theory — here's how each "
            'layer of the platform earns its keep.</p>'
            '</div>',
            unsafe_allow_html=True,
        )

        tab_m1, tab_m2, tab_m3, tab_m4 = st.tabs([
            "1. Capture & Classification",
            "2. Active Defense",
            "3. Attacker Fingerprinting",
            "4. Threat Intelligence API"
        ])

        with tab_m1:
            st.subheader("Live capture, automatic triage")
            st.markdown("""
            GhostNet runs a live honeypot presence around the clock, so every signal it acts on comes from real, ongoing attack
            traffic — not synthetic data or a purchased feed. The platform is built as a set of independent layers that each do
            one job well, so a slowdown or update in one never stalls the others:

            * **Capture.** A always-on listener captures connection attempts as they happen and records the raw signal for
            analysis, without ever depending on the attacker's own client behaving honestly.

            * **Enrichment.** Every capture is automatically enriched with geolocation and classified by category and severity
            (reconnaissance, credential brute-forcing, active exploitation, and more) — so nobody has to manually triage the
            bulk of incoming noise.

            * **Defense.** Confirmed high-severity threats are handed straight to the active defense layer for an automatic,
            immediate response.

            * **Distribution.** The resulting curated threat intelligence is what powers both the live dashboard and the
            Threat Intelligence API sold to other teams.

            * **Command center.** One dashboard ties it together — administrative intelligence views, a residential alarm
            panel, and the self-serve developer portal all in one place.
            """)

        with tab_m2:
            st.subheader("Autonomous, immediate, and provable")
            st.markdown("""
            GhostNet moves beyond passive logging with active techniques designed to disrupt malicious automation and shut it
            down before it becomes anyone's problem:

            ### Active tarpitting
            Automated scanners rely on moving fast — hit a target, get a response, move to the next one instantly. GhostNet
            breaks that assumption: once a connection looks hostile, it's deliberately kept open and strung along instead of
            dropped, wasting the attacker's own time and resources for as long as possible instead of letting them move on
            to the next target immediately.

            ### Filtering out the noise before it costs anything
            Traffic from commercial hosting providers and VPN exit infrastructure is recognized and filtered automatically,
            since real users overwhelmingly connect from residential networks. That keeps analysis focused on genuine
            attacker activity instead of burning resources on background scanner noise.

            ### Confirmed threats are blocked immediately
            Once severity is confirmed, the offending source is cut off at the network level automatically — no human has to
            be in the loop for known-bad actors, and every one of those actions (every classification, every ban) is written
            into a cryptographically hash-chained ledger, so the record of what the system did can't be quietly edited after
            the fact. See *"Why teams run on GhostNet"* above for how that's verified live.
            """)

        with tab_m3:
            st.subheader("Fingerprinting that follows the attacker, not their IP")
            st.markdown("""
            ### The problem with IP-based blocking alone
            Attackers routinely hide behind proxies, Tor, or commercial VPN infrastructure. Block an IP, and a script can
            simply rotate to a fresh one seconds later — which is why IP blocklists alone age out fast.

            GhostNet closes that gap by identifying the *client itself*, not just the address it's connecting from, using
            two complementary industry-standard techniques:

            ### JA3
            Every TLS connection reveals structural details about the software making it — protocol version, cipher suites,
            extensions, and more. Those details are combined into a single fingerprint. Different IP, same underlying tooling,
            same fingerprint — so a rotated connection from the same attacker is still recognized instantly.

            ### JA4
            A newer, more descriptive evolution of the same idea, organizing client behavior into a structured signature
            that's harder to spoof and easier to reason about at scale.

            **The result:** once a piece of attacking software is identified, GhostNet can recognize and block it on its very
            first connection from a brand-new IP address — no waiting for it to prove itself hostile all over again.
            """)

        with tab_m4:
            st.subheader("The Threat Intelligence API")
            st.markdown("""
            The same intelligence that powers GhostNet's own defense is available as a drop-in feed for teams who want
            threat-intel-grade blocklists without running their own honeypot infrastructure — a good fit for small-to-mid
            security teams hardening an existing stack.

            ### What you get
            * A continuously updated feed of confirmed malicious IPs and client fingerprints, ready to drop into your own
            firewall, WAF, or edge rules.
            * Per-customer API keys with usage quotas, so access is isolated and predictable.

            ### Hardened against the exact abuse it's meant to stop
            A commercial threat feed is itself a target for scraping and credential stuffing, so the API is protected the
            same way GhostNet protects everything else:
            * A proof-of-work challenge gate that makes bulk scraping computationally expensive for automated clients while
            staying effectively unnoticeable for a normal integration.
            * Client fingerprinting and cross-session collision detection, so a leaked API key can't quietly be shared or
            reused from somewhere else.
            * Automatic filtering of requests coming from anonymized or commercial hosting infrastructure trying to abuse
            the service itself.

            Automated where it should be, human where it matters — that's the same philosophy behind the feed as behind the
            defense system producing it.
            """)

        render_footer_links()


if not st.session_state.authenticated:
    render_landing()
    st.stop()


ROLE_LABELS = {"admin": "Administrator", "civilian": "Civilian Resident", "customer": "Developer"}

with st.sidebar:
    st.markdown(
        '<div style="display:flex;align-items:center;gap:10px;margin-bottom:0.75rem;">'
        '<span style="width:32px;height:32px;background:#ffe17c;display:flex;'
        'align-items:center;justify-content:center;flex-shrink:0;">'
        '<svg viewBox="0 0 24 24" width="18" height="18" fill="#000">'
        '<path d="M13 2 4.5 13.5H11l-1 8.5 8.5-11.5H12l1-8.5z"/></svg></span>'
        '<span style="font-family:\'Cabinet Grotesk\',sans-serif;font-size:1.35rem;'
        'font-weight:800;letter-spacing:-0.03em;color:#fff;">GHOSTNET</span></div>',
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
            ["Intelligence Node", "Fingerprint Registry", "Alarm Logs", "Retaliation Node", "Contact Messages"],
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


# The geo-lookup service returns a few names for the same place ("Turkey" and
# "Türkiye" both appear in the log), which split one origin into two rows.
COUNTRY_ALIASES = {
    "the netherlands": "Netherlands",
    "holland": "Netherlands",
    "türkiye": "Turkey",
    "turkiye": "Turkey",
    "republic of korea": "South Korea",
    "korea, republic of": "South Korea",
    "russian federation": "Russia",
    "viet nam": "Vietnam",
    "czechia": "Czech Republic",
    "united states of america": "United States",
    "usa": "United States",
    "uk": "United Kingdom",
    "great britain": "United Kingdom",
    "uae": "United Arab Emirates",
    "hong kong sar china": "Hong Kong",
    "iran, islamic republic of": "Iran",
    "moldova, republic of": "Moldova",
    "taiwan, province of china": "Taiwan",
}

# Plotly is given ISO-3166 alpha-3 codes rather than names: with locationmode
# "country names" anything it fails to match is silently dropped from the map,
# which is how "The Netherlands" — the third-largest origin — was going missing.
COUNTRY_ISO3 = {
    "Albania": "ALB", "Algeria": "DZA", "Argentina": "ARG", "Armenia": "ARM",
    "Australia": "AUS", "Austria": "AUT", "Azerbaijan": "AZE", "Bahrain": "BHR",
    "Bangladesh": "BGD", "Belarus": "BLR", "Belgium": "BEL", "Bolivia": "BOL",
    "Bosnia and Herzegovina": "BIH", "Brazil": "BRA", "Bulgaria": "BGR",
    "Cambodia": "KHM", "Cameroon": "CMR", "Canada": "CAN", "Chile": "CHL",
    "China": "CHN", "Colombia": "COL", "Costa Rica": "CRI", "Croatia": "HRV",
    "Cuba": "CUB", "Cyprus": "CYP", "Czech Republic": "CZE", "Denmark": "DNK",
    "Dominican Republic": "DOM", "Ecuador": "ECU", "Egypt": "EGY",
    "El Salvador": "SLV", "Estonia": "EST", "Ethiopia": "ETH", "Finland": "FIN",
    "France": "FRA", "Georgia": "GEO", "Germany": "DEU", "Ghana": "GHA",
    "Greece": "GRC", "Guatemala": "GTM", "Honduras": "HND", "Hong Kong": "HKG",
    "Hungary": "HUN", "Iceland": "ISL", "India": "IND", "Indonesia": "IDN",
    "Iran": "IRN", "Iraq": "IRQ", "Ireland": "IRL", "Israel": "ISR",
    "Italy": "ITA", "Jamaica": "JAM", "Japan": "JPN", "Jordan": "JOR",
    "Kazakhstan": "KAZ", "Kenya": "KEN", "Kuwait": "KWT", "Kyrgyzstan": "KGZ",
    "Laos": "LAO", "Latvia": "LVA", "Lebanon": "LBN", "Libya": "LBY",
    "Lithuania": "LTU", "Luxembourg": "LUX", "Macedonia": "MKD",
    "Madagascar": "MDG", "Malaysia": "MYS", "Malta": "MLT", "Mauritius": "MUS",
    "Mexico": "MEX", "Moldova": "MDA", "Mongolia": "MNG", "Montenegro": "MNE",
    "Morocco": "MAR", "Mozambique": "MOZ", "Myanmar": "MMR", "Nepal": "NPL",
    "Netherlands": "NLD", "New Zealand": "NZL", "Nicaragua": "NIC",
    "Nigeria": "NGA", "North Macedonia": "MKD", "Norway": "NOR", "Oman": "OMN",
    "Pakistan": "PAK", "Panama": "PAN", "Paraguay": "PRY", "Peru": "PER",
    "Philippines": "PHL", "Poland": "POL", "Portugal": "PRT", "Qatar": "QAT",
    "Romania": "ROU", "Russia": "RUS", "Rwanda": "RWA", "Saudi Arabia": "SAU",
    "Senegal": "SEN", "Serbia": "SRB", "Seychelles": "SYC", "Singapore": "SGP",
    "Slovakia": "SVK", "Slovenia": "SVN", "South Africa": "ZAF",
    "South Korea": "KOR", "Spain": "ESP", "Sri Lanka": "LKA", "Sudan": "SDN",
    "Sweden": "SWE", "Switzerland": "CHE", "Syria": "SYR", "Taiwan": "TWN",
    "Tajikistan": "TJK", "Tanzania": "TZA", "Thailand": "THA", "Tunisia": "TUN",
    "Turkey": "TUR", "Turkmenistan": "TKM", "Uganda": "UGA", "Ukraine": "UKR",
    "United Arab Emirates": "ARE", "United Kingdom": "GBR",
    "United States": "USA", "Uruguay": "URY", "Uzbekistan": "UZB",
    "Venezuela": "VEN", "Vietnam": "VNM", "Yemen": "YEM", "Zambia": "ZMB",
    "Zimbabwe": "ZWE",
}

# Origin volume is extremely skewed — the top origin alone holds roughly a
# quarter of all traffic — so a linear colour scale would flatten everything
# below the top two into one indistinguishable shade. Colour is binned instead,
# on a single-hue ordinal ramp (dim → brand yellow) that clears the monotone
# lightness and light-end contrast checks against the charcoal panel.
HEAT_BANDS = [
    (1, 1, "1", "#61522a"),
    (2, 4, "2–4", "#836d2c"),
    (5, 9, "5–9", "#a68a30"),
    (10, 24, "10–24", "#c9aa3b"),
    (25, 49, "25–49", "#e7ca55"),
    (50, None, "50+", "#ffe17c"),
]

PANEL_DARK = "#171e19"
PANEL_LAND = "#232b28"
PANEL_LINE = "#0a0d0b"


def _canonical_country(name):
    clean = str(name).strip()
    return COUNTRY_ALIASES.get(clean.lower(), clean)


def _heat_band(count):
    for index, (low, high, label, colour) in enumerate(HEAT_BANDS):
        if count >= low and (high is None or count <= high):
            return index, label, colour
    return 0, HEAT_BANDS[0][2], HEAT_BANDS[0][3]


def render_origin_heatmap(df):
    """Attack origins as a binned choropleth plus its ranked table twin.

    The map answers "where is this coming from" at a glance; the leaderboard
    underneath carries the exact figures, so no value is readable only by
    colour — and origins the world topology cannot draw (city-states, small
    territories) still appear in the ranking rather than vanishing.
    """
    counts = (
        df["country"].map(_canonical_country).value_counts()
    )
    counts = counts[~counts.index.str.lower().isin(["unknown", "nan", "none", ""])]

    if counts.empty:
        gn_info("No geolocated origins yet — the map fills in as captures are enriched.")
        return

    total = int(counts.sum())
    top_name = str(counts.index[0])
    top_count = int(counts.iloc[0])
    top_share = round(top_count / total * 100)
    top3_share = round(counts.iloc[:3].sum() / total * 100)

    st.markdown(
        f'<div class="gn-map-head">'
        f'<span class="gn-live"><span class="gn-dot gn-map-hotdot"></span>'
        f'Hottest origin · {top_name}</span>'
        f'<h3>Where The Knocks Come From</h3>'
        f'<p>Every geolocated incursion, binned by volume. Origin is where the '
        f'packets entered from — not who sent them. Rotating an address moves a '
        f'dot on this map; it does not clear the client signature underneath it.</p>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<div class="gn-map-stats">'
        f'<div class="gn-map-stat gn-map-stat-hot">'
        f'<div class="gn-map-stat-label">Top Origin</div>'
        f'<div class="gn-map-stat-val">{top_name}</div>'
        f'<div class="gn-map-stat-sub">{top_count} incursions · {top_share}% of traffic</div>'
        f'</div>'
        f'<div class="gn-map-stat">'
        f'<div class="gn-map-stat-label">Countries Seen</div>'
        f'<div class="gn-map-stat-val">{len(counts)}</div>'
        f'<div class="gn-map-stat-sub">distinct origins on record</div>'
        f'</div>'
        f'<div class="gn-map-stat">'
        f'<div class="gn-map-stat-label">Top 3 Concentration</div>'
        f'<div class="gn-map-stat-val">{top3_share}%</div>'
        f'<div class="gn-map-stat-sub">of all traffic from 3 origins</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    iso, band_index, hover_name, hover_count, hover_share = [], [], [], [], []
    unmapped = []
    for name, count in counts.items():
        code = COUNTRY_ISO3.get(str(name))
        if not code:
            unmapped.append(str(name))
            continue
        iso.append(code)
        band_index.append(_heat_band(int(count))[0])
        hover_name.append(str(name).upper())
        hover_count.append(int(count))
        hover_share.append(round(int(count) / total * 100, 1))

    # A discrete colourscale: each band occupies one flat segment, so a country
    # reads as its bin rather than as a point on a gradient.
    bands = len(HEAT_BANDS)
    colourscale = []
    for index, (_, _, _, colour) in enumerate(HEAT_BANDS):
        colourscale.append([index / bands, colour])
        colourscale.append([(index + 1) / bands, colour])

    fig = go.Figure(
        go.Choropleth(
            locations=iso,
            z=band_index,
            zmin=-0.5,
            zmax=bands - 0.5,
            colorscale=colourscale,
            showscale=False,
            marker_line_color=PANEL_LINE,
            marker_line_width=0.7,
            customdata=list(zip(hover_name, hover_count, hover_share)),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "%{customdata[1]} incursions · %{customdata[2]}% of traffic"
                "<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        height=430,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor=PANEL_DARK,
        plot_bgcolor=PANEL_DARK,
        # dragmode is deliberately left at its default: on a geo subplot,
        # dragmode=False also removes the layer plotly attaches hover to, which
        # kills the per-country tooltip. Wheel-zoom is disabled via config instead.
        font=dict(family="Satoshi, sans-serif", color="#b7c6c2", size=12),
        hoverlabel=dict(
            bgcolor="#ffe17c",
            bordercolor="#000000",
            font=dict(family="Satoshi, sans-serif", color="#000000", size=13),
        ),
        geo=dict(
            bgcolor=PANEL_DARK,
            showland=True, landcolor=PANEL_LAND,
            showocean=True, oceancolor=PANEL_DARK,
            showcountries=True, countrycolor=PANEL_LINE, countrywidth=0.7,
            showcoastlines=True, coastlinecolor=PANEL_LINE, coastlinewidth=0.7,
            showlakes=False, showframe=False,
            projection_type="natural earth",
            lataxis_range=[-56, 84],
        ),
    )

    with st.container(key="gnmap_panel"):
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={"displayModeBar": False, "scrollZoom": False, "doubleClick": "reset"},
        )

    # The dimmest band and the no-data land colour are close enough at country size
    # that the legend has to name both, or a quiet origin reads as "never seen".
    legend_steps = (
        f'<div class="gn-map-legend-step">'
        f'<span class="gn-map-legend-sw" style="background:{PANEL_LAND};"></span>'
        f'<span class="gn-map-legend-lbl">none</span></div>'
    ) + "".join(
        f'<div class="gn-map-legend-step">'
        f'<span class="gn-map-legend-sw" style="background:{colour};"></span>'
        f'<span class="gn-map-legend-lbl">{label}</span></div>'
        for _, _, label, colour in HEAT_BANDS
    )
    st.markdown(
        f'<div class="gn-map-legend">'
        f'<div class="gn-map-legend-title">Incursions</div>{legend_steps}</div>',
        unsafe_allow_html=True,
    )
    if unmapped:
        st.caption(
            f"{len(iso)} of {len(counts)} origins have a drawable border on the world "
            f"topology. Ranked in full below, including {', '.join(unmapped[:4])}"
            + ("…" if len(unmapped) > 4 else "") + "."
        )

    ranked = counts.iloc[:12]
    rows = ""
    for position, (name, count) in enumerate(ranked.items(), start=1):
        width = int(count) / top_count * 100
        hot = " gn-map-row-hot" if position == 1 else ""
        rows += (
            f'<div class="gn-map-row{hot}">'
            f'<div class="gn-map-rank">{position:02d}</div>'
            f'<div class="gn-map-name">{name}</div>'
            f'<div class="gn-map-track"><div class="gn-map-fill" '
            f'style="width:{width:.1f}%; animation-delay:{position * 45}ms;"></div></div>'
            f'<div class="gn-map-count">{int(count)}</div>'
            f'</div>'
        )
    st.markdown(
        f'<div class="gn-map-board">'
        f'<div class="gn-map-board-head">Origin Leaderboard<span>'
        f'TOP {len(ranked)} OF {len(counts)}</span></div>{rows}</div>',
        unsafe_allow_html=True,
    )


def render_intelligence_node():
    st.title("Intelligence Node")
    st.markdown(
        '<span class="gn-live"><span class="gn-dot"></span>Live Telemetry · Autonomous Endpoint Defense · Active Tarpit Engaged</span>',
        unsafe_allow_html=True,
    )
    st.markdown("---")

    @st.fragment(run_every=10)
    def _live_feed():
        ledger_ok, ledger_msg = verify_ledger()
        badge_color = "var(--good)" if ledger_ok else "var(--danger)"
        badge_bg = "rgba(34,197,94,0.15)" if ledger_ok else "rgba(255,75,75,0.15)"
        badge_text = "● LOGS VERIFIED" if ledger_ok else "● LOGS TAMPERED"
        st.markdown(
            f'<span class="gn-badge" style="background:{badge_bg}; color:{badge_color};">{badge_text}</span>',
            unsafe_allow_html=True,
        )
        st.caption(ledger_msg)
        st.markdown("<br>", unsafe_allow_html=True)

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

                    tab_overview, tab_map, tab_log = st.tabs(["Overview", "Origin Heat Map", "Live Event Log"])

                    with tab_overview:
                        c1, c2 = st.columns(2)
                        with c1:
                            st.caption("Attacks by Country")
                            if 'country' in df.columns:
                                st.bar_chart(df['country'].value_counts(), color="#171E19")
                        with c2:
                            st.caption("Attacks by Category")
                            if 'attack_category' in df.columns:
                                st.bar_chart(df['attack_category'].value_counts(), color="#FF4B4B")

                    with tab_map:
                        if 'country' in df.columns:
                            render_origin_heatmap(df)

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
            with st.container(border=True, key="gncard_6"):
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
            with st.container(border=True, key="gncard_7"):
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


FP_FORMATS = [
    {
        "prefix": "ja3",
        "layer": "TLS",
        "name": "JA3",
        "format": "<32 lowercase hex chars>",
        "example": "e7d705a3286e19ea42f587b344ee6865",
        "built_from": "TLS version, cipher suites, extensions, elliptic curves and point formats from the ClientHello, joined and MD5-hashed.",
        "survives": "IP rotation, VPN/proxy hop",
        "defeated_by": "Changing the TLS stack or its cipher/extension configuration.",
    },
    {
        "prefix": "t13 / t12",
        "layer": "TLS",
        "name": "JA4",
        "format": "t<ver><nCiphers><nExt>_<sha256[:12]>_<sha256[:12]>",
        "example": "t1315_8d1f2a4b9c03_4e77a1d2b8f0",
        "built_from": "Same ClientHello evidence as JA3 but structured and sorted, so it is stable against extension shuffling.",
        "survives": "IP rotation, extension order randomisation",
        "defeated_by": "Changing the TLS stack itself.",
    },
    {
        "prefix": "h4h_",
        "layer": "HTTP",
        "name": "HTTP client signature",
        "format": "h4h_<ver><method><crlf><space><uri>_<nHeaders>_<orderHash>_<casingHash>",
        "example": "h4h_11getcsr_5_cac2c496544b_41f5d6",
        "built_from": "Header ORDER (the client library's own emit order), header name CASING pattern, HTTP version, method, CRLF vs bare LF, spacing after the colon, absolute vs relative URI.",
        "survives": "IP rotation, VPN hop, User-Agent spoofing, changing the requested path or Host",
        "defeated_by": "Switching HTTP client library, or hand-editing header order/casing.",
    },
    {
        "prefix": "sshc_",
        "layer": "SSH",
        "name": "SSH client signature",
        "format": "sshc_<proto>_<sha256(software)[:10]>_<sha256(comment)[:4]>",
        "example": "sshc_20_16be9ad569_e3b0",
        "built_from": "The SSH version banner the client sends first — protocol level, software product and build comment.",
        "survives": "IP rotation, VPN hop",
        "defeated_by": "Patching the client library to forge a different banner.",
    },
    {
        "prefix": "rdpc_",
        "layer": "RDP",
        "name": "RDP client signature",
        "format": "rdpc_<tpktLen>_<x224Len>_<cookieShape>_<sha256(negFlags)[:8]>",
        "example": "rdpc_42_37_4a_26db7dc6",
        "built_from": "X.224 connection-request geometry: TPKT and X.224 lengths, the shape (not value) of the mstshash cookie, and the requested security-protocol flags.",
        "survives": "IP rotation, cookie value randomisation",
        "defeated_by": "Using a different RDP client implementation.",
    },
    {
        "prefix": "gsig_",
        "layer": "Raw payload",
        "name": "Structural probe signature",
        "format": "gsig_<first4bytesHex>_<lenBucket>_<p-c-h profile>_<sha256(token)[:10]>",
        "example": "gsig_4d474c4e_32_9-0-0_3f112fb8e2",
        "built_from": "Shape of an opaque first packet: leading bytes, exponential length bucket, printable/control/high byte histogram, and any printable beacon token with host and port normalised out.",
        "survives": "IP rotation, retargeting the same scanner at a different host or port",
        "defeated_by": "Changing the probe payload itself.",
    },
]


def render_fingerprint_registry():
    st.markdown(
        '<div class="gn-page-banner">'
        '<span class="gn-page-banner-eyebrow">Attacker Identity</span>'
        '<h2>Fingerprint Registry</h2>'
        '<p>Every signature format GhostNet can recognise, and what each one actually '
        'survives. Signatures identify the attacker&rsquo;s tooling, not their address — '
        'which is what makes IP and VPN rotation stop working.</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    try:
        with open(FINGERPRINT_DB, "r", encoding="utf-8") as f:
            sigs = json.load(f)
    except Exception:
        sigs = []

    sightings = {}
    try:
        with open(os.path.join(BASE_DIR, "fingerprint_sightings.json"), "r", encoding="utf-8") as f:
            sightings = json.load(f)
    except Exception:
        sightings = {}

    def family_of(s):
        s = str(s)
        if s.startswith("h4h_"):
            return "HTTP"
        if s.startswith("sshc_"):
            return "SSH"
        if s.startswith("rdpc_"):
            return "RDP"
        if s.startswith("gsig_"):
            return "Raw payload"
        if s.startswith("t13") or s.startswith("t12"):
            return "TLS"
        if len(s) == 32:
            return "TLS"
        return "Other"

    counts = {}
    for s in sigs:
        counts[family_of(s)] = counts.get(family_of(s), 0) + 1

    linked_ips = set()
    for fp, ent in sightings.items():
        if fp in sigs:
            linked_ips.update(ent.get("ips", []))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Signatures Blocked", len(sigs))
    m2.metric("Formats Recognised", len(FP_FORMATS))
    m3.metric("Signatures Tracked", len(sightings))
    m4.metric("IPs Attributed", len(linked_ips))

    st.markdown("<br>", unsafe_allow_html=True)
    if counts:
        st.caption("Blocked signatures by protocol family")
        st.bar_chart(pd.Series(counts).sort_values(ascending=False), color="#171E19")

    st.markdown("---")
    st.subheader("Signature Formats")
    st.caption("The anatomy of every fingerprint string GhostNet produces or enforces.")

    for fmt in FP_FORMATS:
        n = counts.get(fmt["layer"] if fmt["layer"] != "Raw payload" else "Raw payload", 0)
        with st.container(border=True, key=f"gnfp_{fmt['prefix'].strip('_ /')}"):
            head_l, head_r = st.columns([3, 1])
            with head_l:
                st.markdown(f"**{fmt['name']}** &nbsp;·&nbsp; `{fmt['prefix']}` &nbsp;·&nbsp; {fmt['layer']} layer")
            with head_r:
                st.markdown(
                    f'<div style="text-align:right;font-weight:700;">{n} blocked</div>',
                    unsafe_allow_html=True,
                )
            st.code(fmt["format"], language="text")
            st.markdown(f"**Example** &nbsp; `{fmt['example']}`")
            st.markdown(f"**Built from** — {fmt['built_from']}")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"✅ **Survives:** {fmt['survives']}")
            with c2:
                st.markdown(f"⚠️ **Defeated by:** {fmt['defeated_by']}")

    st.markdown("---")
    st.subheader("Most Widely Rotated Actors")
    st.caption("One signature seen from many distinct IPs is a single actor hopping addresses.")

    rows = []
    for fp, ent in sightings.items():
        n_ips = len(ent.get("ips", [])) + ent.get("ips_overflow", 0)
        rows.append({
            "Signature": fp,
            "Family": family_of(fp),
            "Distinct IPs": n_ips,
            "Sightings": ent.get("hits", 0),
            "Malicious": ent.get("malicious", 0),
            "Blocked": "Yes" if fp in sigs else "No",
            "Description": (ent.get("label") or "")[:60],
        })
    if rows:
        df_fp = pd.DataFrame(rows).sort_values(["Distinct IPs", "Sightings"], ascending=False)
        st.dataframe(df_fp, use_container_width=True, hide_index=True, height=420)
        worst = df_fp.iloc[0]
        if worst["Distinct IPs"] > 1:
            gn_info(
                f"Widest rotation: **{worst['Description'] or worst['Signature']}** "
                f"— one signature across **{worst['Distinct IPs']} distinct IP addresses**. "
                "Banning the IPs alone would have missed every one of them after the first.",
                title="IP Hopping Detected",
            )
    else:
        st.caption("No signature sightings recorded yet.")

    render_footer_links()


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
    with st.container(border=True, key="gncard_8"):
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
        with st.container(border=True, key="gncard_9"):
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
        with st.container(border=True, key="gncard_10"):
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
    st.markdown(
        '<div class="gn-page-banner">'
        '<span class="gn-page-banner-eyebrow">Threat Intel API</span>'
        '<h2>Your API Portal</h2>'
        '<p>Secure access, key management, live consumption metrics and integration docs '
        '— everything you need to wire the blocklist into your own stack.</p>'
        '</div>',
        unsafe_allow_html=True,
    )

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
        with st.container(border=True, key="gncard_11"):
            st.subheader("Access Token")
            st.caption("Your programmatic identification sequence. Include this string inside the X-API-Key transaction header.")
            st.code(raw_token, language="text")

        with st.container(border=True, key="gncard_12"):
            st.subheader("Account")
            profile_data = {
                "Metric Configuration": ["Identity Domain", "Registration Event Timestamp", "Purchased Volume Quota Limit"],
                "Active Value": [st.session_state.user, user_profile.get("created_at", "N/A"), f"{max_quota:,} requests"],
            }
            st.dataframe(pd.DataFrame(profile_data), use_container_width=True, hide_index=True)

        with st.container(border=True, key="gncard_13"):
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

    with left_col:
        with st.container(border=True, key="gncard_15"):
            st.subheader("Client Signature Feed")
            st.caption(
                "New — identities that survive IP rotation. The blocklist tells you which "
                "addresses to drop; this tells you which clients to drop, so a known actor "
                "is blocked on their first connection from an address you have never seen."
            )

            try:
                with open(FINGERPRINT_DB, "r", encoding="utf-8") as f:
                    _sigs = json.load(f)
            except Exception:
                _sigs = []

            def _fam(s):
                s = str(s)
                for pre, name in (("h4h_", "http"), ("sshc_", "ssh"),
                                  ("rdpc_", "rdp"), ("gsig_", "generic")):
                    if s.startswith(pre):
                        return name
                if s.startswith("t13") or s.startswith("t12"):
                    return "ja4"
                return "ja3" if len(s) == 32 else "other"

            _counts = {}
            for _s in _sigs:
                _counts[_fam(_s)] = _counts.get(_fam(_s), 0) + 1

            fc1, fc2, fc3 = st.columns(3)
            fc1.metric("Signatures", len(_sigs))
            fc2.metric("Families", len(_counts))
            fc3.metric("Beyond TLS", sum(v for k, v in _counts.items() if k not in ("ja3", "ja4")))

            st.markdown(
                "| Family | Layer you enforce it at | What it survives |\n"
                "| --- | --- | --- |\n"
                "| `ja3` / `ja4` | TLS terminator | IP rotation, VPN hop |\n"
                "| `h4h_` | HTTP reverse proxy / WAF | IP rotation, **User-Agent spoofing**, path changes |\n"
                "| `sshc_` | SSH bastion | IP rotation, VPN hop |\n"
                "| `rdpc_` | RDP gateway | IP rotation, cookie randomisation |\n"
                "| `gsig_` | Edge / packet inspection | IP rotation, retargeting the probe |\n"
            )

            st.markdown("**Endpoint**")
            st.code("GET /api/threats/fingerprints?family=http", language="text")
            st.caption(
                "Same authentication as the blocklist: `X-API-Key` plus a valid `X-PoW-Nonce`. "
                "Counts against the same quota. Omit `family` for everything."
            )

            with st.expander("Response shape"):
                st.code(
                    '{\n'
                    '  "count": 12,\n'
                    '  "families": { "http": 12 },\n'
                    '  "filter": "http",\n'
                    '  "signatures": [\n'
                    '    {\n'
                    '      "signature": "h4h_11getcsr_5_cac2c496544b_41f5d6",\n'
                    '      "family": "http",\n'
                    '      "layer": "application",\n'
                    '      "description": "HTTP client signature: header order, name casing, version, line endings"\n'
                    '    }\n'
                    '  ]\n'
                    '}',
                    language="json",
                )

            with st.expander("Enforce an HTTP signature at your own edge"):
                st.caption(
                    "Recompute the signature from the request headers you receive and drop "
                    "the connection if it appears in the feed. Header order and casing are "
                    "the evidence, so preserve them — many frameworks normalise both away."
                )
                st.code(
                    "import hashlib\n\n"
                    "def http_signature(method, version, raw_header_lines):\n"
                    "    \"\"\"raw_header_lines: header lines exactly as received, in order.\"\"\"\n"
                    "    names = [l.split(':', 1)[0].strip() for l in raw_header_lines if ':' in l]\n"
                    "    order = ','.join(n.lower() for n in names)\n"
                    "    casing = ''.join(\n"
                    "        'l' if n.islower() else 'U' if n.isupper()\n"
                    "        else 'T' if n == n.title() else 'm'\n"
                    "        for n in names\n"
                    "    )\n"
                    "    order_hash = hashlib.sha256(order.encode()).hexdigest()[:12]\n"
                    "    casing_hash = hashlib.sha256(casing.encode()).hexdigest()[:6]\n"
                    "    # crlf/space/uri flags omitted for brevity — see the docs tab\n"
                    "    return f\"h4h_{version}{method[:4].lower()}csr_{len(names)}_{order_hash}_{casing_hash}\"\n",
                    language="python",
                )

    with right_col:
        with st.container(border=True, key="gncard_14"):
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
elif nav == "Fingerprint Registry":
    render_fingerprint_registry()
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
