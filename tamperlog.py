import os
import json
import hashlib
import fcntl
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEDGER_FILE = os.path.join(BASE_DIR, "security_ledger.jsonl")
GENESIS_HASH = "0" * 64


def _compute_hash(seq, ts, category, actor, action, prev_hash):
    payload = f"{seq}|{ts}|{category}|{actor}|{action}|{prev_hash}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_last_entry(f):
    last = None
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            last = json.loads(line)
        except Exception:
            pass
    return last


def log_event(category, actor, action):
    """Append a hash-chained, tamper-evident entry to the ledger.
    Returns the new entry's hash, or None if the write failed (never raises)."""
    try:
        with open(LEDGER_FILE, "a+", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                last = _read_last_entry(f)
                seq = (last["seq"] + 1) if last else 1
                prev_hash = last["hash"] if last else GENESIS_HASH
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                entry_hash = _compute_hash(seq, ts, category, actor, action, prev_hash)
                entry = {
                    "seq": seq,
                    "ts": ts,
                    "category": category,
                    "actor": actor,
                    "action": action,
                    "prev_hash": prev_hash,
                    "hash": entry_hash,
                }
                f.write(json.dumps(entry) + "\n")
                f.flush()
                os.fsync(f.fileno())
                return entry_hash
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception as e:
        print(f"[tamperlog error] {e}")
        return None


def verify_ledger():
    """Walk the whole ledger and confirm the hash chain is intact.
    Returns (ok: bool, message: str)."""
    if not os.path.exists(LEDGER_FILE):
        return True, "Ledger is empty — nothing to verify yet."

    prev_hash = GENESIS_HASH
    count = 0
    with open(LEDGER_FILE, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                return False, f"Line {line_no} isn't valid JSON — the ledger was truncated or corrupted."

            if entry.get("prev_hash") != prev_hash:
                return False, (
                    f"Chain broken at seq {entry.get('seq')} (line {line_no}): its prev_hash doesn't "
                    f"match the previous entry's hash. A line was likely inserted, removed, or reordered."
                )

            expected = _compute_hash(
                entry.get("seq"), entry.get("ts"), entry.get("category"),
                entry.get("actor"), entry.get("action"), entry.get("prev_hash"),
            )
            if expected != entry.get("hash"):
                return False, (
                    f"Entry at seq {entry.get('seq')} (line {line_no}) has been altered — its content "
                    f"no longer matches its recorded hash."
                )

            prev_hash = entry["hash"]
            count += 1

    return True, f"Chain intact — {count} entries verified, ending at hash {prev_hash[:16]}..."


if __name__ == "__main__":
    ok, message = verify_ledger()
    print(("[OK] " if ok else "[TAMPERED] ") + message)
