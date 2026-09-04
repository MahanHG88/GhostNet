#!/usr/bin/env bash
# Drop this folder anywhere, run this once, and Mr. Alvarez is up and staying up.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
echo "==> installing from $HERE"

command -v python3 >/dev/null || { echo "python3 is not installed"; exit 1; }
python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt 2>/dev/null \
  || pip3 install --quiet -r requirements.txt \
  || echo "!! could not install requests automatically - run: pip3 install requests"

# Config files: keep whatever is already here, fill in the rest from the examples.
[ -f .env ]            || { cp .env.example .env;                 echo "==> created .env"; }
[ -f persona.md ]      || { cp persona.example.md persona.md;     echo "==> created persona.md"; }
[ -f schedule.json ]   || { cp schedule.json.example schedule.json;   echo "==> created schedule.json"; }
[ -f contacts.json ]   || { cp contacts.json.example contacts.json;   echo "==> created contacts.json"; }
[ -f providers.json ]  || { cp providers.json.example providers.json; echo "==> created providers.json"; }

if [ "$(id -u)" = "0" ]; then
  cat > /etc/systemd/system/alvarez.service <<UNIT
[Unit]
Description=Mr. Alvarez - Telegram message desk
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$HERE
ExecStart=$(command -v python3) "$HERE/bot.py"
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
  systemctl enable alvarez >/dev/null 2>&1 || true
  systemctl restart alvarez
  STARTED=yes
  echo "==> service installed and started"
else
  STARTED=no
  echo "==> not root, so no service was installed. Run him with: python3 bot.py"
fi

echo
echo "=============== checks ==============="
python3 doctor.py || true
echo "======================================"
echo
echo "If a key is missing above and it already exists elsewhere on this box, you do not need to"
echo "copy it: add one line to $HERE/.env pointing at the file that has it, e.g."
echo "    SHARED_ENV=/root/GhostNet/.env,/root/Sonava/.env"
echo "Keys set here win; anything left blank here is filled in from those."

if [ "$STARTED" = yes ]; then
  sleep 2
  if systemctl is-active --quiet alvarez; then
    echo
    echo "Alvarez is running. Watch him work:  journalctl -u alvarez -f"
  else
    echo
    echo "Alvarez did NOT start. Why:  journalctl -u alvarez -n 30 --no-pager"
  fi
fi
