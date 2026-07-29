#!/usr/bin/env python3
"""Single-purpose, input-validated ban action for automated triage callers
(the Hermes watchdog -> claude -p escalation pipeline). Deliberately does
nothing else: no arbitrary command execution, no code paths beyond the one
already-established ban mechanism (iptables + banned_ips.txt + ledger +
Telegram), matching what defender.py/honeypot.py already do for confirmed
scanners. Rejects anything that isn't a syntactically valid IPv4/IPv6
address before touching the firewall.
"""
import ipaddress
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(BASE_DIR))

from telegram_notify import notify  # noqa: E402
from tamperlog import log_event  # noqa: E402

BANNED_IPS_FILE = os.path.join(os.path.dirname(BASE_DIR), "banned_ips.txt")


def already_banned(ip):
    if not os.path.exists(BANNED_IPS_FILE):
        return False
    with open(BANNED_IPS_FILE) as f:
        return ip in {line.strip() for line in f}


def main():
    if len(sys.argv) < 2:
        print("usage: confirmed_ban.py <ip> [reason]", file=sys.stderr)
        sys.exit(2)

    raw_ip = sys.argv[1].strip()
    reason = sys.argv[2].strip() if len(sys.argv) > 2 else "auto-triage"

    try:
        ip_obj = ipaddress.ip_address(raw_ip)
    except ValueError:
        print(f"refused: '{raw_ip}' is not a valid IP address", file=sys.stderr)
        sys.exit(1)

    ip = str(ip_obj)

    if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_reserved or ip_obj.is_link_local:
        print(f"refused: '{ip}' is private/loopback/reserved - not banning", file=sys.stderr)
        sys.exit(1)

    if already_banned(ip):
        print(f"no-op: {ip} is already banned")
        sys.exit(0)

    subprocess.run(["sudo", "iptables", "-A", "INPUT", "-s", ip, "-j", "DROP"], check=True)
    with open(BANNED_IPS_FILE, "a") as f:
        f.write(ip + "\n")

    h = log_event("ban", "claude-auto-triage", f"Firewall-banned {ip} ({reason})")
    notify(
        f"Active defense: firewall-banned {ip}\n"
        f"Reason: {reason}\n"
        f"Source: automated Hermes-watchdog -> Claude Code triage"
        + (f"\nledger: {h[:12]}" if h else "")
    )
    print(f"banned {ip}: {reason}")


if __name__ == "__main__":
    main()
