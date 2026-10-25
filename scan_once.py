"""Phase 1 smoke test: pull fresh Solana tokens from DexScreener, run the security gate, log results."""
import asyncio, json, sys
from degen.core import config
from degen.core.db import DB
from degen.data.clients import Clients
from degen.security.gate import check_token

async def main(n=12):
    cfg = config.load(); c = Clients(cfg); db = DB()
    try: profiles = await c.trending_boosts()
    except Exception: profiles = await c.latest_profiles()
    mints = list(dict.fromkeys(p["tokenAddress"] for p in profiles))[:n]
    out = []
    for m in mints:
        try:
            r = await check_token(c, cfg, m); db.log_check(r); out.append(r)
        except Exception as e:
            out.append({"mint": m, "error": repr(e)[:120]})
        await asyncio.sleep(1.5); print('.', end='', flush=True)
    await c.close()
    json.dump(out, open("last_scan.json", "w"), indent=1)
    for r in out:
        if "error" in r: print("ERR", r["mint"][:8], r["error"]); continue
        dd = r["details"]
        print(f'{"PASS" if r["passed"] else "REJECT":6} {str(r["symbol"])[:10]:10} score={r["score"]:3} liq=${dd.get("liquidity_usd",0):>8,} '
              f'top10={dd.get("top10_wallet_pct")}% rt={dd.get("roundtrip_cost_pct")}% age={dd.get("age_min")}m | {"; ".join(r["hard_fails"])[:110]}')
asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 12))
