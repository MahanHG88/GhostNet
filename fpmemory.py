"""
fpmemory — sighting memory that promotes a client signature to a ban on evidence.

THE PROBLEM THIS SOLVES
-----------------------
clientfp.is_bannable() is deliberately strict: it only auto-bans a signature that is
unusual enough to attribute to one actor on sight (a weird SSH banner, an exotic RDP
shape, a hand-rolled scanner with broken header casing). That strictness is correct —
these bans are resold through the threat-intel API, so a false positive blocklists an
innocent client and poisons customer data.

But it leaves a gap exactly where the IP-hopping problem lives. An attacker driving a
plain `python-requests` or `curl` loop produces a perfectly ordinary HTTP signature.
Banning that signature on first sight would also ban every uptime monitor and CI job on
the internet that uses the same library. So it is never auto-banned, and the attacker
rotates IPs freely.

THE FIX
-------
Don't judge the signature in isolation — judge its behaviour over time. A benign library
signature appears from a handful of IPs doing harmless things. A rotating attacker
produces the SAME signature from many different IPs, repeatedly, attached to malicious
payloads. That pattern is not something a legitimate client reproduces.

So a signature is promoted to a ban once it has been seen:
    - from at least PROMOTE_MIN_IPS distinct IP addresses, AND
    - attached to at least PROMOTE_MIN_MALICIOUS malicious payloads

Both conditions matter. Many IPs alone could be a popular library behind a CDN or NAT;
malicious hits alone could be one noisy host already handled by the IP ban.

This is the mechanism that actually defeats IP hopping for plaintext HTTP: the attacker
gets a few free connections while evidence accumulates, then every subsequent IP running
that tooling is blocked on its first packet.
"""

import json
import os
import time

STORE_FILE = "fingerprint_sightings.json"

PROMOTE_MIN_IPS = 3          # distinct source IPs sharing the signature
PROMOTE_MIN_MALICIOUS = 2    # malicious payloads attributed to it
MAX_TRACKED_IPS = 40         # cap per signature so the store cannot grow without bound


def _load(path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass


def record(fp, ip, family="?", malicious=False, label="", path=STORE_FILE):
    """
    Record one sighting of `fp` from `ip` and return the updated entry.

    Never raises — the honeypot must survive a corrupt or unwritable store.
    """
    if not fp:
        return None
    store = _load(path)
    entry = store.get(fp) or {
        "family": family,
        "label": label,
        "ips": [],
        "hits": 0,
        "malicious": 0,
        "first_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
        "promoted": False,
    }
    entry["hits"] += 1
    entry["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if malicious:
        entry["malicious"] += 1
    if label and not entry.get("label"):
        entry["label"] = label
    if ip and ip not in entry["ips"]:
        if len(entry["ips"]) < MAX_TRACKED_IPS:
            entry["ips"].append(ip)
        else:
            # Keep the count honest even once the sample list is full.
            entry["ips_overflow"] = entry.get("ips_overflow", 0) + 1
    store[fp] = entry
    _save(path, store)
    return entry


def distinct_ips(entry):
    if not entry:
        return 0
    return len(entry.get("ips", [])) + entry.get("ips_overflow", 0)


def should_promote(entry):
    """True when accumulated evidence justifies banning an otherwise-generic signature."""
    if not entry or entry.get("promoted"):
        return False
    return (
        distinct_ips(entry) >= PROMOTE_MIN_IPS
        and entry.get("malicious", 0) >= PROMOTE_MIN_MALICIOUS
    )


def mark_promoted(fp, path=STORE_FILE):
    store = _load(path)
    if fp in store:
        store[fp]["promoted"] = True
        store[fp]["promoted_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save(path, store)


def summary(path=STORE_FILE, limit=20):
    """Signatures ranked by how many distinct IPs share them — the IP-hopping view."""
    store = _load(path)
    rows = []
    for fp, e in store.items():
        rows.append({
            "fingerprint": fp,
            "family": e.get("family", "?"),
            "label": e.get("label", ""),
            "distinct_ips": distinct_ips(e),
            "hits": e.get("hits", 0),
            "malicious": e.get("malicious", 0),
            "promoted": e.get("promoted", False),
            "last_seen": e.get("last_seen", ""),
        })
    rows.sort(key=lambda r: (-r["distinct_ips"], -r["hits"]))
    return rows[:limit]
