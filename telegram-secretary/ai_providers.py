import json
import os
import sys

import requests

import env

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROVIDERS_FILE = os.path.join(BASE_DIR, "providers.json")
TIMEOUT = 45


class AllProvidersFailed(Exception):
    pass


def providers():
    try:
        with open(PROVIDERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):
        data = data.get("providers", [])
    return [p for p in data if isinstance(p, dict) and p.get("base_url") and p.get("model")]


def _call(provider, messages, temperature, max_tokens):
    key = os.environ.get(provider.get("api_key_env", ""), "").strip()
    if provider.get("api_key_env") and not key:
        raise RuntimeError("{} is not set in .env".format(provider["api_key_env"]))

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer {}".format(key)
    headers.update(provider.get("headers", {}))

    response = requests.post(
        provider["base_url"].rstrip("/") + "/chat/completions",
        headers=headers,
        json={
            "model": provider["model"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    text = (response.json()["choices"][0]["message"]["content"] or "").strip()
    if not text:
        raise ValueError("provider returned an empty message")
    return text


def generate(messages, temperature=0.5, max_tokens=300):
    """Try each configured provider in order. Returns (reply_text, provider_name)."""
    configured = providers()
    if not configured:
        raise AllProvidersFailed("no providers configured - fill in providers.json")

    failures = []
    for provider in configured:
        name = provider.get("name") or provider["model"]
        try:
            return _call(provider, messages, temperature, max_tokens), name
        except Exception as exc:
            failures.append("{}: {}".format(name, exc))
            print("[ai] {} failed: {}".format(name, exc), flush=True)
    raise AllProvidersFailed(" | ".join(failures))


if __name__ == "__main__":
    import persona
    import schedule

    env.load()
    incoming = " ".join(sys.argv[1:]) or "Hi, is Martina around?"
    status, source = schedule.current_status(None)
    messages = persona.build_messages(
        history=[{"role": "them", "text": incoming}],
        status=status,
        schedule_hint=schedule.availability_hint(),
        sender_name="Test Sender",
    )
    print("--- system prompt ---")
    print(messages[0]["content"])
    print("\n--- status ---")
    print("{} (from {})".format(status, source))
    print("\n--- them ---")
    print(incoming)
    print("\n--- Mr. Alvarez ---")
    try:
        reply, provider_name = generate(messages)
        print("{}\n\n[via {}]".format(reply, provider_name))
    except AllProvidersFailed as exc:
        print("all providers failed: {}".format(exc))
        sys.exit(1)
