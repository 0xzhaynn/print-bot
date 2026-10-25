"""Token security gate: hard fails reject outright; soft factors build a 0-100 score.
Revoked mint / burned LP are necessary, never sufficient."""
from .solkeys import is_on_curve
from ..data.clients import SOL

TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
BURN = {"1nc1nerator11111111111111111111111111111111", "11111111111111111111111111111111"}
DANGEROUS_EXT = {"transferHook", "permanentDelegate", "nonTransferable", "pausableConfig", "defaultAccountState"}

async def check_token(c, cfg, mint, intended_size_sol=0.15):
    s = cfg["security"]; hard, soft, d = [], [], {"mint": mint}
    # 1) mint account: authorities, program, extensions (RPC first, RugCheck fallback when RPC is rate-limited)
    info = None; supply = 0
    try:
        acc = await c.rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
        if acc and acc.get("value"):
            v = acc["value"]; info = v["data"]["parsed"]["info"]
            d["program"] = "token-2022" if v["owner"] == TOKEN_2022 else "spl-token"
    except Exception:
        pass
    if info is None:
        full = await c.rugcheck_full(mint)
        if not full: return _result(mint, None, ["mint data unavailable"], [], d)
        tok = full.get("token") or {}
        info = {"mintAuthority": full.get("mintAuthority"), "freezeAuthority": full.get("freezeAuthority"),
                "supply": tok.get("supply", 0), "decimals": tok.get("decimals", 0), "extensions": []}
        d["program"] = "token-2022" if full.get("tokenProgram") == TOKEN_2022 else "spl-token"
        if d["program"] == "token-2022" and full.get("token_extensions"): d["token_extensions_raw"] = str(full["token_extensions"])[:200]
        d["mint_source"] = "rugcheck"
    d["mint_authority"] = info.get("mintAuthority"); d["freeze_authority"] = info.get("freezeAuthority")
    supply = int(info.get("supply") or 0)
    if d["mint_authority"]: hard.append("mint authority active")
    if d["freeze_authority"]: hard.append("freeze authority active")
    exts = [e.get("extension") for e in info.get("extensions", [])]
    d["extensions"] = exts
    bad = DANGEROUS_EXT.intersection(exts)
    if bad: hard.append(f"dangerous token-2022 extensions: {sorted(bad)}")
    for e in info.get("extensions", []):
        if e.get("extension") == "transferFeeConfig":
            bps = e["state"]["newerTransferFee"]["transferFeeBasisPoints"]
            d["transfer_fee_bps"] = bps
            if bps > 100: hard.append(f"transfer tax {bps/100:.1f}%")
            elif bps > 0: soft.append(("transfer tax", 10))

    # 2) market + liquidity (DexScreener)
    pairs = await c.pairs_for(mint)
    liq = sum((p.get("liquidity") or {}).get("usd", 0) or 0 for p in pairs)
    top = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd", 0) or 0) if pairs else None
    d["symbol"] = top["baseToken"]["symbol"] if top else None
    d["liquidity_usd"] = round(liq); d["dex"] = top.get("dexId") if top else None
    d["age_min"] = round((__import__("time").time()*1000 - top["pairCreatedAt"]) / 60000) if top and top.get("pairCreatedAt") else None
    if liq < s["min_liquidity_usd"]: hard.append(f"liquidity ${liq:,.0f} < ${s['min_liquidity_usd']:,}")
    if top:
        tx = top.get("txns", {}).get("h1", {}); b, sl = tx.get("buys", 0), tx.get("sells", 0)
        d["h1_buys_sells"] = [b, sl]
        if b + sl > 20 and sl > 0 and b / sl < 0.6: soft.append(("heavy 1h selling", 10))

    # 3) holder concentration (exclude program vaults/PDAs, known AMMs/lockers, burn)
    #    Primary: our RPC. Fallback: RugCheck full report (public RPC blocks getTokenLargestAccounts).
    wallets, src = None, None
    try:
        largest = (await c.rpc("getTokenLargestAccounts", [mint]))["value"]
        owners = await c.rpc("getMultipleAccounts", [[a["address"] for a in largest], {"encoding": "jsonParsed"}])
        wallets = []
        for a, o in zip(largest, owners["value"]):
            owner = o["data"]["parsed"]["info"]["owner"] if o else None
            if owner in BURN or (owner and not is_on_curve(owner)): continue
            wallets.append((owner, int(a["amount"]) / supply if supply else 0))
        src = "rpc"
    except Exception:
        full = await c.rugcheck_full(mint)
        if full and full.get("topHolders") is not None:
            known = set((full.get("knownAccounts") or {}).keys())
            wallets = [(h["owner"], h["pct"] / 100) for h in full["topHolders"]
                       if h["owner"] not in known and h["address"] not in known and h["owner"] not in BURN
                       and is_on_curve(h["owner"])]
            src = "rugcheck"
            d["total_holders"] = full.get("totalHolders")
            if full.get("graphInsidersDetected"): soft.append(("insider wallet network detected", 15)); d["insiders"] = full["graphInsidersDetected"]
            if full.get("rugged"): hard.append("flagged as rugged")
    if wallets is None:
        hard.append("holder data unavailable")
    else:
        top10 = sum(p for _, p in wallets[:10]); biggest = wallets[0][1] if wallets else 0
        d["holder_source"] = src
        d["top10_wallet_pct"] = round(top10 * 100, 1); d["largest_wallet_pct"] = round(biggest * 100, 1)
        if top10 > s["max_top10_pct"]: hard.append(f"top-10 wallets hold {top10:.0%}")
        if biggest > s["max_single_holder_pct"]: hard.append(f"single wallet holds {biggest:.0%}")
        elif biggest > s["max_single_holder_pct"] / 2: soft.append(("large single holder", 10))

    # 4) sellability: Jupiter round-trip quote at our intended size
    try:
        lam = int(intended_size_sol * 1e9)
        buy = await c.quote(SOL, mint, lam); out = int(buy["outAmount"])
        sell = await c.quote(mint, SOL, out); back = int(sell["outAmount"])
        rt = 1 - back / lam; d["roundtrip_cost_pct"] = round(rt * 100, 2)
        if rt > s["max_sell_impact_pct"] * 2: hard.append(f"round-trip cost {rt:.1%} too high")
        elif rt > s["max_sell_impact_pct"]: soft.append(("high round-trip cost", 15))
    except Exception as e:
        hard.append("no sell route on Jupiter (unsellable or unroutable)")

    # 5) rug patterns that pass every on-chain check: unlocked LP, serial deployers, copycat ticker farms
    full = await c.rugcheck_full(mint)
    if full:
        mk = [m for m in (full.get("markets") or []) if m.get("lp")]
        if mk:
            locked = max(m["lp"].get("lpLockedPct") or 0 for m in mk); d["lp_locked_pct"] = round(locked, 1)
            if locked < s.get("min_lp_locked_pct", 90): hard.append(f"only {locked:.0f}% of LP locked/burned")
        ct = full.get("creatorTokens") or []
        d["creator_tokens"] = len(ct)
        if len(ct) > s.get("max_creator_tokens", 3): hard.append(f"creator launched {len(ct)} tokens (serial deployer)")
        if full.get("rugged"): hard.append("flagged as rugged")
    if d.get("symbol"):
        try:
            import time as _t
            week = (_t.time() - 7 * 86400) * 1000
            clones = {p["baseToken"]["address"] for p in await c.search(d["symbol"])
                      if p.get("chainId") == "solana" and p["baseToken"]["symbol"].upper() == d["symbol"].upper()
                      and p["baseToken"]["address"] != mint and (p.get("pairCreatedAt") or 0) > week}
            d["symbol_clones_7d"] = len(clones)
            if len(clones) > s.get("max_symbol_clones_7d", 2): hard.append(f"{len(clones)} copycat {d['symbol']} coins this week")
        except Exception:
            pass

    # 6) second opinion: RugCheck
    rc = await c.rugcheck(mint)
    if rc:
        d["rugcheck_score_norm"] = rc.get("score_normalised")
        d["rugcheck_risks"] = [r["name"] for r in rc.get("risks", [])][:6]
        if any(r.get("level") == "danger" for r in rc.get("risks", [])): soft.append(("rugcheck danger flag", 20))
        if (rc.get("score_normalised") or 0) > s["max_rugcheck_score_normalised"]: soft.append(("rugcheck high risk", 15))
    else:
        soft.append(("rugcheck unavailable", 5))
    return _result(mint, d.get("symbol"), hard, soft, d, s["min_security_score"])

def _result(mint, symbol, hard, soft, d, min_score=70):
    score = max(0, 100 - sum(p for _, p in soft)) if not hard else 0
    return {"mint": mint, "symbol": symbol, "score": score, "passed": not hard and score >= min_score,
            "hard_fails": hard, "soft_flags": [n for n, _ in soft], "details": d}
