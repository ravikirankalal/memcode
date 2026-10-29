"""The memory agent's own tables: transcript_scans (how far each session's log was read), agent_sessions (its running
conversation per coding session), memory_log (every change it made, for `memcode history`) and proposals (what it
proposed that memcode did not keep, and why: told back to it in its next message)."""
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
CREATE TABLE IF NOT EXISTS agent_sessions (  -- the memory agent's running conversation, one per coding session
  session TEXT PRIMARY KEY,               -- the coding agent's session
  agent_session TEXT NOT NULL,            -- the memory agent's conversation (claude session id, resumed each turn)
  ready INTEGER NOT NULL DEFAULT 0,       -- 1 once the opening briefing was sent
  calls INTEGER NOT NULL DEFAULT 0,
  context_tokens INTEGER NOT NULL DEFAULT 0,  -- size of the conversation at the last call
  cost_usd REAL NOT NULL DEFAULT 0,       -- the opening call's cost (scans count theirs in transcript_scans)
  started REAL NOT NULL,
  last_ts REAL NOT NULL                   -- when the agent last replied: the delta starts here
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
CREATE TABLE IF NOT EXISTS proposals (      -- proposals memcode did not keep, and why (conversation.delta)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  session TEXT NOT NULL,
  op TEXT NOT NULL,                       -- add | update | retire | recall
  target INTEGER,
  text TEXT NOT NULL,
  reason TEXT NOT NULL
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
