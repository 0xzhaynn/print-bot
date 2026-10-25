"""SQLite decision log: every signal, verdict, order and fill is recorded."""
import sqlite3, json, time, pathlib
SCHEMA = """
CREATE TABLE IF NOT EXISTS security_checks(id INTEGER PRIMARY KEY, ts REAL, mint TEXT, symbol TEXT,
  score INTEGER, passed INTEGER, hard_fails TEXT, details TEXT);
CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY, ts REAL, agent TEXT, mint TEXT, thesis TEXT,
  entry REAL, stop REAL, targets TEXT, features TEXT);
CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY, ts REAL, signal_id INTEGER, accepted INTEGER,
  confidence REAL, size_sol REAL, reason TEXT);
CREATE TABLE IF NOT EXISTS fills(id INTEGER PRIMARY KEY, ts REAL, order_key TEXT UNIQUE, mint TEXT, side TEXT,
  sol_amount REAL, token_amount REAL, fees_sol REAL, slippage_pct REAL, mode TEXT, tx TEXT);
"""
class DB:
    def __init__(self, path="degen.db"):
        p = pathlib.Path(path); self.c = sqlite3.connect(p); self.c.executescript(SCHEMA)
    def log_check(self, r):
        self.c.execute("INSERT INTO security_checks(ts,mint,symbol,score,passed,hard_fails,details) VALUES(?,?,?,?,?,?,?)",
            (time.time(), r["mint"], r.get("symbol"), r["score"], int(r["passed"]), json.dumps(r["hard_fails"]), json.dumps(r["details"])))
        self.c.commit()
