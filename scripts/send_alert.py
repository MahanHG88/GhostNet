#!/usr/bin/env python3
"""Single-purpose alert sender for automated triage callers. Takes exactly
one argument (the message text) and forwards it to the existing Telegram
bot - no shell interpolation, no code execution, no other side effect
possible. This is the escalation path's default action for anything that
isn't a clear-cut repeat-scanner ban (2xx on a sensitive path, a dead
process, an unrecognized ledger event): report to a human, do not act.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(BASE_DIR))

from telegram_notify import notify  # noqa: E402


def main():
    if len(sys.argv) != 2:
        print("usage: send_alert.py \"<message>\"", file=sys.stderr)
        sys.exit(2)

    message = sys.argv[1].strip()
    if not message:
        print("refused: empty message", file=sys.stderr)
        sys.exit(1)

    notify(f"[Claude auto-triage]\n{message}")
    print("sent")


if __name__ == "__main__":
    main()
