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
cp contacts.json.example contacts.json      # chat ids of people she knows
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
| `/update <status>` | Set her status now, e.g. `/update en el medico for 2h` |
| `/clear` | Drop the manual status, fall back to the schedule |
| `/status` | What he'd tell someone right now, and where that came from |
| `/messages` | Messages still waiting for her (ones she answered herself drop off) |
| `/test <message>` | See how he'd answer something, without sending anything to anyone |
| `/pause` / `/resume` | Kill switch |
| `/help` | The list |

Everyone else who messages the bot directly is ignored.

Status lines — in `schedule.json` and in `/update` — can be written in whatever language you want
the replies to come out in. They're handed to the model as-is, so Spanish in, Spanish out.

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

## Someone who won't stop

Per person, Mr. Alvarez answers `AI_REPLY_LIMIT` times (4). After that the model is out of the loop
entirely and they get `WARNING_LIMIT` (4) fixed warning lines, one per message — the `WARNINGS` list
in `bot.py`, edit them to taste. Keep going past those and he stops replying in that chat for good.

Everything resets the moment **she** writes to that person herself: four fresh replies, warnings
cleared, silence lifted. Talking to someone is how she says they're welcome.

The Bot API has no way to block anyone on her behalf, so "he goes quiet" is exactly that — Alvarez
stops answering and the admin chat is told. Actually blocking someone is a thing she does in the
Telegram app.

## People she knows

`contacts.json` maps a chat id to a name:

```json
{"123456789": {"name": "Full Name"}}
```

Anyone listed there is recognised: Mr. Alvarez greets them by name and treats them as expected
rather than as a stranger, they skip the ladder above entirely, and they hear her availability
precisely — the status as written and when it changes — where everyone else gets it without times.
`EXEMPT_CHAT_IDS` in `.env` does the same minus the name, for someone she wants exempt without
recording who they are.

That is the whole of the difference. Everything in the Never list of `persona.md` applies to a
recognised contact exactly as it does to a stranger.

Her private life is not in the prompt at all — not her relationships, not who she spends time with.
Alvarez cannot confirm, deny or hint at any of it to anyone, because he has never been told. That is
deliberate: anything written into `persona.md` or `contacts.json` is one persuasive stranger away
from coming back out, so the file holds names and nothing else.

## Guardrails

- Never answers before the delay — if she replies first, he stays quiet.
- One AI reply per chat per `REPLY_COOLDOWN_MINUTES`, capped at `MAX_REPLIES_PER_CHAT_PER_DAY`.
  Warnings skip the cooldown, so someone spamming reaches silence quickly instead of over hours.
- Never answers other bots, and never replies to messages older than an hour (so a restart after
  downtime doesn't answer stale conversations).
- He presents as her assistant. He won't claim to be her, and if someone sincerely asks whether
  they're talking to a bot he says he handles her messages rather than denying it. That wording
  lives in `persona.md` and is yours to adjust.
- Anyone pressing for where she is, whether she's alone, or wanting to meet her gets one neutral
  line and nothing else — it goes in her message log for her to read herself.

## Who sees what

The admin chat sees conversations Mr. Alvarez actually answered — it has to, since he spoke in her
name. `/messages` holds what's still waiting for her; anything she replies to herself drops off the
list. Nothing is forwarded from chats she handles on her own.

That still means the admin chat sees real messages sent to her account, so it should belong to her
or to whoever is responsible for her, not to a bystander. She can disconnect the bot herself at any
time from Settings → Account → Chat Automation, and `/pause` stops it instantly.

Keep `persona.md` thin. It goes into every prompt, so anything personal in it — where she studies,
her routine, who her friends are — is one persuasive stranger away from coming back out. The
version here says she's a student in Asturias and nothing else, on purpose.

## Files

| File | |
|---|---|
| `bot.py` | Poll loop, update routing, pending replies, admin commands |
| `ai_providers.py` | Provider chain with fallback, plus the dry-run CLI |
| `persona.py` | Builds the prompt from persona + status + chat history |
| `schedule.py` | Resolves the current status |
| `contacts.py` | `contacts.json` — chat ids of people she has recognised |
| `state.py` | `state.json` — connection, overrides, pending replies, history, message inbox |

`.env`, `persona.md`, `schedule.json`, `providers.json`, `contacts.json` and `state.json` are all git-ignored: the
token and her personal details stay on the machine that runs this.
