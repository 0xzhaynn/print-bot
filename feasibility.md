# DEGEN AUTONOMOUS: Feasibility Assessment

## Bottom line
- **Yes, it can be built without a copy-trading bot.** It would be direct wallet signing, Solana RPC streams and the Jupiter swap API, all code we own.
- **The one big limit: Hark can't be the 24/7 runtime.** My sandbox runs per session, and scheduled tasks fire minutes to hours apart. Real-time trading needs an always-on server (a VPS). I can write, test and backtest all of the code and walk you through deploying it. After that, I can review its logs and performance on a schedule, but the bot itself runs on your server.
- **The edge is uncertain and has to be proven.** Of 2.9M pump.fun launches from Aug 1 to Oct 15, 2026, about 2.4–3.4% graduated and under 1 in 10 still traded a week later. About 29% had another wallet buying in the launch block (bundling). In Sep–Oct 2026, only 21–24% of active wallets made money on closed trades, and the median wallet lost (Jumpbit, Oct 2026). Paper trading has to show net profit after real costs before any money goes in.

## 1. Infrastructure needed
| Layer | Choice | Why |
|---|---|---|
| Server | VPS, about 2–4 vCPU and 4–8 GB RAM, US-East or Frankfurt (near validators and RPC) | Always-on runtime |
| RPC and streams | Helius (Developer $49/mo to start; Business $499/mo adds LaserStream gRPC) | WebSocket streams, webhooks for wallet tracking, DAS token data, staked sending |
| Tx landing | Helius Sender (included on all plans; 0.000005 SOL minimum tip) plus priority fees | Higher landing rate without building Jito plumbing ourselves |
| Swaps | Jupiter Swap API (Free 1 RPS; Developer $25/mo, 10 RPS) | Best-route quotes across Raydium, PumpSwap, Meteora, Orca and pump.fun curves |
| Market data | Birdeye Data API (Lite $39, Starter $99, Premium $199 with WebSocket) plus DexScreener's free API | OHLCV, new listings, top holders and traders, wallet trade history |
| Risk data | Our own on-chain checks, plus the RugCheck API as a second opinion | No single external source to trust |
| Storage | Postgres (or SQLite to start) | Every signal, decision, fill and P&L |
| Brain | Python asyncio services (or TypeScript) with rule and score models. An LLM does only slow tasks (narrative or meta review), never per-trade decisions | Latency and cost |
| Alerts and control | Private Telegram bot | Alerts, daily report, /stop kill switch |

## 2. Without a copy-trading bot?
Yes. Every function maps to raw APIs: discovery comes from program logs, safety from account reads plus simulation, execution from Jupiter quote → sign locally → send, and wallet tracking from Helius webhooks. An external service is justified only for:
- **Helius / Birdeye**: running our own Solana node with Geyser costs $2,900+/mo (Helius dedicated nodes start there). Renting is far cheaper.
- **Jupiter**: rebuilding routing across many DEX programs is months of work. Jupiter is free or cheap and audited.

## 3. DEXs and aggregators to integrate
1. **Jupiter**: the primary execution path for everything routable.
2. **Pump.fun bonding curve and PumpSwap**: where most new memecoins start and graduate. Watched directly via program events; trades go through Jupiter, or through direct program instructions later if latency demands it.
3. **Raydium (AMM v4, CPMM, LaunchLab), Meteora (DLMM, DAMM), Orca Whirlpools**: watched for new pools and liquidity changes. Execution still goes through Jupiter.

## 4. Real-time discovery and wallet tracking
- New tokens and pools: Helius WebSocket/LaserStream subscriptions on the pump.fun, PumpSwap, Raydium and Meteora program IDs (create and initialize events).
- Trending and momentum: Birdeye token list, trending and new-listing endpoints, and DexScreener boosts and pairs.
- Wallet tracking: Helius webhooks on a watched-wallet list (a push on every swap), plus Birdeye wallet historical trades and trader profiles to score wallets.
- Holders: RPC `getTokenLargestAccounts`, plus Helius DAS and Birdeye top holders.

## 5. How the four agents work
All agents emit a **Signal** (token, agent, thesis, entry zone, invalidation, targets, raw features). None can trade. Only the Orchestrator can.

**SNIPER**: watches new launches, but doesn't race the launch block. Bundlers and paid snipers win block 0, so we lose that race by design. It enters from minute 2 to 15, only after the token passes the security gate, liquidity ≥ threshold, a sell simulation succeeds, early buyers are mostly unique, un-clustered wallets, and the buy/sell ratio and unique-buyer growth stay positive across 3+ intervals.

**MOMENTUM**: tracks volume z-score versus its own last 1–6 hours, liquidity inflow, breakout over the recent range high, rising tx count and holders, and buy-volume share. It enters on a confirmed breakout plus volume, with a trailing stop based on ATR or the last swing low. It exits on momentum decay (falling volume, rising sell share, or a lower high).

**DIP HUNTER**: only works on tokens already "healthy" (age above X hours, liquidity above Y, passed security, holder count stable or rising). It looks for a sharp wick or drawdown, then waits for reversal confirmation: sell volume exhausting, a higher low on 1–5 minute bars, buy share recovering, and liquidity unchanged. Liquidity that's falling during a dip means it's dying, so the trade is rejected.

**WHALE TAIL**: builds a scored wallet roster from historical closed trades (realized P&L, win rate, average return, hold time, max drawdown, frequency) and drops wallets that look like insiders or bundlers (funded by a token's deployer, buys in launch blocks, coordinated clusters). On a roster wallet's buy, it re-runs the full security and liquidity gate independently, with a latency cap so we don't buy their exit liquidity.

## 6. Rug and malicious-token detection
Every token gets a **Security Score (0–100)** and must pass **hard fails** first. Any one hard fail means reject:
- Mint authority not revoked, or freeze authority set
- Token-2022 dangerous extensions (transfer hook, permanent delegate, transfer fee above a small cap, non-transferable, pausable)
- **Sell simulation fails**: a Jupiter quote and simulateTransaction for selling our intended size must succeed with acceptable impact
- Liquidity below the minimum, or LP removable by a single wallet (where applicable)
- Top-10 holders (excluding pool and burn) above the threshold, or the dev wallet holding above the threshold
- Bundle detection: a high share of supply bought in the launch block by wallets with a common funding source
- Deployer history: past tokens from the same funder that rugged

Soft factors are weighted into the score: holder growth, organic buyer diversity, dev selling, social presence, RugCheck risk flags, token age, and liquidity stability.
A revoked mint or burned LP is required, but never proof of safety.

## 7. Safest execution architecture
- **Dedicated hot wallet** with limited capital. Keep the main funds in a separate wallet you control. Never share a seed phrase in chat.
- **Signing options**: (a) a local encrypted keypair on the VPS (simplest; the key never leaves the server), or (b) a policy-controlled server wallet (e.g. Turnkey) whose policy allows only swap programs such as Jupiter and pump.fun, and blocks transfers to any outside address. Option (b) is safer; verify pricing in Phase 1.
- **Execution engine**: idempotent order IDs (no duplicate buys), a per-token lock, a quote → simulate → sign → send through Sender with a priority fee, and confirmation tracking with a timeout and a capped retry. Balances are reconciled from the chain after every fill, and sells are verified by the token balance going to zero.
- **P&L from actual fills**: SOL in and out, including base, priority and tip fees, DEX fees and realized slippage. Displayed prices are never used.

## 8. Dashboard
A web app on the VPS (Next.js or Streamlit), password-protected, plus Telegram summaries:
- **Account**: starting and current balance, realized and unrealized P&L, fees, volume, daily and weekly P&L, max drawdown
- **Performance**: trades, wins and losses, win rate, average win and loss, profit factor, average hold
- **Agents**: one panel per agent with the same stats and a live status (scanning, signals, rejected, in position)
- **Live feed**: token, agent, reason, entry, size, current price, uP&L, TP and SL, exit reason
- **Decision log**: every signal with its score, accept or reject, and the reason
- Emergency STOP button (also /stop on Telegram)

## 9. Estimated operating costs (monthly)
| Phase | Stack | Est. cost |
|---|---|---|
| Build and paper | VPS $10–40, Helius Developer $49, Jupiter Free–$25, Birdeye Lite–Starter $39–99, LLM API ~$10–30 | **~$110–240** |
| Live, faster | Helius Business $499 (gRPC), Birdeye Premium $199, Jupiter $25–100 | **~$750–850** |

Trading costs per round trip:
- 2 txs, each with the base fee plus priority fee and tip
- DEX/curve fees, often around 1% combined on memecoin venues (verify per venue in Phase 1)
- Slippage, frequently 1–5% on thin pools

On small positions, **expect 2–6% round-trip cost**, so every strategy must clear that before it's profitable. Infra cost matters too: at $750/mo, you'd need meaningful capital just to break even. Start lean.

## 10. Biggest risks
**Technical**
- Latency arms race: pro bots and insiders front-run new launches and our fills
- Failed or dropped transactions in congestion; stuck positions in dying pools
- API outages, rate limits, data errors; bugs in sizing or exits
- Key compromise on the server

**Financial**
- Negative edge after costs (the base rate for memecoin traders is losing)
- Rugs and soft rugs that slip past the checks; liquidity vanishing before the exit
- Regime shifts: a pump.fun mechanics change (e.g. 2026's fee and BOOST changes) can break a strategy overnight
- Overfitting backtests; survivorship bias in historical data (dead tokens disappear from data sets)

**Mitigations**: tiny size, hard daily loss limits, kill switches, paper trading first, a graduated rollout, and no leverage.

## Risk and capital rules (proposed defaults, adjustable)
- Max 2% of trading capital at risk per trade; max 5% notional per position (sniper trades smaller)
- Max 4 open positions; max 1 position per token; 30% reserve always untouched
- Daily loss limit −6%: no new entries for the rest of the day. Drawdown −15% from peak: full stop and notify you
- Losing streak of 4: halve the size until 2 wins. No martingale, ever
- Compounding: recompute the capital base weekly, and only increase size after a positive week
- Abnormal market shutdown: SOL −8% in 1h, RPC errors above X%, or tx failure rate above Y%

## Implementation roadmap
| Phase | What | Exit criteria | Est. time |
|---|---|---|---|
| 1. Research & setup | Sign up for Helius, Jupiter and Birdeye keys; VPS; repo scaffold; verify fees per venue | Data streaming into DB | 1 week |
| 2. Build | Collectors, security gate, 4 agents, orchestrator and risk engine, paper execution engine, dashboard, Telegram bot | All components running end-to-end in paper mode | 3–4 weeks |
| 3. Backtest | Collect our own tick data (public history for dead tokens is weak); replay strategies with cost and slippage models | Each agent's net expectancy is measured, not assumed | 2 weeks, overlapping |
| 4. Paper trading | Live signals, simulated fills using real Jupiter quotes plus a slippage haircut | 4+ weeks, 200+ paper trades | 4–6 weeks |
| 5. Evaluate | Net P&L after costs, drawdown, profit factor, fill quality per agent; kill weak agents | Profit factor > 1.3 net, max DD within limits | 1 week |
| 6. Approval | Full report to you; you approve a small live budget | Your explicit go | — |
| 7. Live & scale | Start with a small amount you can lose entirely; scale only after 4 profitable weeks, in steps of 25–50% | Live results match paper within tolerance | Ongoing |

## What I can do vs. what you'll do
- **Me**: architecture, all code, tests, backtest and paper analysis, the dashboard, scheduled performance reviews, reports
- **You**: create the API accounts and VPS (I'll guide you step by step and can store the keys in your vault), fund the paper-then-live wallet, and approve each phase
- **Not possible from Hark directly**: hosting the always-on process, or holding your private key in chat
