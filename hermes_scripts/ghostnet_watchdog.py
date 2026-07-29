#!/usr/bin/env python3
"""Deterministic, rule-based watchdog for the GhostNet stack. Runs on a Hermes
cron timer in --no-agent mode - no LLM makes the "is this suspicious" call,
only fixed thresholds. When (and only when) a rule fires, this escalates to a
real Claude Code session via `claude -p`, scoped down with --allowedTools so
it can only run two narrow, input-validated scripts (ban a confirmed IP, or
send a Telegram report) - nothing else. Self rate-limited so a misfiring
rule or a burst of real attack traffic can't spam expensive Claude Code
invocations.
"""
import json
import os
import re
import subprocess
import sys
import time

KHARAZMI = "/root/Kharazmi"
CURSOR_FILE = os.path.join(KHARAZMI, ".monitor_cursor.json")
RATE_LIMIT_FILE = os.path.join(KHARAZMI, ".claude_trigger_rate.json")
MAX_TRIGGERS_PER_HOUR = 4

SECRET_SCAN_MARKERS = [
    ".env", ".claude/", "wp-admin", "wp-login", ".git/config", ".git/head",
    "phpmyadmin", "id_rsa", ".aws/credentials", ".ssh/", "xmlrpc.php",
    "key/generate",
]
KNOWN_LEDGER_CATEGORIES = {"ban", "classification", "capture", "remediation"}
REQUIRED_PROCESSES = ["honeypot.py", "enrich.py", "uvicorn", "defender.py"]


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f)


def read_new_ledger_entries(last_seq):
    path = os.path.join(KHARAZMI, "security_ledger.jsonl")
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("seq", 0) > last_seq:
                entries.append(e)
    return entries


def check_process_health():
    out = subprocess.run(["ps", "aux"], capture_output=True, text=True).stdout
    return [name for name in REQUIRED_PROCESSES if name not in out]


def check_2xx_on_secret_paths(max_lines=3000):
    path = os.path.join(KHARAZMI, "api.log")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        lines = f.readlines()[-max_lines:]
    hits = []
    for line in lines:
        low = line.lower()
        if any(marker in low for marker in SECRET_SCAN_MARKERS):
            m = re.search(r'"\s(\d{3})\s', line)
            if m and m.group(1).startswith("2"):
                hits.append(line.strip())
    return hits


def rate_limited():
    now = time.time()
    hist = [t for t in load_json(RATE_LIMIT_FILE, []) if now - t < 3600]
    return len(hist) >= MAX_TRIGGERS_PER_HOUR, hist


def record_trigger(hist):
    hist.append(time.time())
    save_json(RATE_LIMIT_FILE, hist)


def escalate_to_claude(reasons):
    scripts_dir = os.path.join(KHARAZMI, "scripts")
    prompt = (
        "Automated GhostNet security watchdog trigger. These are raw facts from a "
        "deterministic rule check, NOT a pre-formed conclusion - verify independently "
        "before doing anything:\n"
        + "\n".join(f"- {r}" for r in reasons)
        + "\n\nFollow the cybersecurity-monitor skill's triage playbook "
        "(/root/.claude/skills/cybersecurity-monitor/SKILL.md). Investigate with read-only "
        "commands first (cat/tail/grep on files under /root/Kharazmi, ps aux, "
        "sudo iptables -L/-C). You may take exactly one kind of remediation action: if you "
        "independently confirm a single IP is a repeat secret/config-path scanner and it is "
        "not already in banned_ips.txt, run: "
        f"python3 {scripts_dir}/confirmed_ban.py <ip> \"<short reason>\" "
        "For everything else - a 2xx response on a sensitive path, a dead process, an "
        "unrecognized ledger category, anything ambiguous, or if you are not confident - do "
        "NOT take any action. Instead run exactly once: "
        f"python3 {scripts_dir}/send_alert.py \"<your finding, 2-5 lines, what a human should "
        "check>\" and stop. Do not attempt any action outside these two scripts; you do not "
        "have permission for anything else and it will simply be denied."
    )

    result = subprocess.run(
        [
            "claude", "-p", prompt,
            "--bare",  # skip hooks/LSP/plugin-marketplace-sync/attribution - this is a
                       # narrow scripted invocation, not an interactive session, and
                       # marketplace sync over git+ssh hangs on this host (no SSH keys)
            "--allowedTools",
            "Bash(cat *)", "Bash(tail *)", "Bash(grep *)", "Bash(ps aux)",
            "Bash(sudo iptables -L*)", "Bash(sudo iptables -C*)",
            f"Bash(python3 {scripts_dir}/confirmed_ban.py *)",
            f"Bash(python3 {scripts_dir}/send_alert.py *)",
            "--disallowedTools", "Write", "Edit", "NotebookEdit", "Agent",
            "--permission-mode", "dontAsk",
            "--output-format", "json",
        ],
        cwd=KHARAZMI,
        capture_output=True,
        text=True,
        timeout=600,
    )
    return result


def main():
    first_run = not os.path.exists(CURSOR_FILE)
    cursor = load_json(CURSOR_FILE, {"last_seq": 0})
    last_seq = cursor.get("last_seq", 0)
    new_entries = read_new_ledger_entries(last_seq)
    max_seq = max([e.get("seq", last_seq) for e in new_entries], default=last_seq)

    if first_run:
        # Establish the baseline only - a fresh deploy must never treat the
        # entire pre-existing ledger history as "new" activity to alert on.
        save_json(CURSOR_FILE, {"last_seq": max_seq})
        print(f"[watchdog] first run - baseline set to seq {max_seq}, no evaluation")
        return

    reasons = []

    unrecognized = [e for e in new_entries if e.get("category") not in KNOWN_LEDGER_CATEGORIES]
    if unrecognized:
        cats = sorted({e.get("category") for e in unrecognized})
        reasons.append(f"{len(unrecognized)} unrecognized ledger event(s), categories: {cats}")

    ban_events = [e for e in new_entries if e.get("category") == "ban"]
    if len(ban_events) >= 10:
        reasons.append(f"ban rate spike: {len(ban_events)} bans since last check ({len(new_entries)} total events)")

    dead = check_process_health()
    if dead:
        reasons.append(f"process(es) not detected in `ps aux`: {dead}")

    exposed = check_2xx_on_secret_paths()
    if exposed:
        reasons.append(f"2xx response on a secret-scan path: {len(exposed)} instance(s), most recent: {exposed[-1][:200]}")

    save_json(CURSOR_FILE, {"last_seq": max_seq})

    if not reasons:
        return  # silent - nothing to report, no LLM was involved in reaching this conclusion

    limited, hist = rate_limited()
    if limited:
        print(f"[watchdog] trigger conditions met but rate-limited (>= {MAX_TRIGGERS_PER_HOUR}/hr): {reasons}")
        return

    record_trigger(hist)
    result = escalate_to_claude(reasons)
    print(f"[watchdog] escalated to claude -p (exit {result.returncode}). reasons: {reasons}")
    if result.returncode != 0:
        print(f"[watchdog] stderr: {result.stderr[:2000]}", file=sys.stderr)


if __name__ == "__main__":
    main()
