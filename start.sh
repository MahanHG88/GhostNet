#!/bin/bash
echo "[*] Starting GhostNet Architecture..."

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