import json
import requests
import os
import time

from telegram_notify import notify

def load_env_file(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

load_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

if not os.environ.get("OPENROUTER_API_KEY"):
    raise RuntimeError("OPENROUTER_API_KEY not set. Add it to /root/Kharazmi/.env")

OPENROUTER_MODEL = "openai/gpt-oss-20b:free"

INPUT_FILE = "raw_attacks.json"
OUTPUT_FILE = "enriched_attacks.json"

def call_openrouter(prompt):
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        json={"model": OPENROUTER_MODEL, "messages": [{"role": "user", "content": prompt}]},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def get_ip_metadata(ip):
    try:
        response = requests.get(f"http://ip-api.com/json/{ip}", timeout=3)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "success":
                return {
                    "country": data.get("country", "Unknown"),
                    "city": data.get("city", "Unknown"),
                    "isp": data.get("isp", "Unknown")
                }
    except:
        pass
    return {"country": "Unknown", "city": "Unknown", "isp": "Unknown"}

def analyze_payload_with_ai(payload):
    if not payload or len(payload) < 2:
        return "Automated Scanner", "Low"
        
    prompt = f"""Analyze this network payload and output ONLY valid JSON.
    Rules:
    - If gibberish/TLS: Category "Recon / SSL Scan", Severity "Low"
    - If login attempts: Category "Credential Brute Force", Severity "High"
    - If commands (wget/curl/rm): Category "Exploit Attempt", Severity "Critical"
    
    Payload: {payload}
    Output format: {{"attack_category": "...", "severity": "...", "summary": "..."}}"""
    
    try:
        text = call_openrouter(prompt).strip().replace("```json", "").replace("```", "")
        result = json.loads(text)
        return result.get("attack_category", "Unknown"), result.get("severity", "Medium")
    except:
        return "Unknown Attempt", "Medium"

def run_engine():
    print("[*] Enrichment Engine Online.")
    while True:
        if not os.path.exists(INPUT_FILE):
            time.sleep(5)
            continue

        existing_enriched = {}
        if os.path.exists(OUTPUT_FILE):
            try:
                with open(OUTPUT_FILE, "r") as f:
                    for item in json.load(f):
                        existing_enriched[item["timestamp"]] = item
            except:
                pass

        try:
            with open(INPUT_FILE, "r") as f:
                raw_data = json.load(f)
        except:
            time.sleep(5)
            continue

        new_data_added = False
        for entry in raw_data:
            if entry["timestamp"] not in existing_enriched:
                metadata = get_ip_metadata(entry["attacker_ip"])
                cat, sev = analyze_payload_with_ai(entry.get("payload", ""))
                entry.update(metadata)
                entry["attack_category"] = cat
                entry["severity"] = sev
                existing_enriched[entry["timestamp"]] = entry
                new_data_added = True
                notify(
                    f"Attack classified\nIP: {entry.get('attacker_ip')}\n"
                    f"Country: {metadata.get('country')}\nCategory: {cat}\nSeverity: {sev}"
                )

        if new_data_added:
            with open(OUTPUT_FILE, "w") as f:
                json.dump(list(existing_enriched.values()), f, indent=4)
            print("[+] Data enriched.")
        time.sleep(5)

if __name__ == "__main__":
    run_engine()