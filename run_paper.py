"""DEGEN AUTONOMOUS paper loop: scan -> security gate -> MOMENTUM -> risk sizing -> paper fill -> manage exits.
Usage: python run_paper.py [cycles]   (default runs forever)"""
import asyncio, json, sys, time, html
from degen.core import config
from degen.core.db import DB
from degen.core.notify import Notifier
from degen.data.clients import Clients, SOL
from degen.security.gate import check_token
from degen.agents import momentum
from degen.execution.paper import PaperBroker
from degen.execution.shadow import Shadow

GATE_TTL = 1800
REENTRY_COOLDOWN = 24 * 3600   # never re-buy a token within 24h of closing it at a loss
REPORT_HOUR_WAT = 21  # nightly report at 9 PM Lagos time (UTC+1)
HEARTBEAT_SEC = 3 * 3600  # "still alive" ping when nothing else was sent for 3h

def report_text(broker, title, shadow=None):
    st = broker.stats()
    rows = broker.db.execute("SELECT symbol, sol_out-sol_in-fees_sol AS pnl FROM positions WHERE status='closed' ORDER BY closed DESC").fetchall()
    best = max(rows, key=lambda r: r["pnl"], default=None); worst = min(rows, key=lambda r: r["pnl"], default=None)
    start = broker.db.execute("SELECT v FROM account WHERE k='start'").fetchone()[0]
    lines = [f"<b>{title}</b>", f"Closed trades: {st['closed']} (goal: 100)",
             "Win rate: " + ("-" if st['win_rate'] is None else f"{st['win_rate']:.0%}"),
             f"Net P/L: {st['net_sol']:+.5f} SOL ({st['net_sol']/start:+.1%} of start)",
             f"Cash: {st['cash']:.4f} SOL | Open: {st['open']}"]
    if best: lines.append(f"Best: {html.escape(best['symbol'])} {best['pnl']:+.5f} | Worst: {html.escape(worst['symbol'])} {worst['pnl']:+.5f}")
    for p in broker.open_positions(): lines.append(f"Holding {html.escape(p['symbol'])} ({p['sol_in']:.4f} SOL)")
    halt = risk_state(broker)
    if halt: lines.append(f"New entries PAUSED: {halt}")
    if shadow:
        sh = shadow.stats()
        lines += ["", "<b>Moonbag version (shadow)</b>", f"Closed: {sh['closed']} | Open: {sh['open']}",
                  "Win rate: " + ("-" if sh['win_rate'] is None else f"{sh['win_rate']:.0%}"),
                  f"Net P/L: {sh['net_sol']:+.5f} SOL | Best run: {sh['best_peak_x']}x"]
    return "\n".join(lines)

def _wat_midnight_utc():
    wat = time.time() + 3600
    return wat - (wat % 86400) - 3600

def risk_state(broker):
    """Why new entries are blocked, or None. Exits are always still managed."""
    cap, lim = broker.cfg["capital"], broker.cfg["limits"]
    start = broker.db.execute("SELECT v FROM account WHERE k='start'").fetchone()[0]
    closed = broker.db.execute("SELECT sol_out-sol_in-fees_sol AS pnl, closed FROM positions WHERE status='closed'").fetchall()
    open_cost = sum(p["sol_in"] for p in broker.open_positions())
    realized = sum(r["pnl"] for r in closed)
    if -realized >= start * lim["max_drawdown_pct"]:
        return f"max drawdown hit ({realized/start:+.1%} realized, limit -{lim['max_drawdown_pct']:.0%}). Halted until reviewed."
    today = sum(r["pnl"] for r in closed if (r["closed"] or 0) >= _wat_midnight_utc())
    if -today >= start * lim["daily_loss_pct"]:
        return f"daily loss limit hit ({today/start:+.1%} today, limit -{lim['daily_loss_pct']:.0%}). Resumes after midnight WAT."
    if broker.cash - start * cap["reserve_pct"] < 0.01:
        return "cash is at the reserve floor. Waiting for open trades to close."
    return None

RUG_LOSS = 0.5   # a single trade losing more than half its size = rug: ticker and coin banned for good
SEED_BANS = {"MAYA"}

def banned(broker, mint, symbol):
    if (symbol or "").upper() in SEED_BANS: return True
    rows = broker.db.execute("SELECT mint, symbol FROM positions WHERE status='closed' AND sol_out-sol_in-fees_sol < -?*sol_in", (RUG_LOSS,)).fetchall()
    return any(r["mint"] == mint or (r["symbol"] or "").upper() == (symbol or "").upper() for r in rows)

def recently_lost(broker, mint):
    r = broker.db.execute("SELECT max(closed) AS t FROM positions WHERE mint=? AND status='closed' AND sol_out-sol_in-fees_sol<0", (mint,)).fetchone()
    return bool(r and r["t"] and time.time() - r["t"] < REENTRY_COOLDOWN)

async def housekeeping(broker, tg, state, shadow=None):
    for cmd in await tg.commands():
        if cmd in ("/stats", "/start"): await tg.send(report_text(broker, "PRINT stats (paper)", shadow))
    await tg.flush()
    if time.time() - tg.last_sent >= HEARTBEAT_SEC:
        st = broker.stats(); hb = state.setdefault("hb", {"scanned": 0, "signals": 0})
        await tg.send(f"PRINT alive: {hb['scanned']} tokens checked, {hb['signals']} setups, quiet for 3h, no new entries. "
                      f"Open: {st['open']} | Cash: {st['cash']:.4f} SOL" + (" | PAUSED" if state.get("halt") else ""))
        state["hb"] = {"scanned": 0, "signals": 0}
    wat = time.gmtime(time.time() + 3600)
    day = time.strftime("%Y-%m-%d", wat)
    if wat.tm_hour >= REPORT_HOUR_WAT and state.get("reported") != day:
        state["reported"] = day
        await tg.send(report_text(broker, f"PRINT nightly report {day} (paper)", shadow))  # re-check a token at most every 30 min

async def manage_shadow(c, cfg, shadow, tg):
    for s in shadow.open_rows():
        pairs = await c.pairs_for(s["mint"])
        if not pairs: continue
        price = float(max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd", 0) or 0).get("priceUsd") or 0)
        if price <= 0: continue
        ev = shadow.update(s, price, cfg)
        if ev and "moonbag" in ev: await tg.send(f"MOONBAG (shadow) {html.escape(s['symbol'])}: {ev}")

async def manage(c, cfg, broker, tg):
    m = cfg["momentum"]
    for p in broker.open_positions():
        pairs = await c.pairs_for(p["mint"])
        if not pairs: continue
        price = float(max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd", 0) or 0).get("priceUsd") or 0)
        peak = max(p["peak_usd"], price); broker.db.execute("UPDATE positions SET peak_usd=? WHERE id=?", (peak, p["id"])); broker.db.commit()
        t1, t2 = json.loads(p["targets"]); half_taken = p["tokens_left"] < p["tokens"]
        reason = frac = None
        if price <= p["stop_usd"]: reason, frac = "stop", 1
        elif price >= t2: reason, frac = "target2", 1
        elif price >= t1 and not half_taken: reason, frac = "target1", 0.5
        elif half_taken and price <= peak * (1 - m["trail_pct"] / 100): reason, frac = "trail", 1
        elif time.time() - p["opened"] > m["time_stop_min"] * 60: reason, frac = "time", 1
        if reason:
            sol = await broker.sell(p, frac, reason)
            await tg.send(f"PAPER SELL {html.escape(p['symbol'])} ({reason}) {frac:.0%} -> {sol:.4f} SOL | price ${price:.6g}")

async def cycle(c, cfg, broker, db, tg, gate_cache, shadow, state):
    await manage(c, cfg, broker, tg)
    await manage_shadow(c, cfg, shadow, tg)
    halt = risk_state(broker)
    if halt != state.get("halt"):  # alert once when the pause starts or ends, never every cycle
        state["halt"] = halt
        await tg.send(f"PAUSED new entries: {halt}" if halt else "RESUMED: new entries allowed again")
    if halt: return
    if len(broker.open_positions()) >= cfg["capital"]["max_open_positions"]: return
    held = {p["mint"] for p in broker.open_positions()}
    seen = []
    for src in (c.trending_boosts, c.latest_profiles):
        try: seen += [x["tokenAddress"] for x in await src()]
        except Exception: pass
    for mint in list(dict.fromkeys(seen))[: cfg["loop"]["candidates_per_scan"]]:
        if mint in held or recently_lost(broker, mint): continue
        pairs = await c.pairs_for(mint)
        if not pairs: continue
        pair = max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd", 0) or 0)
        if banned(broker, mint, pair["baseToken"]["symbol"]): continue
        sig, feats = momentum.evaluate(pair, cfg)
        hb = state.setdefault("hb", {"scanned": 0, "signals": 0}); hb["scanned"] += 1; hb["signals"] += bool(sig)
        print("  ", pair["baseToken"]["symbol"][:10], feats, "SIGNAL" if sig else "")
        if not sig: continue
        cached = gate_cache.get(mint)
        if not cached or time.time() - cached[0] > GATE_TTL:
            try: r = await check_token(c, cfg, mint)
            except Exception as e: print("gate error", mint[:8], repr(e)[:80]); continue
            db.log_check(r); gate_cache[mint] = (time.time(), r)
        r = gate_cache[mint][1]
        if not r["passed"]: continue
        size = broker.size_for(sig)
        if size < 0.01: print("skip, size too small", sig["symbol"], round(size, 4)); continue
        tokens = await broker.buy(sig, size)
        if tokens:
            pid = broker.db.execute("SELECT max(id) FROM positions").fetchone()[0]
            shadow.open(pid, sig["mint"], sig["symbol"], size, sig["entry"])
            await tg.send(f"PAPER BUY {html.escape(sig['symbol'])} {size:.4f} SOL | {sig['thesis']} | gate {r['score']} | "
                          f"stop ${sig['stop']:.6g} tp ${sig['targets'][0]:.6g}/${sig['targets'][1]:.6g} | conf {sig['confidence']}")
        if len(broker.open_positions()) >= cfg["capital"]["max_open_positions"]: break

async def main(cycles=None):
    cfg = config.load(); c = Clients(cfg); db = DB(); broker = PaperBroker(cfg, c); tg = Notifier(); cache = {}; shadow = Shadow(broker.db)
    for p in broker.open_positions(): shadow.open(p['id'], p['mint'], p['symbol'], p['sol_in'], p['entry_usd'])
    state = {"reported": time.strftime("%Y-%m-%d", time.gmtime(time.time() + 3600)) if time.gmtime(time.time()+3600).tm_hour >= REPORT_HOUR_WAT else None}
    n = 0
    while cycles is None or n < cycles:
        try: await housekeeping(broker, tg, state, shadow)
        except Exception as e: print("housekeeping error:", repr(e)[:150])
        try: await cycle(c, cfg, broker, db, tg, cache, shadow, state)
        except Exception as e: print("cycle error:", repr(e)[:150])
        n += 1; print("stats", broker.stats(), flush=True)
        if cycles is None or n < cycles: await asyncio.sleep(cfg["loop"]["scan_interval_sec"])
    await c.close()

asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else None))
