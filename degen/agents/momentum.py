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
