"""Shadow 'moonbag' strategy: same entries as the real paper trades, different exits.
Half at +25%, 30% at +60%, last 20% rides until it falls 40% from its peak (72h cap).
Priced from DexScreener with a flat cost per sale, so it is an estimate for comparison."""
import time
SCHEMA = """CREATE TABLE IF NOT EXISTS shadow(id INTEGER PRIMARY KEY, mint TEXT, symbol TEXT, sol_in REAL, entry REAL,
 left REAL DEFAULT 1.0, realized REAL DEFAULT 0, peak REAL, stage INTEGER DEFAULT 0, opened REAL, closed REAL, status TEXT DEFAULT 'open');"""
COST = 0.025  # spread + fees per sale

class Shadow:
    def __init__(self, db): self.db = db; db.executescript(SCHEMA)
    def open(self, pos_id, mint, symbol, sol_in, entry):
        self.db.execute("INSERT OR IGNORE INTO shadow(id,mint,symbol,sol_in,entry,peak,opened) VALUES(?,?,?,?,?,?,?)",
                        (pos_id, mint, symbol, sol_in, entry, entry, time.time())); self.db.commit()
    def open_rows(self): return self.db.execute("SELECT * FROM shadow WHERE status='open'").fetchall()

    def update(self, s, price, cfg):
        m = cfg["momentum"]; e = s["entry"]; peak = max(s["peak"], price); age = time.time() - s["opened"]
        left, realized, stage = s["left"], s["realized"], s["stage"]
        def sell(frac):
            nonlocal left, realized
            frac = min(frac, left); realized += s["sol_in"] * frac * (price / e) * (1 - COST); left -= frac
        event = None
        if stage == 0:
            if price <= e * (1 - m["stop_pct"] / 100): sell(left); event = "stop"
            elif price >= e * (1 + m["take_profit_pct"][0] / 100): sell(0.5); stage = 1; event = "tp1"
            elif age > m["time_stop_min"] * 60: sell(left); event = "time"
        elif stage == 1:
            if price >= e * (1 + m["take_profit_pct"][1] / 100): sell(0.3); stage = 2; event = "tp2 (moonbag on)"
            elif price <= peak * (1 - m["trail_pct"] / 100) or age > m["time_stop_min"] * 60: sell(left); event = "trail/time"
        elif stage == 2:
            if price <= peak * 0.60 or age > 72 * 3600: sell(left); event = f"moonbag out at {price/e:.1f}x"
        done = left <= 1e-9
        self.db.execute("UPDATE shadow SET left=?, realized=?, peak=?, stage=?, status=?, closed=? WHERE id=?",
                        (max(left, 0), realized, peak, stage, "closed" if done else "open", time.time() if done else None, s["id"]))
        self.db.commit(); return event

    def stats(self):
        rows = self.db.execute("SELECT * FROM shadow WHERE status='closed'").fetchall()
        pnl = [r["realized"] - r["sol_in"] for r in rows]
        best = max((r["peak"] / r["entry"] for r in rows), default=0)
        return {"closed": len(rows), "win_rate": round(sum(p > 0 for p in pnl) / len(rows), 2) if rows else None,
                "net_sol": round(sum(pnl), 5), "best_peak_x": round(best, 1), "open": len(self.open_rows())}
