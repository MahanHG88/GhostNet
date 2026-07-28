import json
import time
import os
import subprocess

from telegram_notify import notify

ENRICHED_FILE = "enriched_attacks.json"
BANNED_IPS_FILE = "banned_ips.txt"

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

def scan_and_defend():
    print("??? GhostNet Active Defense Daemon Online...")
    
    while True:
        banned_ips = load_banned_ips()
        
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
                        notify(f"Active defense: firewall-banned {ip}\nSeverity: {severity}")
                        
            except Exception as e:
                pass

        time.sleep(30)

if __name__ == "__main__":
    scan_and_defend()