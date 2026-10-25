"""Paper execution: real Jupiter quotes for fills, real fee model, no transactions sent."""
import json, time, sqlite3
from ..data.clients import SOL

SCHEMA = """CREATE TABLE IF NOT EXISTS positions(id INTEGER PRIMARY KEY, mint TEXT, symbol TEXT, agent TEXT,
 opened REAL, closed REAL, sol_in REAL, tokens REAL, tokens_left REAL, entry_usd REAL, stop_usd REAL,
 targets TEXT, peak_usd REAL, sol_out REAL DEFAULT 0, fees_sol REAL DEFAULT 0, status TEXT, exit_reason TEXT, thesis TEXT);
CREATE TABLE IF NOT EXISTS account(k TEXT PRIMARY KEY, v REAL);"""

class PaperBroker:
    def __init__(self, cfg, clients, path="paper.db"):
        self.cfg, self.c = cfg, clients
        self.db = sqlite3.connect(path); self.db.row_factory = sqlite3.Row; self.db.executescript(SCHEMA)
        if not self.db.execute("SELECT 1 FROM account WHERE k='cash'").fetchone():
            self.db.execute("INSERT INTO account VALUES('cash',?)", (cfg["capital"]["paper_starting_sol"],))
            self.db.execute("INSERT INTO account VALUES('start',?)", (cfg["capital"]["paper_starting_sol"],)); self.db.commit()
    @property
    def cash(self): return self.db.execute("SELECT v FROM account WHERE k='cash'").fetchone()[0]
    def _cash(self, delta): self.db.execute("UPDATE account SET v=v+? WHERE k='cash'", (delta,)); self.db.commit()
    def open_positions(self): return self.db.execute("SELECT * FROM positions WHERE status='open'").fetchall()
    def equity_sol(self, marks):  # marks: mint -> SOL value of remaining tokens
        return self.cash + sum(marks.get(p["mint"], 0) for p in self.open_positions())

    def size_for(self, signal):
        cap = self.cfg["capital"]; start = self.db.execute("SELECT v FROM account WHERE k='start'").fetchone()[0]
        deployable = self.cash - start * cap["reserve_pct"]
        risk_size = start * cap["max_risk_per_trade_pct"] / (1 - signal["stop"] / signal["entry"])
        return max(0.0, min(deployable, start * cap["max_position_pct"], risk_size))

    async def buy(self, signal, size_sol):
        f = self.cfg["fees"]; q = await self.c.quote(SOL, signal["mint"], int(size_sol * 1e9))
        tokens = int(q["outAmount"]); fees = f["base_fee_sol"] + f["priority_fee_sol"] + f["ata_rent_sol"]
        if self.cash < size_sol + fees: return None
        self._cash(-(size_sol + fees))
        self.db.execute("""INSERT INTO positions(mint,symbol,agent,opened,sol_in,tokens,tokens_left,entry_usd,stop_usd,targets,peak_usd,fees_sol,status,thesis)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'open', ?)""", (signal["mint"], signal["symbol"], signal["agent"], time.time(), size_sol,
          tokens, tokens, signal["entry"], signal["stop"], json.dumps(signal["targets"]), signal["entry"], fees, signal["thesis"]))
        self.db.commit(); return tokens

    async def sell(self, pos, frac, reason):
        f = self.cfg["fees"]; amt = int(pos["tokens_left"] * frac) if frac < 1 else int(pos["tokens_left"])
        if amt <= 0: return 0
        q = await self.c.quote(pos["mint"], SOL, amt); sol = int(q["outAmount"]) / 1e9
        fees = f["base_fee_sol"] + f["priority_fee_sol"]; left = pos["tokens_left"] - amt
        refund = f["ata_rent_sol"] if left <= 0 else 0
        self._cash(sol - fees + refund)
        self.db.execute("UPDATE positions SET tokens_left=?, sol_out=sol_out+?, fees_sol=fees_sol+?-?, status=?, closed=?, exit_reason=? WHERE id=?",
            (left, sol, fees, refund, "closed" if left <= 0 else "open", time.time() if left <= 0 else None, reason, pos["id"]))
        self.db.commit(); return sol

    def stats(self):
        rows = self.db.execute("SELECT * FROM positions WHERE status='closed'").fetchall()
        pnl = [r["sol_out"] - r["sol_in"] - r["fees_sol"] for r in rows]
        wins = [p for p in pnl if p > 0]
        return {"closed": len(rows), "win_rate": round(len(wins) / len(rows), 2) if rows else None,
                "net_sol": round(sum(pnl), 5), "cash": round(self.cash, 5), "open": len(self.open_positions())}
