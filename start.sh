#!/bin/bash
set -e
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "[*] Bootstrapping GhostNet..."

# 0. Install/verify Python dependencies
pip install -q -r requirements.txt --break-system-packages 2>/dev/null || pip install -q -r requirements.txt

# 0b. Create .env from the template if it doesn't exist yet
if [ ! -f .env ]; then
    cp .env.example .env
    echo "[!] .env was missing — created from .env.example. Fill in real values before relying on auth/email/AI/Telegram features."
fi

# 0c. Generate a self-signed TLS cert for the dashboard if one doesn't exist yet
if [ ! -f server.crt ] || [ ! -f server.key ]; then
    echo "[*] No TLS cert found — generating a self-signed one for the dashboard."
    openssl req -x509 -newkey rsa:2048 -keyout server.key -out server.crt -days 365 -nodes \
        -subj "/CN=ghostnet.local" >/dev/null 2>&1
fi

set +e
echo "[*] Starting GhostNet Architecture..."

# 0d. Re-apply the full ban list to the firewall. iptables rules don't survive a
# reboot on their own, and this file is the source of truth for who's banned, so
# replay it every start (idempotent: skips IPs already dropped, so re-running this
# script without a reboot never piles up duplicate rules).
if [ -f banned_ips.txt ]; then
    echo "[*] Re-applying firewall bans from banned_ips.txt..."
    restored=0
    while IFS= read -r ip; do
        [ -z "$ip" ] && continue
        if ! sudo iptables -C INPUT -s "$ip" -j DROP 2>/dev/null; then
            sudo iptables -A INPUT -s "$ip" -j DROP 2>/dev/null && restored=$((restored + 1))
        fi
    done < <(sort -u banned_ips.txt)
    echo "[+] Restored $restored firewall rule(s) from banned_ips.txt."
fi

# 1. Kill any existing instances to prevent port conflicts
pkill -f honeypot.py
pkill -f enrich.py
pkill -f uvicorn
pkill -f streamlit
pkill -f defender.py
pkill -f telegram_bot.py

# 2. Start core processes in the background
nohup python3 honeypot.py > honeypot.log 2>&1 &
nohup python3 enrich.py > enrich.log 2>&1 &
nohup uvicorn api:app --host 0.0.0.0 --port 8000 > api.log 2>&1 &

# 3. Start Active Defense Daemon
nohup python3 defender.py > defense.log 2>&1 &

# 4. Start Streamlit Dashboard
nohup python3 -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.sslCertFile server.crt --server.sslKeyFile server.key > dashboard.log 2>&1 &

# 5. Start Telegram Admin Bot
nohup python3 -u telegram_bot.py > telegram_bot.log 2>&1 &

echo "[+] All systems and Active Defenses running in the background!"
echo "Dashboard available at: https://$(curl -s ifconfig.me):8501"
echo "API Intelligence Feed available at: http://$(curl -s ifconfig.me):8000/api/threats/blocklist"
