# PRINT — Solana Momentum Trading Bot (paper mode)

PRINT is an automated trading bot for new Solana tokens, written in Python. It scans fresh pairs on-chain, filters out rugs with a security gate, enters on momentum, and manages exits — all in **paper mode** with realistic fees, so the strategy is proven before real money is at risk. It runs 24/7 on an Android phone via Termux and reports to Telegram.

## How it works
```
scan (DexScreener) -> security gate -> momentum signal -> risk sizing -> paper fill (Jupiter quotes) -> exits -> Telegram
```
- **Scanner:** pulls new Solana pairs every 60 s and ranks candidates.
- **Security gate:** RugCheck score, liquidity floor, LP burned/locked, top-10 and single-holder concentration, sell-impact test at our size, serial-deployer and ticker-clone checks, off-curve (PDA) detection for holder analysis.
- **Momentum agent:** 1h/5m price change bands, volume-to-liquidity band (filters wash trading), buy/sell ratio, minimum token age.
- **Risk engine:** 2% risk per trade, 20% max position, 3 open positions max, 30% cash reserve, daily-loss and max-drawdown circuit breakers, size halving after a losing streak, SOL-crash pause, 24h no-re-entry after a loss.
- **Paper execution:** fills priced with live Jupiter quotes and charged base fee, priority fee and token-account rent, so P/L matches what a live wallet would see. A shadow tracker records what skipped trades would have done.
- **Exits:** 12% stop, partial take-profit at +25%, final at +60% or 15% trailing stop, 4-hour time stop.
- **Telegram:** entry/exit alerts, `/stats` and `/start` commands, nightly 9 PM WAT report, 3-hour heartbeat, retry + offline queue for dropped messages.

## Layout
```
run_paper.py              main loop
config.yaml               all strategy, risk and fee parameters
degen/data/clients.py     DexScreener, Jupiter, RugCheck, Solana RPC clients
degen/security/gate.py    rug / safety checks
degen/agents/momentum.py  entry signal
degen/execution/paper.py  paper broker with fee model
degen/execution/shadow.py shadow tracking of skipped setups
degen/core/notify.py      Telegram notifier with retry queue
termux_start.sh           always-on runner for Android
```

## Run
```bash
pip install httpx pyyaml
cp .env.example .env      # add your Telegram bot token and chat id
python run_paper.py       # or: bash termux_start.sh on Android
```

## Status
Paper trading only. Live mode is deliberately not wired up; it will only be considered after a meaningful paper track record (goal: 100 closed trades).

Built by Antigha Otu Antigha ([@0xzhaynn](https://github.com/0xzhaynn)).
