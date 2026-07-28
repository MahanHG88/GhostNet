# GhostNet

Autonomous threat intelligence and active defense platform: a honeypot that captures and TLS-fingerprints (JA3/JA4) real attack attempts, an AI enrichment pipeline that classifies each one, an active defense daemon that auto-bans high-severity attackers, a commercial-style API gateway for the resulting threat feed, an operations dashboard, and a Telegram bot that mirrors the whole admin panel.

## Components

- `honeypot.py` — decoy service on port 2222 that captures connection attempts and fingerprints the client's TLS handshake.
- `enrich.py` — geolocates captured attacks and classifies them (category + severity) via an LLM over OpenRouter.
- `defender.py` — watches enriched data and firewalls High/Critical severity attackers automatically.
- `api.py` — FastAPI gateway that serves the threat feed to subscribers, gated by API key + a proof-of-work challenge.
- `app.py` — Streamlit dashboard: admin intelligence view, civilian alarm panel, developer self-serve portal, and an AI chat assistant ("Ghost").
- `telegram_bot.py` — Telegram admin bot mirroring the dashboard's admin capabilities, with inline-button navigation and a password-gated login.
- `telegram_notify.py` — shared helper the other processes use to push live event notifications to Telegram.
- `start.sh` — launches all of the above as background processes.

## Setup

1. `pip install -r requirements.txt` *(not yet pinned — see below)*
2. Copy `.env.example` to `.env` and fill in real values.
3. Generate a TLS cert/key for the dashboard (`server.crt` / `server.key`), or point `start.sh` at your own.
4. `./start.sh`

## Notes

- All runtime state (attack logs, banned lists, activity logs, developer accounts) lives in flat JSON files alongside the code and is gitignored — it's data, not source.
- No `requirements.txt` is committed yet; dependencies currently in use: `streamlit`, `pandas`, `plotly`, `fastapi`, `uvicorn`, `requests`.
