import socket
import json
import os
import time
import subprocess
import threading
import requests
import hashlib

from telegram_notify import notify
from tamperlog import log_event

LOG_FILE = "raw_attacks.json"
BANNED_FILE = "banned_ips.txt"
FINGERPRINT_DB = "banned_fingerprints.json"
IP_HISTORY = {"banned": []}

MALICIOUS_PAYLOADS = [
    "mstshash=Administr", 
    "wp-admin", 
    "jndi:ldap", 
    "wget ", 
    "curl ", 
    "nmap", 
    "masscan", 
    "../"
]

if os.path.exists(BANNED_FILE):
    with open(BANNED_FILE, "r") as f:
        IP_HISTORY["banned"] = [line.strip() for line in f if line.strip()]

def load_fingerprints():
    if os.path.exists(FINGERPRINT_DB):
        with open(FINGERPRINT_DB, "r") as f:
            return json.load(f)
    return []

def save_fingerprints(data):
    with open(FINGERPRINT_DB, "w") as f:
        json.dump(data, f, indent=4)

def check_vpn_infrastructure(ip):
    try:
        res = requests.get(f"https://ipinfo.io/{ip}/json", timeout=2)
        if res.status_code == 200:
            org = res.json().get("org", "").lower()
            providers = ["hosting", "datacenter", "vpn", "ovh", "digitalocean", "aws", "linode"]
            return any(p in org for p in providers)
    except:
        pass
    return False

def calculate_tls_fingerprints(raw_bytes):
    if len(raw_bytes) < 45 or raw_bytes[0] != 0x16 or raw_bytes[5] != 0x01:
        return None, None
    try:
        session_id_len = raw_bytes[43]
        cipher_offset = 44 + session_id_len
        cipher_len = int.from_bytes(raw_bytes[cipher_offset:cipher_offset+2], byteorder='big')
        
        ciphers_bytes = raw_bytes[cipher_offset+2:cipher_offset+2+cipher_len]
        ciphers = [str(int.from_bytes(ciphers_bytes[i:i+2], 'big')) for i in range(0, len(ciphers_bytes), 2)]
        
        comp_offset = cipher_offset + 2 + cipher_len
        comp_len = raw_bytes[comp_offset]
        
        ext_offset = comp_offset + 1 + comp_len
        if ext_offset + 2 <= len(raw_bytes):
            ext_len = int.from_bytes(raw_bytes[ext_offset:ext_offset+2], 'big')
            ext_bytes = raw_bytes[ext_offset+2:ext_offset+2+ext_len]
            
            extensions = []
            idx = 0
            while idx + 4 <= len(ext_bytes):
                ext_type = int.from_bytes(ext_bytes[idx:idx+2], 'big')
                extensions.append(str(ext_type))
                e_len = int.from_bytes(ext_bytes[idx+2:idx+4], 'big')
                idx += 4 + e_len
        else:
            extensions = []

        ja3_string = f"771,{','.join(ciphers)},{','.join(extensions)},,"
        ja3_hash = hashlib.md5(ja3_string.encode()).hexdigest()
        
        ja4_a = f"t13{len(ciphers)}{len(extensions)}"
        ja4_b = hashlib.sha256(",".join(sorted(ciphers)).encode()).hexdigest()[:12]
        ja4_c = hashlib.sha256(",".join(sorted(extensions)).encode()).hexdigest()[:12]
        ja4_hash = f"{ja4_a}_{ja4_b}_{ja4_c}"
        
        return ja3_hash, ja4_hash
    except:
        return None, None

def log_attack_to_json(ip, port, payload, ja3=None, ja4=None):
    data_list = []
    target_file = "enriched_attacks.json"
    if os.path.exists(target_file) and os.path.getsize(target_file) > 0:
        try:
            with open(target_file, "r") as f:
                data_list = json.load(f)
        except:
            data_list = []

    new_entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "attacker_ip": ip,
        "source_port": port,
        "payload": str(payload).strip(),
        "ja3_fingerprint": ja3,
        "ja4_fingerprint": ja4,
        "attack_category": "Automated Scanner",
        "severity": "Critical" if (ja4 or "mstshash" in str(payload)) else "Medium",
        "country": "Unknown"
    }
    data_list.append(new_entry)
    with open(target_file, "w") as f:
        json.dump(data_list, f, indent=4)

def block_ip(ip):
    if ip not in IP_HISTORY["banned"]:
        try:
            # iptables, not ufw: ufw was found inactive (Status: inactive) on this
            # host, meaning every ban this function issued was silently unenforced.
            # iptables is what defender.py already uses and takes effect immediately
            # regardless of ufw's enabled/disabled state.
            subprocess.run(["sudo", "iptables", "-A", "INPUT", "-s", ip, "-j", "DROP"], check=True)
        except:
            pass
        with open(BANNED_FILE, "a") as f:
            f.write(ip + "\n")
        IP_HISTORY["banned"].append(ip)
        h = log_event("ban", "honeypot", f"Banned IP {ip}")
        notify(f"Honeypot banned IP\n{ip}" + (f"\nledger: {h[:12]}" if h else ""))

def handle_connection(conn, addr):
    ip = addr[0]
    port = addr[1]
    
    if ip in IP_HISTORY["banned"]:
        conn.close()
        return

    if check_vpn_infrastructure(ip):
        block_ip(ip)
        conn.close()
        return

    try:
        conn.settimeout(2.0)
        raw_buffer = conn.recv(2048)
        if not raw_buffer:
            conn.close()
            return
            
        ja3, ja4 = calculate_tls_fingerprints(raw_buffer)
        banned_sigs = load_fingerprints()
        
        if (ja3 and ja3 in banned_sigs) or (ja4 and ja4 in banned_sigs):
            block_ip(ip)
            conn.close()
            return
            
        decoded_payload = raw_buffer.decode('utf-8', errors='ignore')
        log_attack_to_json(ip, port, decoded_payload, ja3, ja4)
        h = log_event("capture", ip, f"Honeypot capture on port {port} (JA3 {ja3 or '-'}, JA4 {ja4 or '-'})")
        notify(f"Honeypot capture\nIP: {ip}:{port}\nJA3: {ja3 or '-'}\nJA4: {ja4 or '-'}" + (f"\nledger: {h[:12]}" if h else ""))

        is_critical_payload = any(bad_string in decoded_payload for bad_string in MALICIOUS_PAYLOADS)
        
        if is_critical_payload or ja4 is not None:
            block_ip(ip)
            if ja3 and ja3 not in banned_sigs:
                banned_sigs.append(ja3)
            if ja4 and ja4 not in banned_sigs:
                banned_sigs.append(ja4)
            save_fingerprints(banned_sigs)
            conn.close()
            return
            
        IP_HISTORY[ip] = IP_HISTORY.get(ip, 0) + 1
        if IP_HISTORY[ip] >= 5:
            block_ip(ip)
            conn.close()
            return
        
        conn.settimeout(None) 
        while True:
            try:
                conn.send(b"\x00")
                time.sleep(2)
            except (socket.error, BrokenPipeError):
                break
            
    except Exception:
        pass
    finally:
        conn.close()

def start_honeypot():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', 2222))
    s.listen(100)
    
    while True:
        conn, addr = s.accept()
        threading.Thread(target=handle_connection, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    start_honeypot()

