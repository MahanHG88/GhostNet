import json
import time
import os
import subprocess
import fcntl

from telegram_notify import notify
from tamperlog import log_event

ENRICHED_FILE = "enriched_attacks.json"
BANNED_IPS_FILE = "banned_ips.txt"
SCAN_HITS_FILE = "api_scan_hits.jsonl"
SCAN_HIT_THRESHOLD = 3
SCAN_HIT_WINDOW_SECONDS = 600
SCAN_HIT_RETENTION_SECONDS = 86400

def load_banned_ips():
    if os.path.exists(BANNED_IPS_FILE):
        with open(BANNED_IPS_FILE, "r") as f:
            return set(line.strip() for line in f)
    return set()

def save_banned_ip(ip):
    with open(BANNED_IPS_FILE, "a") as f:
        f.write(f"{ip}\n")

def block_ip(ip):
    print(f"[!] INITIATING BAN PROTOCOL: Executing iptables drop for {ip}")
    command = f"sudo iptables -A INPUT -s {ip} -j DROP"
    subprocess.run(command, shell=True)

def check_api_scan_hits(banned_ips):
    """Repeated secret/config-scan paths hit on the live API (port 8000) never go
    through the honeypot's AI enrichment - they're deterministically malicious, so
    ban on hit count alone instead of waiting on severity classification."""
    if not os.path.exists(SCAN_HITS_FILE):
        return

    now = time.time()
    counts = {}
    kept_lines = []
    try:
        with open(SCAN_HITS_FILE, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except Exception:
                        continue
                    ts = entry.get("timestamp", 0)
                    if now - ts > SCAN_HIT_RETENTION_SECONDS:
                        continue
                    kept_lines.append(line)
                    if now - ts > SCAN_HIT_WINDOW_SECONDS:
                        continue
                    ip = entry.get("ip")
                    if not ip or ip == "127.0.0.1" or ip in banned_ips:
                        continue
                    counts[ip] = counts.get(ip, 0) + 1

                f.seek(0)
                f.truncate()
                f.write("\n".join(kept_lines) + ("\n" if kept_lines else ""))
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        return

    for ip, count in counts.items():
        if count >= SCAN_HIT_THRESHOLD:
            block_ip(ip)
            save_banned_ip(ip)
            banned_ips.add(ip)
            print(f"[+] {ip} neutralized (API secret-scan pattern x{count}).")
            h = log_event("ban", "defender-api-scan", f"Firewall-banned {ip} (secret-scan pattern hit {count}x on live API)")
            notify(f"Active defense: firewall-banned {ip}\nReason: repeated secret/config scan on live API ({count} hits)" + (f"\nledger: {h[:12]}" if h else ""))


def scan_and_defend():
    print("??? GhostNet Active Defense Daemon Online...")

    while True:
        banned_ips = load_banned_ips()

        check_api_scan_hits(banned_ips)

        if os.path.exists(ENRICHED_FILE):
            try:
                with open(ENRICHED_FILE, "r") as f:
                    data = json.load(f)
                
                for attack in data:
                    ip = attack.get("attacker_ip")
                    severity = attack.get("severity")
                    
                    if ip == "127.0.0.1" or ip in banned_ips:
                        continue
                        
                    if severity in ["High", "Critical"]:
                        block_ip(ip)
                        save_banned_ip(ip)
                        print(f"[+] {ip} successfully neutralized.")
                        h = log_event("ban", "defender", f"Firewall-banned {ip} (severity {severity})")
                        notify(f"Active defense: firewall-banned {ip}\nSeverity: {severity}" + (f"\nledger: {h[:12]}" if h else ""))
                        
            except Exception as e:
                pass

        time.sleep(30)

if __name__ == "__main__":
    scan_and_defend()