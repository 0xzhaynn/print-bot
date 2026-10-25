#!/usr/bin/env bash
# DEGEN AUTONOMOUS installer for Ubuntu (Oracle Always Free). Paper mode only.
set -e
sudo apt-get update -y && sudo apt-get install -y python3-venv unzip
cd ~/degen-autonomous
python3 -m venv .venv && . .venv/bin/activate && pip install -q httpx pyyaml
[ -f .env ] || printf "TELEGRAM_BOT_TOKEN=\nTELEGRAM_CHAT_ID=\n" > .env
sudo tee /etc/systemd/system/degen.service >/dev/null <<UNIT
[Unit]
Description=DEGEN AUTONOMOUS paper bot
After=network-online.target
[Service]
User=$USER
WorkingDirectory=$HOME/degen-autonomous
EnvironmentFile=$HOME/degen-autonomous/.env
ExecStart=$HOME/degen-autonomous/.venv/bin/python -u run_paper.py
Restart=always
RestartSec=30
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload && sudo systemctl enable --now degen
echo "Installed. Logs: journalctl -u degen -f"
