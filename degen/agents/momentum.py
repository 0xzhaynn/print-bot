"""MOMENTUM agent: trend continuation on tokens that already passed the security gate.
Emits a structured signal (thesis, entry, stop, targets) or None."""
import time

def evaluate(pair: dict, cfg: dict):
    m = cfg["momentum"]
    pc = pair.get("priceChange") or {}; tx = (pair.get("txns") or {}).get("h1", {})
    liq = (pair.get("liquidity") or {}).get("usd") or 0
    vol_h1 = (pair.get("volume") or {}).get("h1") or 0
    price = float(pair.get("priceUsd") or 0)
    age = (time.time() * 1000 - pair.get("pairCreatedAt", 0)) / 60000
    h1, m5 = pc.get("h1") or 0, pc.get("m5") or 0
    buys, sells = tx.get("buys", 0), max(tx.get("sells", 0), 1)
    f = {"h1": h1, "m5": m5, "vol_liq": round(vol_h1 / liq, 2) if liq else 0, "bs": round(buys / sells, 2), "age_min": round(age)}
    ok = (m["min_h1_change_pct"] <= h1 <= m["max_h1_change_pct"] and m5 >= m["min_m5_change_pct"]
          and m["min_h1_volume_to_liq"] <= f["vol_liq"] <= m.get("max_h1_volume_to_liq", 99) and f["bs"] >= m["min_buy_sell_ratio"]
          and age >= m["min_age_min"] and price > 0)
    if not ok: return None, f
    conf = min(1.0, 0.4 + 0.1 * (f["bs"] - 1) + 0.05 * min(f["vol_liq"], 4) + (0.1 if m5 > 2 else 0))
    return {"agent": "MOMENTUM", "mint": pair["baseToken"]["address"], "symbol": pair["baseToken"]["symbol"],
            "thesis": f'+{h1:.0f}% 1h, buys/sells {f["bs"]}, vol/liq {f["vol_liq"]}',
            "entry": price, "stop": price * (1 - m["stop_pct"] / 100),
            "targets": [price * (1 + t / 100) for t in m["take_profit_pct"]],
            "confidence": round(conf, 2), "features": f}, f


def pullback_entry(pair: dict, w: dict, price: float, cfg: dict):
    """Second step after a momentum signal: wait for a 5-15% dip off the high, then buy the first uptick with buyers still in control.
    The stop goes under the dip's low, so normal pullbacks no longer knock us out."""
    m = cfg["momentum"]
    if price <= 0: return None
    prev = w["last"]; w["high"] = max(w["high"], price); w["low"] = min(w["low"], price); w["last"] = price
    dip = 1 - price / w["high"]
    lo, hi = m.get("pullback_min_pct", 5) / 100, m.get("pullback_max_pct", 15) / 100
    if dip > m.get("pullback_kill_pct", 25) / 100: w["t"] = 0; return None   # too deep: it's dumping, drop it
    tx = (pair.get("txns") or {}).get("m5", {}); bs = tx.get("buys", 0) / max(tx.get("sells", 0), 1)
    dipped = 1 - w["low"] / w["high"] >= lo
    if not (dipped and lo * 0.5 <= dip <= hi and price > prev and bs >= 1.0): return None
    stop = min(price * (1 - m["stop_pct"] / 100), w["low"] * 0.97)
    return {"agent": "MOMENTUM", "mint": pair["baseToken"]["address"], "symbol": pair["baseToken"]["symbol"],
            "thesis": f"pullback buy: -{(1 - w['low'] / w['high']) * 100:.0f}% dip off high, bouncing, m5 buys/sells {bs:.2f}",
            "entry": price, "stop": stop, "targets": [price * (1 + t / 100) for t in m["take_profit_pct"]],
            "confidence": round(min(1.0, 0.5 + 0.1 * (bs - 1)), 2), "features": {"dip": round(dip, 3), "bs_m5": round(bs, 2)}}
