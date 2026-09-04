# Mr. Alvarez — a Telegram message desk for Ms. Martina Garcia

An answering service for a personal Telegram account. When someone writes to Ms. Garcia and she
hasn't answered within a few minutes, **Mr. Alvarez** — her assistant — steps in, tells them where
she stands right now, answers simple practical questions, and takes a message for her. He keeps it
short and businesslike: no small talk, no personal details, no promises on her behalf.

He stands down the moment she replies herself.

This runs on Telegram's built-in **Chat Automation** feature (Settings → Account → Chat Automation),
which is the supported way for a bot to answer on a personal account's behalf. No third-party login,
no session hijacking — the account owner connects the bot herself and can disconnect it at any time.

This project is self-contained and has nothing to do with the rest of the GhostNet repo.

## How it decides what to say

Her current status comes from the first of these that applies:

1. **A manual update** — `/update in a meeting until 4pm` (optionally `for 90m` to auto-expire)
2. **The weekly schedule** in `schedule.json`
3. **The default line** in `schedule.json`

## Setup

**1. The bot**

Create a bot with [@BotFather](https://t.me/BotFather) and keep the token.

**2. Connect it to her account**

On the phone signed in as Ms. Garcia: Settings → Account → Chat Automation → enter the bot's
username → choose which chats it may access (and exclude any it shouldn't touch) → make sure it is
allowed to reply.

**3. Configure**

```bash
cd telegram-secretary
pip install -r requirements.txt

cp .env.example .env                        # token + admin chat id + timings
cp persona.example.md persona.md            # who she is, what he may say
cp schedule.json.example schedule.json      # her week
cp providers.json.example providers.json    # the AI providers to try, in order
```

`ADMIN_CHAT_ID` is the only chat that can run commands, and the only one that sees the audit trail.
Get it by messaging [@userinfobot](https://t.me/userinfobot).

**4. Run**

```bash
python bot.py                     # foreground
nohup python bot.py > alvarez.log 2>&1 &    # background
```

## Commands (admin chat only)

| Command | What it does |
|---|---|
| `/update <status>` | Set her status now, e.g. `/update on a flight for 6h` |
| `/clear` | Drop the manual status, fall back to the schedule |
| `/status` | What he'd tell someone right now, and where that came from |
| `/messages` | Recent messages people left for her |
| `/pause` / `/resume` | Kill switch |
| `/help` | The list |

Everyone else who messages the bot directly is ignored.

## AI providers

`providers.json` is an ordered list. Each one is tried in turn and the first that answers wins, so a
dead key or a rate limit just falls through to the next:

```json
[{"name": "openrouter", "base_url": "https://openrouter.ai/api/v1",
  "api_key_env": "OPENROUTER_API_KEY", "model": "openai/gpt-oss-20b:free"}]
```

Any provider speaking the OpenAI `/chat/completions` shape works as-is — OpenRouter, OpenAI, Groq,
Together, a local Ollama (`http://localhost:11434/v1`, no key). A provider with a different request
shape (Anthropic's native Messages API, say) would need a small adapter branch in `ai_providers.py`.

If every provider fails, **nothing is sent** and the admin chat gets told, so a human can step in.

Try the wording without touching Telegram:

```bash
python ai_providers.py "hi, is Martina free tomorrow?"
```

## Guardrails

- Never answers before the delay — if she replies first, he stays quiet.
- One reply per chat per `REPLY_COOLDOWN_MINUTES`, capped at `MAX_REPLIES_PER_CHAT_PER_DAY`.
- Never answers other bots, and never replies to messages older than an hour (so a restart after
  downtime doesn't answer stale conversations).
- He presents as her assistant. He won't claim to be her, and if someone sincerely asks whether
  they're talking to a bot he says he handles her messages rather than denying it. That wording
  lives in `persona.md` and is yours to adjust.

## Files

| File | |
|---|---|
| `bot.py` | Poll loop, update routing, pending replies, admin commands |
| `ai_providers.py` | Provider chain with fallback, plus the dry-run CLI |
| `persona.py` | Builds the prompt from persona + status + chat history |
| `schedule.py` | Resolves the current status |
| `state.py` | `state.json` — connection, overrides, pending replies, history, message inbox |

`.env`, `persona.md`, `schedule.json`, `providers.json` and `state.json` are all git-ignored: the
token and her personal details stay on the machine that runs this.
