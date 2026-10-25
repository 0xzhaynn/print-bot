#!/data/data/com.termux/files/usr/bin/bash
# Connects DEGEN AUTONOMOUS to your Telegram bot, then restarts the paper bot.
cd ~/degen-autonomous || exit 1
echo "Paste your bot token from BotFather, then press Enter (it stays hidden):"
read -s TOKEN
echo
TOKEN="$(echo "$TOKEN" | tr -d '[:space:]')"
CHAT=$(python - "$TOKEN" <<'PY'
import sys, httpx
t = sys.argv[1]
r = httpx.get(f"https://api.telegram.org/bot{t}/getUpdates", timeout=15).json()
if not r.get("ok"): print("ERR:" + r.get("description", "bad token")); sys.exit()
ids = [u["message"]["chat"]["id"] for u in r["result"] if "message" in u]
print(ids[-1] if ids else "ERR:no messages yet")
PY
)
case "$CHAT" in
  ERR:*) echo "Problem: ${CHAT#ERR:}"; echo "Open the bot in Telegram, send it 'hi', then run this script again."; exit 1;;
esac
printf "TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\n" "$TOKEN" "$CHAT" > .env
chmod 600 .env
python - "$TOKEN" "$CHAT" <<'PY'
import sys, httpx
httpx.post(f"https://api.telegram.org/bot{sys.argv[1]}/sendMessage",
           json={"chat_id": sys.argv[2], "text": "DEGEN AUTONOMOUS connected. Paper mode. Trade alerts will land here."})
PY
pkill -f termux_start.sh; pkill -f run_paper.py; sleep 2
nohup bash termux_start.sh >/dev/null 2>&1 &
echo "Done. Check Telegram for the test message. The bot has restarted with alerts on."
