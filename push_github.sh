#!/data/data/com.termux/files/usr/bin/bash
# Push PRINT to github.com/0xzhaynn/print-bot. Secrets (.env), databases and logs are excluded by .gitignore.
set -e
cd "$(dirname "$0")"
pkg install -y git gh >/dev/null 2>&1 || true
gh auth status >/dev/null 2>&1 || gh auth login -h github.com -p https -w
gh auth setup-git
[ -d .git ] || git init -b main
git config user.name "0xzhaynn"
git config user.email "zaneantigha@gmail.com"
git add -A
git commit -m "PRINT: Solana momentum paper-trading bot" || true
git branch -M main
git remote remove origin 2>/dev/null || true
git remote add origin https://github.com/0xzhaynn/print-bot.git
git push -u origin main || { git pull --rebase --allow-unrelated-histories origin main && git push -u origin main; }
echo "Done: https://github.com/0xzhaynn/print-bot"
