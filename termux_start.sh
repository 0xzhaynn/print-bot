#!/data/data/com.termux/files/usr/bin/bash
# Run DEGEN AUTONOMOUS paper bot on Android (Termux). Paper mode only.
cd "$(dirname "$0")"
pkg install -y python >/dev/null 2>&1 || true
pip install -q httpx pyyaml
termux-wake-lock
[ -f .env ] && export $(grep -v '^#' .env | xargs)
while true; do python -u run_paper.py >> paper.log 2>&1; echo "restarting..." >> paper.log; sleep 30; done
