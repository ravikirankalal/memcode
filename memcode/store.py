"""SQLite store: a `paths` table (the directory-tree spine) and a `memories` table.

Stdlib only. Every module talks to the store through this API; do not change
signatures without updating callers.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS paths (
  path TEXT PRIMARY KEY,          -- repo-relative, '' is the root
  parent TEXT,                    -- parent path, NULL for root
  kind TEXT NOT NULL,             -- 'dir' | 'file'
  content_hash TEXT,              -- sha1 of file contents (files only)
  annotation TEXT,                -- short human/agent note shown in the pinned map
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trigger TEXT NOT NULL,          -- correction|revert|fail_to_fix|retry|dep_change|manual
  text TEXT NOT NULL,             -- redacted summary
  anchor_path TEXT NOT NULL,      -- paths.path this memory is attached to ('' = repo-wide)
  anchor_hash TEXT,               -- content hash of the anchor when written
  provenance TEXT NOT NULL,       -- JSON: session id, event ids, timestamps
  confidence REAL NOT NULL DEFAULT 0.5,
  stale INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS memories_anchor ON memories(anchor_path);
CREATE TABLE IF NOT EXISTS salience_log (   -- shadow mode: logged, never used for ranking
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  memory_id INTEGER NOT NULL,
  surprise REAL NOT NULL, friction REAL NOT NULL,
  fragility REAL NOT NULL, confidence REAL NOT NULL,
  logged_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (          -- raw (redacted) hook events for trigger detection
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS retrievals (      -- for reinforce-on-success only
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session TEXT NOT NULL, memory_id INTEGER NOT NULL, ts REAL NOT NULL
);
"""


def sha1(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha1(data).hexdigest()


def db_path(repo_root: str | os.PathLike) -> Path:
    return Path(repo_root) / ".memcode" / "memory.db"


def connect(repo_root: str | os.PathLike) -> sqlite3.Connection:
    p = db_path(repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def upsert_path(con, path: str, kind: str, content_hash: str | None = None,
                annotation: str | None = None) -> None:
    parent = None if path == "" else ("" if "/" not in path else path.rsplit("/", 1)[0])
    con.execute(
        """INSERT INTO paths(path,parent,kind,content_hash,annotation,updated_at)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(path) DO UPDATE SET kind=excluded.kind,
             content_hash=COALESCE(excluded.content_hash,paths.content_hash),
             annotation=COALESCE(excluded.annotation,paths.annotation),
             updated_at=excluded.updated_at""",
        (path, parent, kind, content_hash, annotation, time.time()))
    con.commit()


def add_memory(con, trigger: str, text: str, anchor_path: str = "",
               anchor_hash: str | None = None, provenance: dict | None = None,
               confidence: float = 0.5) -> int:
    now = time.time()
    cur = con.execute(
        """INSERT INTO memories(trigger,text,anchor_path,anchor_hash,provenance,
             confidence,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)""",
        (trigger, text, anchor_path, anchor_hash, json.dumps(provenance or {}),
         confidence, now, now))
    con.commit()
    return cur.lastrowid


def list_memories(con, include_stale: bool = False) -> list[sqlite3.Row]:
    q = "SELECT * FROM memories" + ("" if include_stale else " WHERE stale=0")
    return con.execute(q + " ORDER BY updated_at DESC").fetchall()


def log_event(con, session: str, kind: str, payload: dict) -> int:
    cur = con.execute("INSERT INTO events(session,kind,payload,ts) VALUES(?,?,?,?)",
                      (session, kind, json.dumps(payload), time.time()))
    con.commit()
    return cur.lastrowid
