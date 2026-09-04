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


def _split_system(messages):
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    return system, [m for m in messages if m["role"] != "system"]


def _call_anthropic(provider, messages, temperature, max_tokens):
    """Anthropic's Messages API: the system prompt travels separately and the key is a header."""
    key = os.environ.get(provider.get("api_key_env", ""), "").strip()
    if provider.get("api_key_env") and not key:
        raise RuntimeError("{} is not set in .env".format(provider["api_key_env"]))

    system, turns = _split_system(messages)
    headers = {"content-type": "application/json", "anthropic-version": "2023-06-01"}
    if key:
        headers["x-api-key"] = key
    headers.update(provider.get("headers", {}))

    response = requests.post(
        provider["base_url"].rstrip("/") + "/v1/messages",
        headers=headers,
        json={
            "model": provider["model"],
            "system": system,
            "messages": turns,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    blocks = response.json().get("content") or []
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
    if not text:
        raise ValueError("provider returned an empty message")
    return text


def _flatten(messages):
    system, turns = _split_system(messages)
    lines = [system] if system else []
    for turn in turns:
        lines.append("{}: {}".format("Them" if turn["role"] == "user" else "You", turn["content"]))
    return "\n\n".join(lines)


def _fill(value, fields):
    if isinstance(value, str):
        return value.format(**fields) if "{" in value else value
    if isinstance(value, dict):
        return {k: _fill(v, fields) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, fields) for v in value]
    return value


def _dig(data, path):
    for step in path.split("."):
        data = data[int(step)] if step.isdigit() else data[step]
    return data


def _call_custom(provider, messages, temperature, max_tokens):
    """Anything that is neither OpenAI- nor Anthropic-shaped. The config says where to post,
    what the body looks like, and where the reply sits in the response."""
    key = os.environ.get(provider.get("api_key_env", ""), "").strip()
    if provider.get("api_key_env") and not key:
        raise RuntimeError("{} is not set in .env".format(provider["api_key_env"]))

    system, turns = _split_system(messages)
    fields = {
        "prompt": _flatten(messages),
        "system": system,
        "message": turns[-1]["content"] if turns else "",
        "model": provider["model"],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    headers = {"Content-Type": "application/json"}
    auth = provider.get("auth", "bearer")
    if key and auth == "bearer":
        headers["Authorization"] = "Bearer {}".format(key)
    elif key and auth == "x-api-key":
        headers["x-api-key"] = key
    headers.update(_fill(provider.get("headers", {}), fields))

    payload = _fill(provider.get("payload") or {"prompt": "{prompt}"}, fields)
    response = requests.post(
        provider["base_url"].rstrip("/") + provider.get("path", ""),
        headers=headers,
        json=payload,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    body = response.json()
    try:
        text = str(_dig(body, provider.get("response_path", "response"))).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("response_path {!r} does not fit the reply: {}".format(
            provider.get("response_path", "response"), str(body)[:200])) from exc
    if not text:
        raise ValueError("provider returned an empty message")
    return text


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


FORMATS = {"anthropic": _call_anthropic, "custom": _call_custom}


def generate(messages, temperature=0.5, max_tokens=300):
    """Try each configured provider in order. Returns (reply_text, provider_name)."""
    configured = providers()
    if not configured:
        raise AllProvidersFailed("no providers configured - fill in providers.json")

    failures = []
    for provider in configured:
        name = provider.get("name") or provider["model"]
        call = FORMATS.get(provider.get("format"), _call)
        try:
            return call(provider, messages, temperature, max_tokens), name
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
