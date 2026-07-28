from fastapi import FastAPI, Header, HTTPException, Request, status
import json
import os
import requests
import hashlib

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

POW_DIFFICULTY = 4

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

def verify_proof_of_work(identifier: str, nonce: str, difficulty: int = POW_DIFFICULTY) -> bool:
    if not nonce or not identifier:
        return False
    identifier = identifier.strip()
    nonce = str(nonce).strip()
    target = "0" * difficulty
    hash_result = hashlib.sha256(f"{identifier}{nonce}".encode()).hexdigest()
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

    return {
        "identifier": target_user_id.strip(),
        "difficulty": POW_DIFFICULTY,
        "algorithm": "sha256",
        "instructions": (
            "Find any string `nonce` such that "
            "sha256(identifier + nonce) starts with `difficulty` zero hex "
            "characters. Send it back as the X-PoW-Nonce header on your "
            "/api/threats/blocklist request, alongside your X-API-Key."
        )
    }

@app.get("/api/threats/blocklist")
async def get_threat_blocklist(
    x_api_key: str = Header(None, alias="X-API-Key"),
    x_pow_nonce: str = Header(None, alias="X-PoW-Nonce"),
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

    if not verify_proof_of_work(target_user_id, x_pow_nonce, difficulty=POW_DIFFICULTY):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cryptographic computation verification failed. Complete Proof-of-Work execution requirements."
        )
        
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


