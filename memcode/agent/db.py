"""The memory agent's own tables: transcript_scans (how far each session's log was read) and memory_log (every
change it made, for `memcode history`)."""
from __future__ import annotations

import json

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS transcript_scans (
  session TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  offset INTEGER NOT NULL DEFAULT 0,      -- transcript lines already scanned
  status TEXT NOT NULL,                   -- pending | working | idle | error
  attempts INTEGER NOT NULL DEFAULT 0,
  ts REAL NOT NULL,
  cost_usd REAL NOT NULL DEFAULT 0,
  result TEXT
);
CREATE TABLE IF NOT EXISTS memory_log (     -- every change the memory agent made, for review and undo
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  session TEXT,
  op TEXT NOT NULL,                       -- add | update | retire
  memory_id INTEGER,
  before TEXT,                            -- the memory row as JSON before the change (update, retire)
  after TEXT,                             -- the new text (add, update)
  evidence TEXT
);
"""

def ensure(con) -> None:
    con.executescript(SCHEMA_SQL)


def loads(s) -> dict:
    try:
        v = json.loads(s or "{}")
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}
