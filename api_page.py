import streamlit as st
import secrets
import time
import pandas as pd

if "api_keys" not in st.session_state:
    st.session_state.api_keys = [
        {"name": "Production_SIEM", "key": "gk_live_8f3b...1a9e", "created": "2026-06-12", "status": "Active"},
        {"name": "Dev_Testing", "key": "gk_test_2c9d...7b4f", "created": "2026-07-01", "status": "Active"}
    ]

st.set_page_config(page_title="GhostNet API Portal", layout="wide")

st.title("?? Threat Intelligence API Portal")
st.markdown("Manage your endpoints, access keys, and live telemetry ingestion feeds.")

st.divider()

col1, col2, col3, col4 = st.columns(4)
col1.metric(label="Total API Requests (24h)", value="14,282", delta="+12%")
col2.metric(label="Average Latency", value="42ms", delta="-4ms")
col3.metric(label="Active Webhooks", value="3")
col4.metric(label="Rate Limit Status", value="94.8% Remaining")

st.divider()

left_col, right_col = st.columns([3, 2])

with left_col:
    st.subheader("?? API Access Keys")
    
    with st.expander("? Generate New API Key"):
        with st.form("key_form", clear_on_submit=True):
            key_name = st.text_input("Key Label / Application Name", placeholder="e.g., Corporate Splunk Cluster")
            submitted = st.form_submit_button("Generate")
            if submitted and key_name:
                new_raw_key = f"gk_live_{secrets.token_hex(16)}"
                st.session_state.api_keys.append({
                    "name": key_name,
                    "key": f"{new_raw_key[:12]}...{new_raw_key[-4:]}",
                    "created": time.strftime("%Y-%m-%d"),
                    "status": "Active"
                })
                st.success(f"Key generated successfully!")
                st.code(new_raw_key, language="text")
                st.warning("Copy this token now. You won't be able to see it again.")

    df_keys = pd.DataFrame(st.session_state.api_keys)
    st.dataframe(df_keys, use_container_width=True, hide_index=True)

with right_col:
    st.subheader("?? API Usage Quotas")
    
    usage_data = pd.DataFrame({
        "Endpoint": ["/v1/attacks/raw", "/v1/attacks/enriched", "/v1/intel/reputation"],
        "Hits": [8432, 5120, 730],
        "Quota Used": ["42.1%", "25.6%", "7.3%"]
    })
    st.table(usage_data)

st.divider()

st.subheader("?? Developer Integration Reference")

with st.expander("?? How the Proof-of-Work (PoW) gate works — read this first", expanded=True):
    st.markdown("""
Every call to `/api/threats/blocklist` needs **two** headers, not one:

| Header | What it is |
|---|---|
| `X-API-Key` | Your account's key from the table above |
| `X-PoW-Nonce` | A value *you* compute locally for this specific request |

The nonce isn't something you're given — you have to find it, and that's the point: it costs
a legitimate client a few milliseconds of CPU time, but costs an attacker firing millions of
requests a lot more.

**The flow is three steps:**

1. **Ask what to solve.** `GET /api/pow-challenge` with just your `X-API-Key`. It returns your
   `identifier` (your account email, exactly as registered) and the current `difficulty`.
2. **Solve it locally.** Try `nonce = "0"`, `"1"`, `"2"`, ... and compute
   `sha256(identifier + nonce)` each time, until the resulting hex hash starts with
   `difficulty` zeros. At difficulty 4 this takes a few thousand tries — milliseconds on any
   machine.
3. **Send the real request.** `GET /api/threats/blocklist` with both `X-API-Key` and
   `X-PoW-Nonce` set to the winning nonce.

A fresh nonce must be solved for every request — you can't reuse one. If you get back
`400 Cryptographic computation verification failed`, it almost always means one of:
the nonce wasn't included, it was computed against the wrong identifier string (double-check
you copied your registered email exactly, no extra spaces), or difficulty changed since you
last checked `/api/pow-challenge`.
    """)

doc_tab1, doc_tab2 = st.tabs(["cURL / Shell", "Python Ingestion"])

with doc_tab1:
    st.markdown("**Fetch Latest Threat Blocklist (with Proof-of-Work)**")
    st.code("""
API_KEY="YOUR_API_KEY"
BASE_URL="https://api.ghostnet.intel"

# 1. Ask the server what to solve
CHALLENGE=$(curl -s -X GET "$BASE_URL/api/pow-challenge" -H "X-API-Key: $API_KEY")
IDENTIFIER=$(echo "$CHALLENGE" | jq -r '.identifier')
DIFFICULTY=$(echo "$CHALLENGE" | jq -r '.difficulty')
TARGET=$(printf '0%.0s' $(seq 1 "$DIFFICULTY"))

# 2. Brute-force a nonce locally: sha256(identifier + nonce) must start with $TARGET zeros
NONCE=0
while true; do
  HASH=$(printf '%s%s' "$IDENTIFIER" "$NONCE" | sha256sum | cut -d' ' -f1)
  case "$HASH" in
    "$TARGET"*) break ;;
  esac
  NONCE=$((NONCE + 1))
done
echo "Solved nonce=$NONCE (hash=$HASH)"

# 3. Make the real request with both headers
curl -X GET "$BASE_URL/api/threats/blocklist" \\
  -H "X-API-Key: $API_KEY" \\
  -H "X-PoW-Nonce: $NONCE" \\
  -H "Accept: application/json"
    """, language="bash")
    st.caption("Requires `jq` for parsing JSON. On most Linux/macOS shells `sha256sum` is built in (macOS: use `shasum -a 256` instead).")

with doc_tab2:
    st.markdown("**Automated Threat Feed Polling Daemon**")
    st.code("""
import hashlib
import requests

BASE_URL = "https://api.ghostnet.intel"
API_KEY = "YOUR_API_KEY"


def get_pow_challenge():
    \"\"\"Step 1: ask the server what identifier + difficulty to solve for.\"\"\"
    resp = requests.get(
        f"{BASE_URL}/api/pow-challenge",
        headers={"X-API-Key": API_KEY},
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json()


def solve_pow(identifier: str, difficulty: int) -> str:
    \"\"\"Step 2: brute-force a nonce such that sha256(identifier + nonce)
    starts with `difficulty` zero hex characters. Trivial for a real client
    (milliseconds at difficulty 4), expensive at scale for a scraper/bot.\"\"\"
    target = "0" * difficulty
    counter = 0
    while True:
        nonce = str(counter)
        digest = hashlib.sha256(f"{identifier}{nonce}".encode()).hexdigest()
        if digest.startswith(target):
            return nonce
        counter += 1


def fetch_threat_feed():
    \"\"\"Step 3: solve a fresh PoW nonce and use it on the real request.\"\"\"
    challenge = get_pow_challenge()
    nonce = solve_pow(challenge["identifier"], challenge["difficulty"])

    headers = {
        "X-API-Key": API_KEY,
        "X-PoW-Nonce": nonce,
        "Accept": "application/json",
    }
    try:
        response = requests.get(
            f"{BASE_URL}/api/threats/blocklist", headers=headers, timeout=5
        )
        if response.status_code == 200:
            attacks = response.json()
            for attack in attacks:
                print(f"[!] Target Alert: {attack.get('attacker_ip')} -> {attack.get('attack_category')}")
        else:
            print(f"[!] Request failed ({response.status_code}): {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Connection error: {e}")


if __name__ == "__main__":
    fetch_threat_feed()
    """, language="python")