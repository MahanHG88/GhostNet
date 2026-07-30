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
import clientfp
import fpmemory

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

GREASE_VALUES = {
    0x0A0A, 0x1A1A, 0x2A2A, 0x3A3A, 0x4A4A, 0x5A5A, 0x6A6A, 0x7A7A,
    0x8A8A, 0x9A9A, 0xAAAA, 0xBABA, 0xCACA, 0xDADA, 0xEAEA, 0xFAFA,
}


def calculate_tls_fingerprints_legacy(raw_bytes):
    """Original JA3/JA4 computation, unchanged. Kept so fingerprints already on the
    blocklist (learned before GREASE-filtering/curve-parsing existed below) keep
    matching - only used for backward-compatible lookups, never for new learning."""
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


def calculate_tls_fingerprints(raw_bytes):
    """Hardened JA3/JA4. Three fixes over the legacy version above:

    1. Uses the real client_version field (legacy hardcoded 771/TLS1.2) and detects the
       true negotiated version from the supported_versions extension when present.
    2. Fills in the elliptic-curve and point-format fields JA3 requires - the legacy
       version always left them blank, silently discarding real distinguishing data
       that was sitting right there in the ClientHello.
    3. Strips GREASE values (RFC 8701) from ciphers/extensions/curves/versions before
       hashing. Without this, an attacker can dodge a ban on an unchanged TLS stack
       just by randomizing one ignorable GREASE slot per connection - verified this
       defeats the legacy hash but leaves this one unchanged.
    """
    if len(raw_bytes) < 45 or raw_bytes[0] != 0x16 or raw_bytes[5] != 0x01:
        return None, None
    try:
        client_version = int.from_bytes(raw_bytes[9:11], 'big')
        session_id_len = raw_bytes[43]
        cipher_offset = 44 + session_id_len
        cipher_len = int.from_bytes(raw_bytes[cipher_offset:cipher_offset+2], byteorder='big')

        ciphers_bytes = raw_bytes[cipher_offset+2:cipher_offset+2+cipher_len]
        ciphers_raw = [int.from_bytes(ciphers_bytes[i:i+2], 'big') for i in range(0, len(ciphers_bytes), 2)]
        ciphers = [str(c) for c in ciphers_raw if c not in GREASE_VALUES]

        comp_offset = cipher_offset + 2 + cipher_len
        comp_len = raw_bytes[comp_offset]

        ext_offset = comp_offset + 1 + comp_len
        extensions, curves, point_formats, alpn, supported_versions = [], [], [], [], []
        if ext_offset + 2 <= len(raw_bytes):
            ext_len = int.from_bytes(raw_bytes[ext_offset:ext_offset+2], 'big')
            ext_bytes = raw_bytes[ext_offset+2:ext_offset+2+ext_len]

            idx = 0
            while idx + 4 <= len(ext_bytes):
                ext_type = int.from_bytes(ext_bytes[idx:idx+2], 'big')
                e_len = int.from_bytes(ext_bytes[idx+2:idx+4], 'big')
                e_body = ext_bytes[idx+4:idx+4+e_len]

                if ext_type not in GREASE_VALUES:
                    extensions.append(str(ext_type))

                if ext_type == 10 and len(e_body) >= 2:  # supported_groups (elliptic curves)
                    glen = int.from_bytes(e_body[0:2], 'big')
                    gbytes = e_body[2:2+glen]
                    curves = [
                        str(int.from_bytes(gbytes[i:i+2], 'big'))
                        for i in range(0, len(gbytes), 2)
                        if int.from_bytes(gbytes[i:i+2], 'big') not in GREASE_VALUES
                    ]
                elif ext_type == 11 and len(e_body) >= 1:  # ec_point_formats
                    flen = e_body[0]
                    point_formats = [str(b) for b in e_body[1:1+flen]]
                elif ext_type == 16 and len(e_body) >= 2:  # ALPN
                    alpn_list_len = int.from_bytes(e_body[0:2], 'big')
                    abytes = e_body[2:2+alpn_list_len]
                    ai = 0
                    while ai < len(abytes):
                        plen = abytes[ai]
                        alpn.append(abytes[ai+1:ai+1+plen].decode('ascii', 'ignore'))
                        ai += 1 + plen
                elif ext_type == 43 and len(e_body) >= 1:  # supported_versions
                    vlen = e_body[0]
                    vbytes = e_body[1:1+vlen]
                    supported_versions = [
                        int.from_bytes(vbytes[i:i+2], 'big')
                        for i in range(0, len(vbytes), 2)
                        if int.from_bytes(vbytes[i:i+2], 'big') not in GREASE_VALUES
                    ]

                idx += 4 + e_len

        real_version = max(supported_versions) if supported_versions else client_version

        ja3_string = "%d,%s,%s,%s,%s" % (
            client_version, ",".join(ciphers), ",".join(extensions),
            ",".join(curves), ",".join(point_formats),
        )
        ja3_hash = hashlib.md5(ja3_string.encode()).hexdigest()

        version_prefix = {0x0301: "t10", 0x0302: "t11", 0x0303: "t12", 0x0304: "t13"}.get(real_version, "t13")
        alpn_tag = hashlib.sha256(alpn[0].encode()).hexdigest()[:2] if alpn else "00"
        ja4_a = f"{version_prefix}{len(ciphers):02d}{len(extensions):02d}{alpn_tag}"
        ja4_b = hashlib.sha256(",".join(sorted(ciphers)).encode()).hexdigest()[:12]
        ja4_c = hashlib.sha256(",".join(sorted(extensions + curves)).encode()).hexdigest()[:12]
        ja4_hash = f"{ja4_a}_{ja4_b}_{ja4_c}"

        return ja3_hash, ja4_hash
    except Exception:
        return None, None

def log_attack_to_json(ip, port, payload, ja3=None, ja4=None, cfp=None):
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
        # Non-TLS client identity (HTTP header order/casing, SSH banner, RDP shape,
        # structural probe signature) — see clientfp.py.
        "client_fingerprint": (cfp or {}).get("fp"),
        "client_fp_family": (cfp or {}).get("family"),
        "client_fp_detail": (cfp or {}).get("detail"),
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
            subprocess.run(["sudo", "ufw", "deny", "from", ip], check=True)
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
        ja3_legacy, ja4_legacy = calculate_tls_fingerprints_legacy(raw_buffer)
        # JA3/JA4 only exist for a TLS ClientHello (~4% of real traffic here). Everything
        # else — plaintext HTTP, SSH, RDP, raw probes — is identified by clientfp instead,
        # so rotating IP or VPN exit no longer buys the attacker a clean slate.
        cfp = clientfp.fingerprint(raw_buffer)
        cfp_id = cfp.get("fp")
        cfp_legacy_id = cfp.get("legacy_fp")
        banned_sigs = load_fingerprints()

        # is_bannable() gates whether a signature may be LEARNED, never whether an
        # already-blocklisted one is ENFORCED. A signature promoted on evidence
        # (fpmemory) is generic by construction, so gating the match on is_bannable
        # would leave it on the blocklist but never actually block anything.
        #
        # Both a hardened id (ja3/ja4/cfp_id) and its pre-hardening legacy form are
        # checked, so fingerprints already on the blocklist from before GREASE-filtering/
        # HASSH/header-value hardening keep matching. Only the hardened form is ever
        # written to the blocklist below, so it migrates forward over time.
        known_bad = (
            (ja3 and ja3 in banned_sigs)
            or (ja4 and ja4 in banned_sigs)
            or (ja3_legacy and ja3_legacy in banned_sigs)
            or (ja4_legacy and ja4_legacy in banned_sigs)
            or (cfp_id and cfp_id in banned_sigs)
            or (cfp_legacy_id and cfp_legacy_id in banned_sigs)
        )
        if known_bad:
            block_ip(ip)
            h = log_event(
                "fingerprint-block", ip,
                f"Blocked on first contact: known-bad client signature ({clientfp.describe(cfp)})",
            )
            notify(
                f"Repeat actor on a new IP\n{ip}:{port}\n{clientfp.describe(cfp)}"
                + (f"\nledger: {h[:12]}" if h else "")
            )
            conn.close()
            return

        decoded_payload = raw_buffer.decode('utf-8', errors='ignore')
        log_attack_to_json(ip, port, decoded_payload, ja3, ja4, cfp)
        h = log_event(
            "capture", ip,
            f"Honeypot capture on port {port} (JA3 {ja3 or '-'}, JA4 {ja4 or '-'}, "
            f"client {cfp_id or '-'})",
        )
        notify(
            f"Honeypot capture\nIP: {ip}:{port}\nJA3: {ja3 or '-'}\nJA4: {ja4 or '-'}\n"
            f"Client: {clientfp.describe(cfp)}" + (f"\nledger: {h[:12]}" if h else "")
        )

        is_critical_payload = any(bad_string in decoded_payload for bad_string in MALICIOUS_PAYLOADS)

        # Remember every sighting. A signature too generic to ban on sight can still earn
        # a ban by behaviour — the same signature turning up from many IPs attached to
        # malicious payloads is the exact shape of an actor rotating addresses.
        if cfp_id:
            entry = fpmemory.record(
                cfp_id, ip,
                family=cfp.get("family", "?"),
                malicious=is_critical_payload,
                label=clientfp.describe(cfp),
            )
            if fpmemory.should_promote(entry) and cfp_id not in banned_sigs:
                banned_sigs.append(cfp_id)
                save_fingerprints(banned_sigs)
                fpmemory.mark_promoted(cfp_id)
                n_ips = fpmemory.distinct_ips(entry)
                log_event(
                    "fingerprint-promote", ip,
                    f"Promoted {cfp_id} to blocklist: seen from {n_ips} IPs, "
                    f"{entry.get('malicious', 0)} malicious ({clientfp.describe(cfp)})",
                )
                notify(
                    f"IP-hopping actor identified\n{clientfp.describe(cfp)}\n"
                    f"same signature from {n_ips} distinct IPs — signature now blocked"
                )

        if is_critical_payload or ja4 is not None:
            block_ip(ip)
            if ja3 and ja3 not in banned_sigs:
                banned_sigs.append(ja3)
            if ja4 and ja4 not in banned_sigs:
                banned_sigs.append(ja4)
            # Only record a non-TLS signature when it is specific enough to attribute to
            # one actor — these bans are resold via the threat-intel API, so a generic
            # signature would blocklist innocent clients and poison customer data.
            if cfp_id and clientfp.is_bannable(cfp) and cfp_id not in banned_sigs:
                banned_sigs.append(cfp_id)
                log_event("fingerprint-learn", ip, f"Learned client signature {cfp_id} ({clientfp.describe(cfp)})")
            save_fingerprints(banned_sigs)
            conn.close()
            return
            
        IP_HISTORY[ip] = IP_HISTORY.get(ip, 0) + 1
        if IP_HISTORY[ip] >= 5:
            block_ip(ip)
            # A persistent repeat offender is exactly the actor worth remembering by
            # signature — otherwise the next IP they use starts from zero again.
            if cfp_id and clientfp.is_bannable(cfp) and cfp_id not in banned_sigs:
                banned_sigs.append(cfp_id)
                save_fingerprints(banned_sigs)
                log_event("fingerprint-learn", ip, f"Learned client signature {cfp_id} after repeat contact")
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

