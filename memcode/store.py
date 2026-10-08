"""SQLite store: a `paths` table (the directory-tree spine) and a `memories` table.

Stdlib only. Every module talks to the store through this API; do not change
signatures without updating callers.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS paths (
  path TEXT PRIMARY KEY,          -- repo-relative, '' is the root
  parent TEXT,                    -- parent path, NULL for root
  kind TEXT NOT NULL,             -- 'dir' | 'file'
  content_hash TEXT,              -- sha1 of file contents (files only)
  annotation TEXT,                -- short human/agent note shown in the pinned map
  updated_at REAL NOT NULL,
  mtime_ns INTEGER,               -- stat cache so unchanged files are not re-hashed
  size INTEGER
);
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trigger TEXT NOT NULL,          -- correction|revert|fail_to_fix|retry|dep_change|manual
  text TEXT NOT NULL,             -- redacted summary
  anchor_path TEXT NOT NULL,      -- paths.path this memory is attached to ('' = repo-wide)
  anchor_hash TEXT,               -- content hash of the anchor when written
  anchor_symbol TEXT,             -- optional Python symbol (Class.method) inside the anchor file
  symbol_hash TEXT,               -- AST hash of that symbol when written
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
CREATE INDEX IF NOT EXISTS events_session ON events(session, id);
CREATE TABLE IF NOT EXISTS session_stats (   -- per-session counters (see `python3 -m memcode sessions`)
  session TEXT PRIMARY KEY,
  started_at REAL NOT NULL,
  rules_injected INTEGER NOT NULL DEFAULT 0,     -- user rules shown at session start
  notes_injected INTEGER NOT NULL DEFAULT 0,     -- other memories shown at session start
  captured INTEGER NOT NULL DEFAULT 0,           -- memories written this session
  repeated_corrections INTEGER NOT NULL DEFAULT 0, -- user re-stated a rule already stored: memory failed
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS injections (       -- which memories each session was shown (for later reinforcement)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session TEXT NOT NULL, memory_id INTEGER NOT NULL, ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS outcomes (         -- reinforcement signal per (session, memory); see outcomes.py
  session TEXT NOT NULL, memory_id INTEGER NOT NULL, outcome TEXT NOT NULL, ts REAL NOT NULL,
  PRIMARY KEY (session, memory_id)
);
CREATE TABLE IF NOT EXISTS scored_sessions (session TEXT PRIMARY KEY, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS capture_queue (    -- opt-in model capture (model_capture.py)
  id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL, text TEXT NOT NULL,
  status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, result TEXT, memory_id INTEGER, ts REAL NOT NULL
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


BUSY_TIMEOUT_MS = 5000
EVENTS_PER_SESSION = 400        # only the last 200 are ever replayed
EVENT_MAX_AGE_S = 30 * 86400


def resolve_root(hint: str | os.PathLike | None = None) -> str:
    """Repo root used by hooks and the MCP server alike: CLAUDE_PROJECT_DIR, else
    `git rev-parse --show-toplevel` from `hint` (or cwd), else `hint`/cwd itself."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and os.path.isdir(env):
        return os.path.abspath(env)
    start = str(hint) if hint and os.path.isdir(str(hint)) else os.getcwd()
    try:
        r = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"],
                           capture_output=True, check=False, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return os.path.abspath(r.stdout.decode("utf-8", "surrogateescape").strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return os.path.abspath(start)


def _ensure_ignored(repo_root: Path, memdir: Path) -> None:
    """Keep .memcode/ out of the user's git history (best effort, once per DB)."""
    try:
        (memdir / ".gitignore").write_text("*\n")
    except OSError:
        pass
    try:
        r = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "--git-path", "info/exclude"],
                           capture_output=True, check=False, timeout=5)
        if r.returncode != 0:
            return
        ex = Path(r.stdout.decode().strip())
        if not ex.is_absolute():
            ex = Path(repo_root) / ex
        cur = ex.read_text() if ex.exists() else ""
        if ".memcode/" not in cur.split():
            ex.parent.mkdir(parents=True, exist_ok=True)
            with open(ex, "a") as fh:
                fh.write(("" if not cur or cur.endswith("\n") else "\n") + ".memcode/\n")
    except (OSError, ValueError, subprocess.SubprocessError):
        pass


def _migrate(con) -> None:
    cols = {r[1] for r in con.execute("PRAGMA table_info(paths)")}
    for col in ("mtime_ns", "size"):
        if col not in cols:
            try:
                con.execute(f"ALTER TABLE paths ADD COLUMN {col} INTEGER")
            except sqlite3.OperationalError:
                pass  # another process migrated first
    mcols = {r[1] for r in con.execute("PRAGMA table_info(memories)")}
    for col in ("anchor_symbol", "symbol_hash"):
        if col not in mcols:
            try:
                con.execute(f"ALTER TABLE memories ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass
    con.commit()


def connect(repo_root: str | os.PathLike) -> sqlite3.Connection:
    """Open the DB safe for concurrent hook processes: WAL + busy_timeout."""
    p = db_path(repo_root)
    new = not p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(SCHEMA)
    _migrate(con)
    if new:
        try:
            os.chmod(p.parent, 0o700)
            os.chmod(p, 0o600)
        except OSError:
            pass
        _ensure_ignored(Path(repo_root), p.parent)
    return con


def upsert_path(con, path: str, kind: str, content_hash: str | None = None,
                annotation: str | None = None, mtime_ns: int | None = None,
                size: int | None = None, commit: bool = True) -> None:
    parent = None if path == "" else ("" if "/" not in path else path.rsplit("/", 1)[0])
    con.execute(
        """INSERT INTO paths(path,parent,kind,content_hash,annotation,updated_at,mtime_ns,size)
           VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(path) DO UPDATE SET kind=excluded.kind,
             content_hash=COALESCE(excluded.content_hash,paths.content_hash),
             annotation=COALESCE(excluded.annotation,paths.annotation),
             mtime_ns=excluded.mtime_ns, size=excluded.size,
             updated_at=excluded.updated_at""",
        (path, parent, kind, content_hash, annotation, time.time(), mtime_ns, size))
    if commit:
        con.commit()


def add_memory(con, trigger: str, text: str, anchor_path: str = "",
               anchor_hash: str | None = None, provenance: dict | None = None,
               confidence: float = 0.5, commit: bool = True,
               anchor_symbol: str | None = None, symbol_hash: str | None = None) -> int:
    now = time.time()
    cur = con.execute(
        """INSERT INTO memories(trigger,text,anchor_path,anchor_hash,provenance,
             confidence,created_at,updated_at,anchor_symbol,symbol_hash) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (trigger, text, anchor_path, anchor_hash, json.dumps(provenance or {}),
         confidence, now, now, anchor_symbol, symbol_hash))
    if commit:
        con.commit()
    return cur.lastrowid


def list_memories(con, include_stale: bool = False) -> list[sqlite3.Row]:
    q = "SELECT * FROM memories" + ("" if include_stale else " WHERE stale=0")
    return con.execute(q + " ORDER BY updated_at DESC").fetchall()


def log_event(con, session: str, kind: str, payload: dict, commit: bool = True) -> int:
    """Append an event and prune: keep the last EVENTS_PER_SESSION per session and
    drop anything older than EVENT_MAX_AGE_S."""
    now = time.time()
    cur = con.execute("INSERT INTO events(session,kind,payload,ts) VALUES(?,?,?,?)",
                      (session, kind, json.dumps(payload), now))
    new_id = cur.lastrowid
    con.execute("""DELETE FROM events WHERE session=? AND id <
                   COALESCE((SELECT id FROM events WHERE session=? ORDER BY id DESC
                             LIMIT 1 OFFSET ?), 0)""",
                (session, session, EVENTS_PER_SESSION - 1))
    con.execute("DELETE FROM events WHERE ts < ?", (now - EVENT_MAX_AGE_S,))
    if commit:
        con.commit()
    return new_id


STAT_FIELDS = ("rules_injected", "notes_injected", "captured", "repeated_corrections")


def bump(con, session: str, field: str, n: int = 1, commit: bool = True) -> None:
    """Add n to a per-session counter (creates the row on first use)."""
    if field not in STAT_FIELDS:
        raise ValueError(f"unknown counter {field}")
    now = time.time()
    con.execute(f"""INSERT INTO session_stats(session, started_at, {field}, updated_at) VALUES(?,?,?,?)
                    ON CONFLICT(session) DO UPDATE SET {field}={field}+excluded.{field}, updated_at=excluded.updated_at""",
                (session, now, n, now))
    if commit:
        con.commit()


SALIENCE_KEEP = 30   # salience_log rows kept per memory (shadow-mode time series)


def prune_salience_log(con) -> None:
    con.execute("""DELETE FROM salience_log WHERE id IN (
                     SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY memory_id ORDER BY id DESC) AS rn
                                     FROM salience_log) WHERE rn > ?)""", (SALIENCE_KEEP,))
    con.execute("DELETE FROM salience_log WHERE memory_id NOT IN (SELECT id FROM memories)")
    con.execute("DELETE FROM injections WHERE memory_id NOT IN (SELECT id FROM memories)")
    con.execute("DELETE FROM outcomes WHERE memory_id NOT IN (SELECT id FROM memories)")
    con.commit()
