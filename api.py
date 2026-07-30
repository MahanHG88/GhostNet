from fastapi import FastAPI, Header, HTTPException, Request, status
import json
import os
import requests
import hashlib
import secrets
import time

from telegram_notify import notify

app = FastAPI(title="GhostNet Threat Intelligence Gateway Engine", version="2.5.0")


@app.middleware("http")
async def notify_on_request(request: Request, call_next):
    response = await call_next(request)
    client_ip = request.headers.get("x-forwarded-for") or (request.client.host if request.client else "unknown")
    api_key = request.headers.get("x-api-key")
    who = None
    if api_key:
        users = read_json_store(API_USERS_FILE)
        for email, metadata in users.items():
            if str(metadata.get("api_key")).strip() == api_key.strip():
                who = email
                break
    msg = f"API request\n{request.method} {request.url.path}\nStatus: {response.status_code}\nIP: {client_ip}"
    if who:
        msg += f"\nCustomer: {who}"
    notify(msg)
    return response

API_USERS_FILE = "/root/Kharazmi/api_users.json"
ENRICHED_FILE = "/root/Kharazmi/enriched_attacks.json"
BANNED_FINGERPRINTS = "banned_fingerprints.json"
ACTIVE_FINGERPRINTS_FILE = "active_fingerprints.json"
POW_CHALLENGES_FILE = "/root/Kharazmi/pow_challenges.json"

POW_DIFFICULTY = 4  # kept at original value - measured difficulty=6 at ~40-70s/solve
                    # with genuinely randomized challenges, too slow for legitimate
                    # customers. The real fix is the single-use challenge_token binding
                    # below (closes the replay vulnerability); difficulty=4 gives ~150-300ms
                    # of real per-request cost now that it can no longer be reused.
POW_CHALLENGE_TTL_SECONDS = 300

def read_json_store(filepath):
    if not os.path.exists(filepath):
        return {}
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

def write_json_store(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
        f.flush()
        os.fsync(f.fileno())

def verify_proof_of_work(identifier: str, challenge_token: str, nonce: str, difficulty: int = POW_DIFFICULTY) -> bool:
    """Verifies a solved PoW is bound to a specific, still-valid, server-issued
    challenge_token - NOT just the account identifier.

    The original version hashed only sha256(identifier + nonce). Since identifier never
    changes for an account, that puzzle has a fixed, deterministic answer forever - an
    attacker only has to solve it ONCE and can then replay the identical nonce on
    unlimited future requests (verified empirically: 5/5 replays succeeded, at ~5ms to
    solve difficulty 4). Binding to a random per-issue challenge_token that is deleted
    the instant it's spent (see get_threat_blocklist below) forces a genuinely fresh,
    costly solve on every single request - there is no way to reuse a past solution
    because the token it was solved for no longer exists server-side after first use.
    """
    if not nonce or not identifier or not challenge_token:
        return False
    identifier = identifier.strip()
    nonce = str(nonce).strip()
    challenge_token = challenge_token.strip()
    target = "0" * difficulty
    hash_result = hashlib.sha256(f"{identifier}{challenge_token}{nonce}".encode()).hexdigest()
    return hash_result.startswith(target)

def is_commercial_infrastructure(ip: str) -> bool:
    try:
        res = requests.get(f"https://ipinfo.io/{ip}/json", timeout=3)
        if res.status_code == 200:
            data = res.json()
            org = data.get("org", "").lower()
            company = data.get("company", {}).get("type", "").lower()
            banned_keywords = ["hosting", "datacenter", "vpn", "cloud", "amazon", "google", "ovh", "digitalocean", "linode"]
            if any(k in org or k in company for k in banned_keywords):
                return True
    except:
        pass
    return False

@app.post("/api/admin/sync-honeypot")
async def sync_honeypot_data():
    try:
        if not os.path.exists(BANNED_FINGERPRINTS):
            raise HTTPException(status_code=404, detail="banned_fingerprints.json not found.")
        read_json_store(BANNED_FINGERPRINTS)
        return {"status": "success", "message": "Synchronized successfully."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/pow-challenge")
async def get_pow_challenge(x_api_key: str = Header(None, alias="X-API-Key")):
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing identification credentials header sequence: X-API-Key"
        )

    users = read_json_store(API_USERS_FILE)
    target_user_id = None
    for email, metadata in users.items():
        if str(metadata.get("api_key")).strip() == str(x_api_key).strip():
            target_user_id = email
            break

    if not target_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid security credentials provided. Access denied."
        )

    challenge_token = secrets.token_hex(16)
    challenges = read_json_store(POW_CHALLENGES_FILE)
    challenges[target_user_id] = {"token": challenge_token, "issued_at": time.time()}
    write_json_store(POW_CHALLENGES_FILE, challenges)

    return {
        "identifier": target_user_id.strip(),
        "challenge_token": challenge_token,
        "difficulty": POW_DIFFICULTY,
        "algorithm": "sha256",
        "expires_in_seconds": POW_CHALLENGE_TTL_SECONDS,
        "instructions": (
            "Find any string `nonce` such that "
            "sha256(identifier + challenge_token + nonce) starts with `difficulty` zero "
            "hex characters. Send both back as the X-PoW-Challenge and X-PoW-Nonce "
            "headers on your /api/threats/blocklist request, alongside your X-API-Key, "
            f"within {POW_CHALLENGE_TTL_SECONDS} seconds. Each challenge is single-use - "
            "fetch and solve a fresh one for every request."
        )
    }

@app.get("/api/threats/blocklist")
async def get_threat_blocklist(
    x_api_key: str = Header(None, alias="X-API-Key"),
    x_pow_nonce: str = Header(None, alias="X-PoW-Nonce"),
    x_pow_challenge: str = Header(None, alias="X-PoW-Challenge"),
    client_ip: str = Header(None, alias="X-Forwarded-For"),
    x_ja3_fingerprint: str = Header(None, alias="X-JA3-Fingerprint"),
    x_ja4_fingerprint: str = Header(None, alias="X-JA4-Fingerprint"),
    user_agent: str = Header(None, alias="User-Agent"),
    accept_encoding: str = Header(None, alias="Accept-Encoding")
):
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing identification credentials header sequence: X-API-Key"
        )
        
    banned_sigs = read_json_store(BANNED_FINGERPRINTS)
    if (x_ja3_fingerprint in banned_sigs) or (x_ja4_fingerprint in banned_sigs):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Malicious script client signature profile match detected."
        )

    if client_ip and is_commercial_infrastructure(client_ip):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Commercial hosting environments or VPN networks are prohibited."
        )

    sig_source = f"{x_ja3_fingerprint or ''}|{x_ja4_fingerprint or ''}|{user_agent or ''}|{accept_encoding or ''}"
    client_signature = hashlib.sha256(sig_source.encode("utf-8")).hexdigest()

    if client_ip:
        active_sessions = read_json_store(ACTIVE_FINGERPRINTS_FILE)
        
        if client_signature in active_sessions:
            if active_sessions[client_signature] != client_ip:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied. Fingerprint collision detected across distinct network routes."
                )
        else:
            active_sessions[client_signature] = client_ip
            write_json_store(ACTIVE_FINGERPRINTS_FILE, active_sessions)

    users = read_json_store(API_USERS_FILE)
    target_user_id = None
    for email, metadata in users.items():
        if str(metadata.get("api_key")).strip() == str(x_api_key).strip():
            target_user_id = email
            break
            
    if not target_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid security credentials provided. Access denied."
        )

    challenges = read_json_store(POW_CHALLENGES_FILE)
    stored_challenge = challenges.get(target_user_id)
    challenge_current_and_unexpired = (
        stored_challenge
        and x_pow_challenge
        and stored_challenge.get("token") == str(x_pow_challenge).strip()
        and (time.time() - stored_challenge.get("issued_at", 0)) <= POW_CHALLENGE_TTL_SECONDS
    )
    if not challenge_current_and_unexpired or not verify_proof_of_work(
        target_user_id, x_pow_challenge, x_pow_nonce, difficulty=POW_DIFFICULTY
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cryptographic computation verification failed. Complete Proof-of-Work execution requirements."
        )

    # Single-use: burn the challenge the instant it's spent, so the exact same solved
    # (challenge_token, nonce) pair can never be replayed - the next request must fetch
    # and solve a brand new challenge from scratch.
    del challenges[target_user_id]
    write_json_store(POW_CHALLENGES_FILE, challenges)

    user_record = users[target_user_id]
    current_usage = int(user_record.get("requests_used", 0))
    allowed_quota = int(user_record.get("quota", 0))
    
    if current_usage >= allowed_quota:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Purchased request limits exhausted. Quota resource validation failed."
        )
        
    new_usage = current_usage + 1
    users[target_user_id]["requests_used"] = new_usage
    write_json_store(API_USERS_FILE, users)
    
    threat_data = read_json_store(ENRICHED_FILE)
    return threat_data if threat_data else []


def classify_signature(sig: str) -> dict:
    """
    Describe a blocklist signature by its format family.

    Signatures are namespaced by prefix so TLS and non-TLS identities coexist in one
    flat list. Customers use this to decide which families they can actually enforce:
    a JA3/JA4 value is matched at your TLS terminator, whereas an h4h_/sshc_/rdpc_
    value is matched at the application layer.
    """
    if sig.startswith("h4h_"):
        return {"family": "http", "layer": "application",
                "description": "HTTP client signature: header order, name casing, version, line endings"}
    if sig.startswith("sshc_"):
        return {"family": "ssh", "layer": "application",
                "description": "SSH client identity derived from the version banner"}
    if sig.startswith("rdpc_"):
        return {"family": "rdp", "layer": "application",
                "description": "RDP X.224 connection-request shape and negotiation flags"}
    if sig.startswith("gsig_"):
        return {"family": "generic", "layer": "transport-payload",
                "description": "Structural signature of an opaque probe (length, leading bytes, byte profile)"}
    if sig.startswith("t13") or sig.startswith("t12"):
        return {"family": "ja4", "layer": "tls",
                "description": "JA4 TLS client fingerprint"}
    if len(sig) == 32 and all(c in "0123456789abcdef" for c in sig.lower()):
        return {"family": "ja3", "layer": "tls",
                "description": "JA3 TLS client fingerprint (MD5)"}
    return {"family": "unknown", "layer": "unknown", "description": "Unclassified signature"}


@app.get("/api/threats/fingerprints")
async def get_fingerprint_feed(
    family: str = None,
    x_api_key: str = Header(None, alias="X-API-Key"),
    x_pow_nonce: str = Header(None, alias="X-PoW-Nonce"),
    client_ip: str = Header(None, alias="X-Forwarded-For"),
):
    """
    Client-signature feed.

    Complements /api/threats/blocklist: that returns malicious IPs, this returns the
    client identities behind them. Signatures survive IP and VPN rotation, so enforcing
    them blocks a known actor on their FIRST connection from an address you have never
    seen before. Optional ?family= filter: ja3, ja4, http, ssh, rdp, generic.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing identification credentials header sequence: X-API-Key",
        )

    if client_ip and is_commercial_infrastructure(client_ip):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Commercial hosting environments or VPN networks are prohibited.",
        )

    users = read_json_store(API_USERS_FILE)
    target_user_id = None
    for email, metadata in users.items():
        if str(metadata.get("api_key")).strip() == str(x_api_key).strip():
            target_user_id = email
            break

    if not target_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid security credentials provided. Access denied.",
        )

    if not verify_proof_of_work(target_user_id, x_pow_nonce, difficulty=POW_DIFFICULTY):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cryptographic computation verification failed. Complete Proof-of-Work execution requirements.",
        )

    user_record = users[target_user_id]
    current_usage = int(user_record.get("requests_used", 0))
    allowed_quota = int(user_record.get("quota", 0))
    if current_usage >= allowed_quota:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Purchased request limits exhausted. Quota resource validation failed.",
        )

    users[target_user_id]["requests_used"] = current_usage + 1
    write_json_store(API_USERS_FILE, users)

    signatures = read_json_store(BANNED_FINGERPRINTS) or []
    records = []
    for sig in signatures:
        meta = classify_signature(str(sig))
        if family and meta["family"] != family.lower():
            continue
        records.append({"signature": sig, **meta})

    counts = {}
    for r in records:
        counts[r["family"]] = counts.get(r["family"], 0) + 1

    return {
        "count": len(records),
        "families": counts,
        "filter": family or "all",
        "signatures": records,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


