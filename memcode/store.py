"""SQLite store: a `paths` table (the directory-tree spine) and a `memories` table.

Stdlib only. Every module talks to the store through this API; do not change
signatures without updating callers.
"""
from __future__ import annotations

import functools
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
  trigger TEXT NOT NULL,          -- where it came from: correction|revert|fail_to_fix|retry|dep_change|agent|manual
  text TEXT NOT NULL,             -- summary
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
CREATE TABLE IF NOT EXISTS events (          -- hook events for trigger detection (fields capped)
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
CREATE TABLE IF NOT EXISTS memory_links (    -- the memory graph: related memories (graph.py)
  src INTEGER NOT NULL, dst INTEGER NOT NULL,
  kind TEXT NOT NULL,                     -- related | refines | contradicts | same_file | similar
  weight REAL NOT NULL DEFAULT 1.0,
  source TEXT NOT NULL,                   -- agent | auto
  ts REAL NOT NULL,
  PRIMARY KEY (src, dst, kind)
);
CREATE INDEX IF NOT EXISTS links_dst ON memory_links(dst);
CREATE TABLE IF NOT EXISTS memory_feedback (  -- did the coding agent use a memory shown next to the work? (feedback.py)
  session TEXT NOT NULL, memory_id INTEGER NOT NULL,
  verdict TEXT NOT NULL,                   -- used | unused
  source TEXT NOT NULL DEFAULT '',         -- how it was shown: prompt | action | touch | flagged
  ts REAL NOT NULL,
  PRIMARY KEY (session, memory_id)
);
CREATE TABLE IF NOT EXISTS pending_recalls (  -- memories the memory agent flagged for what a session is doing now
  session TEXT NOT NULL, memory_id INTEGER NOT NULL,
  why TEXT NOT NULL DEFAULT '',            -- the agent's reason, shown with the memory
  ts REAL NOT NULL,
  PRIMARY KEY (session, memory_id)
);
CREATE TABLE IF NOT EXISTS memory_vectors (  -- local embedding per memory (embed.py)
  memory_id INTEGER PRIMARY KEY,
  vec TEXT NOT NULL,                      -- JSON {bucket: 1 + log(count)}, sparse; IDF applied when compared
  src_hash TEXT NOT NULL                  -- hash of the text it was computed from
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


def memdir(repo_root: str | os.PathLike) -> Path:
    """Where the store lives: <main working tree>/.memcode, shared by every checkout of the repository (#32). Files
    are still read from `repo_root`, the session's own checkout (#37)."""
    return Path(main_tree(os.path.abspath(str(repo_root)))) / ".memcode"


def db_path(repo_root: str | os.PathLike) -> Path:
    return memdir(repo_root) / "memory.db"


BUSY_TIMEOUT_MS = 5000
EVENTS_PER_SESSION = 400        # only the last 200 are ever replayed
EVENT_MAX_AGE_S = 30 * 86400


def resolve_root(hint: str | os.PathLike | None = None) -> str:
    """The session's working tree, used by hooks, slash commands and the MCP server alike: CLAUDE_PROJECT_DIR, else
    `git rev-parse --show-toplevel` from `hint` (the hook's cwd) or the process cwd, else that directory itself.
    Files (anchors, staleness, the repo map, scoping) resolve against it; the store itself lives in the main working
    tree (memdir), so a linked worktree shares its repository's store without reading the main checkout's branch
    (#32, #37). A host may set CLAUDE_PROJECT_DIR to the main checkout while the session runs in one of its linked
    worktrees: then the worktree the session is in wins (#39)."""
    start = str(hint) if hint and os.path.isdir(str(hint)) else os.getcwd()
    here = _toplevel(start)
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and os.path.isdir(env):
        env = os.path.abspath(env)
        if here and os.path.realpath(here) != os.path.realpath(env) \
                and os.path.realpath(main_tree(here)) == os.path.realpath(main_tree(env)):
            return here                                 # another checkout of the same repository: the session's own
        return env
    return here or os.path.abspath(start)


def _toplevel(start: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"],
                           capture_output=True, check=False, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return os.path.abspath(r.stdout.decode("utf-8", "surrogateescape").strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


@functools.lru_cache(maxsize=32)
def main_tree(top: str) -> str:
    """The main working tree when `top` is a linked worktree (its git common dir is <main>/.git), else `top`."""
    try:
        r = subprocess.run(["git", "-C", top, "rev-parse", "--git-dir", "--git-common-dir"],
                           capture_output=True, check=False, timeout=5)
        if r.returncode != 0:
            return top
        git_dir, common = (os.path.normpath(os.path.join(top, x))
                           for x in r.stdout.decode("utf-8", "surrogateescape").split("\n")[:2])
    except (OSError, ValueError, subprocess.SubprocessError):
        return top
    main = os.path.dirname(common)
    if git_dir == common or os.path.basename(common) != ".git" or not os.path.isdir(main):
        return top                 # not a linked worktree, or the main repository is bare
    return main


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
    for gone in ("capture_queue", "salience_log"):       # model capture and the salience shadow log (removed in 0.12)
        con.execute(f"DROP TABLE IF EXISTS {gone}")
    cols = {r[1] for r in con.execute("PRAGMA table_info(paths)")}
    for col in ("mtime_ns", "size"):
        if col not in cols:
            try:
                con.execute(f"ALTER TABLE paths ADD COLUMN {col} INTEGER")
            except sqlite3.OperationalError:
                pass  # another process migrated first
    for table, col, decl in (("injections", "source", "TEXT NOT NULL DEFAULT 'pinned'"),
                             ("session_stats", "prompt_injected", "INTEGER NOT NULL DEFAULT 0")):
        if col not in {r[1] for r in con.execute(f"PRAGMA table_info({table})")}:
            try:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass
    mcols = {r[1] for r in con.execute("PRAGMA table_info(memories)")}
    for col in ("anchor_symbol", "symbol_hash", "terms"):   # terms: retrieval's cached tokens, keyed by a source hash
        if col not in mcols:
            try:
                con.execute(f"ALTER TABLE memories ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass
    # hierarchy (scope + abstraction) and labels; all additive with defaults, so older readers are unaffected
    for col, decl in (("scope_path", "TEXT NOT NULL DEFAULT ''"),        # where it applies: '' repo, dir, or file
                      ("scope_kind", "TEXT NOT NULL DEFAULT 'repo'"),    # repo | dir | file | symbol
                      ("parent_id", "INTEGER"),                          # consolidated child -> lesson id
                      ("level", "INTEGER NOT NULL DEFAULT 0"),           # 0 raw, 1 lesson
                      ("labels", "TEXT NOT NULL DEFAULT ''"),            # comma-separated, sorted
                      ("evidence_count", "INTEGER NOT NULL DEFAULT 1")): # lessons: number of children
        if col not in mcols:
            try:
                con.execute(f"ALTER TABLE memories ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass
    # the flat memory model (0.15): one kind of memory; these replace rules / notes / facts / decisions
    for col, decl in (("from_user", "INTEGER NOT NULL DEFAULT 0"),      # quoted from the user's words: an instruction
                      ("topic", "TEXT NOT NULL DEFAULT ''"),            # workflow, stack, component, ...: display only
                      ("importance", "INTEGER NOT NULL DEFAULT 3"),     # 1-5
                      ("mkey", "TEXT"),                                 # set for memories updated in place
                      ("expires_at", "REAL"),                           # ongoing state that lapses
                      ("stats", "TEXT NOT NULL DEFAULT '{}'"),          # counters of keyed memories (runs, ok, fail)
                      ("unusual", "INTEGER NOT NULL DEFAULT 0")):       # differs from the usual way for such a project
        if col not in mcols:
            try:
                con.execute(f"ALTER TABLE memories ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass
    try:
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_mem_key ON memories(mkey) WHERE mkey IS NOT NULL")
    except sqlite3.OperationalError:
        pass
    # memories written before 0.15: rules -> from_user, the agent's categories -> topic, decisions -> an expiry
    con.execute("UPDATE memories SET from_user=1 WHERE trigger='correction' AND from_user=0")
    con.execute("""UPDATE memories SET topic=json_extract(provenance, '$.category') WHERE topic='' AND
                   json_valid(provenance) AND json_extract(provenance, '$.category') IS NOT NULL
                   AND json_extract(provenance, '$.category') NOT IN ('', 'rule')""")
    con.execute("""UPDATE memories SET importance=CAST(json_extract(provenance, '$.importance') AS INTEGER)
                   WHERE importance=3 AND json_valid(provenance) AND json_extract(provenance, '$.importance') BETWEEN 1 AND 5""")
    con.execute("UPDATE memories SET topic='decision' WHERE trigger='decision' AND topic=''")
    con.execute("UPDATE memories SET expires_at=updated_at+30*86400 WHERE trigger='decision' AND expires_at IS NULL")
    con.execute("""UPDATE memories SET trigger='agent' WHERE trigger IN ('transcript', 'decision') OR (trigger='correction'
                   AND json_valid(provenance) AND json_extract(provenance, '$.source')='transcript')""")
    con.execute("""UPDATE memories SET text=substr(text, 28) WHERE text LIKE 'Rule from user correction: %'""")
    _facts_to_memories(con)
    con.execute("DROP VIEW IF EXISTS fact_rows")
    con.execute(FACT_ROWS)

    for idx, cols in (("idx_mem_scope", "scope_path"), ("idx_mem_parent", "parent_id")):
        try:
            con.execute(f"CREATE INDEX IF NOT EXISTS {idx} ON memories({cols})")
        except sqlite3.OperationalError:
            pass
    con.commit()


# Keyed memories (what were facts): updated in place by key; origin command | repo | env | inference | manual (set
# by the user with `memcode fact set`); counters in stats. fact_rows reads them in the old facts shape.
FACT_ORIGINS = ("command", "repo", "env", "inference")
FACT_ROWS = """CREATE VIEW fact_rows AS SELECT id, mkey AS key,
  CASE WHEN trigger='manual' THEN 'user' ELSE trigger END AS category,
  json_extract(stats, '$.role') AS role, text AS value, COALESCE(json_extract(stats, '$.source'), '') AS source,
  COALESCE(json_extract(stats, '$.runs'), 0) AS runs, COALESCE(json_extract(stats, '$.ok'), 0) AS ok,
  COALESCE(json_extract(stats, '$.fail'), 0) AS fail, created_at AS first_seen, updated_at AS last_seen,
  json_extract(stats, '$.source_hash') AS source_hash
  FROM memories WHERE mkey IS NOT NULL AND (trigger IN ('command', 'repo', 'env', 'inference') OR mkey LIKE 'user:%')"""


def _facts_to_memories(con) -> None:
    """Stores from before 0.15 kept facts in their own table: move each into a keyed memory, then drop the table."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='facts'").fetchone():
        return
    for r in con.execute("SELECT * FROM facts").fetchall():
        stats = {"role": r["role"], "source": r["source"], "runs": r["runs"], "ok": r["ok"], "fail": r["fail"],
                 "source_hash": r["source_hash"]}
        con.execute("""INSERT OR IGNORE INTO memories(trigger, text, anchor_path, provenance, created_at, updated_at,
                         topic, mkey, stats) VALUES(?,?,'','{}',?,?,?,?,?)""",
                    ("manual" if r["category"] == "user" else r["category"], r["value"], r["first_seen"],
                     r["last_seen"], r["role"] or "", r["key"], json.dumps(stats)))
    con.execute("DROP TABLE facts")


def scope_chain(path: str) -> list[str]:
    """'billing/api/x.py' -> ['billing/api/x.py', 'billing/api', 'billing', ''] (nearest first; '' is the repo)."""
    path = (path or "").strip("/")
    out = []
    while path:
        out.append(path)
        path = path.rsplit("/", 1)[0] if "/" in path else ""
    out.append("")
    return out


def delete_ids(con, ids) -> int:
    """Delete memories and the rows that reference them (retrievals, injections). The caller commits."""
    ids = [(i,) for i in ids]
    if not ids:
        return 0
    for t in ("retrievals", "injections", "outcomes", "memory_vectors", "pending_recalls", "memory_feedback"):
        con.executemany(f"DELETE FROM {t} WHERE memory_id=?", ids)
    con.executemany("DELETE FROM memory_links WHERE src=? OR dst=?", [(i[0], i[0]) for i in ids])
    return sum(con.execute("DELETE FROM memories WHERE id=?", i).rowcount for i in ids)


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
               anchor_symbol: str | None = None, symbol_hash: str | None = None, *,
               from_user: bool | None = None, topic: str = "", importance: int = 3,
               key: str | None = None, expires_at: float | None = None, unusual: bool = False) -> int:
    """One memory. trigger is where it came from (a correction, a revert, the agent, ...); from_user marks the user's
    own words (delivered as an instruction; defaults to True for corrections); key makes it updatable in place."""
    now = time.time()
    if from_user is None:
        from_user = trigger == "correction"
    cur = con.execute(
        """INSERT INTO memories(trigger,text,anchor_path,anchor_hash,provenance,confidence,created_at,updated_at,
             anchor_symbol,symbol_hash,from_user,topic,importance,mkey,expires_at,unusual)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (trigger, text, anchor_path, anchor_hash, json.dumps(provenance or {}), confidence, now, now,
         anchor_symbol, symbol_hash, int(bool(from_user)), topic or "", int(importance), key, expires_at, int(bool(unusual))))
    if commit:
        con.commit()
    return cur.lastrowid


def list_memories(con, include_stale: bool = False, measured: bool = False) -> list[sqlite3.Row]:
    """Memories, newest first; measured=True includes the per-command counters (facts.py) too."""
    q = "SELECT * FROM memories WHERE " + ("1" if measured else "trigger!='command'") + ("" if include_stale else " AND stale=0")
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


STAT_FIELDS = ("rules_injected", "notes_injected", "captured", "repeated_corrections", "prompt_injected")


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


def prune_orphans(con) -> None:
    """Injection and outcome rows of memories that no longer exist."""
    for t in ("injections", "outcomes"):
        con.execute(f"DELETE FROM {t} WHERE memory_id NOT IN (SELECT id FROM memories)")
    con.commit()
