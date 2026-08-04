import json
import os
import time
import fcntl

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCAN_HITS_FILE = os.path.join(BASE_DIR, "api_scan_hits.jsonl")

SECRET_SCAN_PATTERNS = [
    ".env", ".claude/", ".git/config", ".git/head", "wp-admin", "wp-login",
    "phpmyadmin", "id_rsa", ".aws/credentials", ".ssh/", "xmlrpc.php",
    "config.php", "docker-compose.yml", ".npmrc", "secrets.yml", ".htpasswd",
    "key/generate",
]


def is_secret_scan_path(path: str) -> bool:
    p = path.lower()
    return any(pattern in p for pattern in SECRET_SCAN_PATTERNS)


def record_scan_hit(ip: str, path: str, status_code: int):
    """Append-only, lock-protected. No read-modify-write, so concurrent
    uvicorn workers can never clobber each other here."""
    entry = {"timestamp": time.time(), "ip": ip, "path": path, "status": status_code}
    try:
        with open(SCAN_HITS_FILE, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(json.dumps(entry) + "\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        pass
