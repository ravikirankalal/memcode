"""Opt-in transcript capture: read what happened in the session and keep what a later session needs.

The triggers only see events (a correction phrase, a failing-then-passing command, a revert). They miss what the
agent found out along the way ("the tests only run through `make check`") and rules the user states as plain
description ("every new module gets the SPDX header"). When enabled, the Stop hook queues the session's transcript;
a detached worker condenses the part not scanned yet (user messages, agent text, commands with exit status and
output tail, files written), asks a model for durable, repo-specific knowledge, and keeps an item only if:

  evidence   the model quotes it verbatim from the condensed transcript, and the quote is found there
  rules      an item is stored as a user rule only when its evidence is in a USER message (the user's own words);
             everything else is a note (trigger 'transcript'), shown inside the untrusted-notes wrapper
  new        it does not repeat a live memory or fact (term overlap)
  few        at most MAX_ITEMS per scan

On by default since 0.9.0; off with `memcode config transcript-capture off` or MEMCODE_TRANSCRIPT_CAPTURE=0. Model: MEMCODE_CAPTURE_MODEL
(default claude-haiku-5-5 here: one call per scanned turn). The call uses the `claude` CLI (the user's login) with
no tools, settings or plugins. Privacy: the condensed, redacted transcript text is sent to the model.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from . import store
from .redact import redact

DEFAULT_MODEL = "claude-haiku-5-5"
MAX_ITEMS = 5
MIN_NEW_CHARS = 400          # a scan needs at least this much new condensed text
MAX_CHARS = 24_000           # condensed text sent per scan (the newest part wins)
DUP_OVERLAP = 0.6            # term overlap with an existing memory or fact that counts as a repeat
MAX_ATTEMPTS = 2

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

SYSTEM = (
    "You are memcode's memory agent for one software repository. memcode gives coding agents a memory that carries "
    "across sessions: user rules (conventions the user stated; shown to every future session as instructions), notes "
    "(facts about the repository; shown as information) and facts (commands and environment limits). Your only job "
    "is to keep THIS repository's memory correct and useful. You never talk to the user or edit code.\n\n"
    "Each time, you get a briefing (the repository, the session, the memory as it stands, each item numbered) and the "
    "condensed transcript of the latest turn(s): [user] lines are the user's own words, [agent] lines the coding "
    "agent's, [ran] a shell command with its result and output tail, [wrote] a file it changed. Decide what the memory "
    "needs, as a list of operations (usually none):\n"
    "- add: something a future session must know to avoid a mistake or wasted time, that it could not easily see from "
    "the code: a convention the user stated or confirmed (also when phrased as description, e.g. 'every module has "
    "X'), how to build, test, lint or run things here when the obvious way fails, a pitfall that was discovered.\n"
    "- update: a numbered memory is incomplete or partly wrong given the transcript; give its number as target and the "
    "corrected full text.\n"
    "- retire: a numbered memory is no longer true or the user withdrew it; give its number as target.\n"
    "Rules of the job: a user rule is added, changed or retired only because of the user's own words. Skip details of "
    "the current task, one-off requests ('for this change only'), guesses the agent did not verify, general "
    "programming knowledge, anything soon stale, anything about the agent's own memory or tools, and anything the "
    "memory already says. Items marked (in the agent's context) were already shown to the coding agent in this "
    "session: when the agent follows, quotes or restates them, that is memcode working, not something new; never add "
    "or update anything because of it. Never record a place where the code still breaks a user rule as the accepted way. For each "
    "operation give: op; target (the memory number, 0 for add); kind ('rule' for a convention the USER stated, 'env' "
    "for a limit of the agent's environment rather than the repository, such as a refused or missing command, else "
    "'note'); text (one short imperative or factual sentence; for retire, why); evidence (an EXACT quote of 8-200 "
    "characters copied from the transcript); path (a repo-relative file or folder it applies to, or ''); conflicts "
    "(true when the operation would contradict or weaken a user rule without the user saying so). At most 5 "
    "operations; an empty list is the usual answer.")
SCHEMA = json.dumps({
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "maxItems": MAX_ITEMS, "items": {
        "type": "object", "additionalProperties": False,
        "required": ["op", "target", "kind", "text", "evidence", "path", "conflicts"],
        "properties": {"op": {"type": "string", "enum": ["add", "update", "retire"]}, "target": {"type": "integer"},
                       "kind": {"type": "string", "enum": ["rule", "note", "env"]}, "text": {"type": "string"},
                       "evidence": {"type": "string"}, "path": {"type": "string"},
                       "conflicts": {"type": "boolean"}}}}}})
_SELF = re.compile(r"(?i)\b(?:memcode|memory_(?:add|search|pinned|facts)|(?:agent|assistant)'?s? (?:own )?memory)\b")


def enabled(root) -> bool:
    """On by default since 0.9.0 (tc2 gate, bench/live/RESULTS.md Run 17). Off with MEMCODE_TRANSCRIPT_CAPTURE=0 or
    `memcode config transcript-capture off`, and wherever the `claude` CLI it calls is not installed."""
    env = os.environ.get("MEMCODE_TRANSCRIPT_CAPTURE", "").lower()
    if env in ("0", "false", "off"):
        return False
    from .model_capture import read_config
    if env not in ("1", "true", "on") and read_config(root).get("transcript_capture") is False:
        return False
    import shutil
    return shutil.which("claude") is not None


def ensure(con) -> None:
    con.executescript(SCHEMA_SQL)


def enqueue(con, session: str, path: str) -> None:
    ensure(con)
    con.execute("""INSERT INTO transcript_scans(session, path, status, ts) VALUES(?,?,'pending',?)
                   ON CONFLICT(session) DO UPDATE SET path=excluded.path, status='pending', attempts=0,
                   ts=excluded.ts""", (session, path, time.time()))
    con.commit()


def spawn_worker(root: str) -> None:
    """Start a detached worker; it exits when nothing is pending. Never raises."""
    try:
        pkg_parent = str(Path(__file__).resolve().parent.parent)
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in (pkg_parent, os.environ.get("PYTHONPATH")) if p))
        subprocess.Popen([sys.executable, "-m", "memcode.transcript_capture", str(root)], env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
    except OSError:
        pass


def pending(con) -> int:
    ensure(con)
    return con.execute("SELECT COUNT(*) FROM transcript_scans WHERE status IN ('pending','working')").fetchone()[0]


# ---- condensing ----

def _blocks(msg) -> list:
    c = (msg or {}).get("content")
    return c if isinstance(c, list) else ([{"type": "text", "text": c}] if isinstance(c, str) else [])


def condense(lines: list[str]) -> str:
    """Transcript JSONL lines -> compact text: [user] / [agent] / [ran] / [wrote] lines. Harness-injected user turns
    (task notifications, reminders) and hook context are left out; tool output keeps only its tail."""
    from .engine import is_harness
    out: list[str] = []
    pending_cmd: dict[str, str] = {}
    for raw in lines:
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(e, dict) or e.get("isMeta") or e.get("type") not in ("user", "assistant"):
            continue
        for b in _blocks(e.get("message")):
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if e["type"] == "user" and t == "text":
                text = str(b.get("text", "")).strip()
                if text and not is_harness(text) and not text.startswith(("<command-", "<local-command")):
                    out.append("[user] " + " ".join(text.split())[:1500])
            elif e["type"] == "assistant" and t == "text":
                text = " ".join(str(b.get("text", "")).split())
                if text:
                    out.append("[agent] " + text[:800])
            elif t == "tool_use":
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                name = b.get("name", "")
                if name == "Bash" and inp.get("command"):
                    pending_cmd[b.get("id", "")] = " ".join(str(inp["command"]).split())[:300]
                elif name in ("Write", "Edit", "MultiEdit", "NotebookEdit") and inp.get("file_path"):
                    out.append(f"[wrote] {inp['file_path']}")
            elif t == "tool_result" and b.get("tool_use_id") in pending_cmd:
                cmd = pending_cmd.pop(b["tool_use_id"])
                c = b.get("content")
                text = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c if isinstance(x, dict)) \
                    if isinstance(c, list) else ""
                tail = " ".join(text.split())[-300:]
                out.append(f"[ran] `{cmd}` -> {'failed' if b.get('is_error') else 'ok'}" + (f" | {tail}" if tail else ""))
    return redact("\n".join(out))


# ---- model ----

MAX_BRIEF_MEMORIES = 60


def shown_ids(con, session: str) -> set[int]:
    """Memories memcode already put in the main agent's context this session (start block, prompt, first touch)."""
    try:
        return {r[0] for r in con.execute("SELECT memory_id FROM injections WHERE session=?", (session,))}
    except Exception:  # noqa: BLE001
        return set()


def briefing(con, root: str, session: str) -> str:
    """What the memory agent is told before each transcript: which repository and session, and the memory as it
    stands (numbered, so it can update or retire an item; marked when the main agent already has it in context),
    plus the facts."""
    shown = shown_ids(con, session)
    lines = [f"Repository: {os.path.basename(os.path.realpath(root)) or root}", f"Session: {session}",
             "Memory now (number, kind, where it applies, text):"]
    rows = con.execute("SELECT id, trigger, text, anchor_path, scope_path FROM memories WHERE stale=0 "
                       "ORDER BY (trigger='correction') DESC, updated_at DESC LIMIT ?", (MAX_BRIEF_MEMORIES,)).fetchall()
    for r in rows:
        kind = "rule" if r["trigger"] == "correction" else "note"
        body = r["text"].replace("Rule from user correction: ", "", 1) if kind == "rule" else r["text"]
        where = r["anchor_path"] or r["scope_path"] or "repo"
        mark = " (in the agent's context)" if r["id"] in shown else ""
        lines.append(f"- #{r['id']} {kind} [{where}]{mark}: {' '.join(body.split())[:300]}")
    if not rows:
        lines.append("- (empty)")
    try:
        from . import facts
        fl = facts.lines(con, max_lines=12)
    except Exception:  # noqa: BLE001
        fl = []
    lines += ["Facts:"] + (fl or ["- (none)"])
    return "\n".join(lines)


def extract(text: str, context: str = "", model: str | None = None, timeout: int = 120) -> dict | None:
    """One memory-agent call: briefing + condensed transcript -> {"items": [...], "model", "cost_usd"} or None."""
    model = model or os.environ.get("MEMCODE_CAPTURE_MODEL") or DEFAULT_MODEL
    cmd = ["claude", "-p", f"{context}\n\nTranscript:\n{text}", "--model", model, "--effort", "low",
           "--setting-sources", "", "--strict-mcp-config", "--tools", "", "--no-session-persistence",
           "--session-id", str(uuid.uuid4()), "--max-budget-usd", "0.25", "--output-format", "json",
           "--system-prompt", SYSTEM, "--json-schema", SCHEMA]
    env = dict(os.environ, MEMCODE_DISABLE="1")
    try:
        with tempfile.TemporaryDirectory() as cwd:
            p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        out = json.loads(p.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    so = out.get("structured_output") if isinstance(out, dict) and not out.get("is_error") else None
    if not isinstance(so, dict) or not isinstance(so.get("items"), list):
        return None
    return {"items": [i for i in so["items"] if isinstance(i, dict)][:MAX_ITEMS], "model": model,
            "cost_usd": float(out.get("total_cost_usd") or 0.0)}


# ---- checks ----

def _norm(s: str) -> str:
    return " ".join(str(s).lower().split())


def _terms(s: str) -> set:
    from .retrieval import terms
    return terms(s)


def verified(item: dict, condensed: str) -> str | None:
    """'rule' | 'note' | 'env' when the item passes the checks, else None: evidence quoted from the transcript, no
    conflict with the user's rules (the model's flag), nothing about the agent's own memory or tools."""
    ev = _norm(item.get("evidence", ""))
    text = " ".join(str(item.get("text", "")).split())
    if len(ev) < 8 or len(text) < 8 or len(text) > 300 or item.get("conflicts") is True or _SELF.search(text):
        return None
    lines = [_norm(l) for l in condensed.splitlines()]
    hits = [l for l in lines if ev in l]
    if not hits:
        return None
    if item.get("kind") == "rule" and any(l.startswith("[user]") for l in hits):
        return "rule"
    return "env" if item.get("kind") == "env" else "note"


def is_repeat(con, text: str) -> bool:
    t = _terms(text)
    if not t:
        return True
    rows = [r[0] for r in con.execute("SELECT text FROM memories WHERE stale=0")]
    try:
        rows += [r[0] for r in con.execute("SELECT value FROM facts")]
    except Exception:  # noqa: BLE001  (no facts table yet)
        pass
    for other in rows:
        o = _terms(other)
        # most of the NEW item's terms already in one memory; a short fact ("shelf") never swallows a long item
        if len(o) >= 3 and len(t & o) / len(t) >= DUP_OVERLAP:
            return True
    return False


def _anchor(root: str, path: str) -> str:
    p = (path or "").strip().strip("/")
    if not p or p.startswith("..") or os.path.isabs(p):
        return ""
    return p if os.path.exists(os.path.join(root, p)) else ""


def _log(con, session, op, mid, before=None, after=None, evidence=""):
    ensure(con)
    con.execute("INSERT INTO memory_log(ts, session, op, memory_id, before, after, evidence) VALUES(?,?,?,?,?,?,?)",
                (time.time(), session, op, mid, json.dumps(dict(before)) if before is not None else None, after,
                 redact(str(evidence))[:200]))


def _user_evidence(item: dict, condensed: str) -> bool:
    ev = _norm(item.get("evidence", ""))
    return bool(ev) and any(_norm(l).startswith("[user]") and ev in _norm(l) for l in condensed.splitlines())


def change(con, session: str, item: dict, condensed: str) -> int | None:
    """update / retire a numbered memory. Same evidence and conflict checks as add; a user rule changes only on the
    user's own words. Retire deletes the row (staleness is recomputed from the tree, so it cannot hold a withdrawal);
    the old row is kept in memory_log. -> the memory id changed, or None."""
    from . import activity
    op = item.get("op")
    try:
        target = int(item.get("target") or 0)
    except (TypeError, ValueError):
        return None
    row = con.execute("SELECT * FROM memories WHERE id=? AND stale=0", (target,)).fetchone() if target > 0 else None
    if row is None or verified(dict(item, kind="note"), condensed) is None:
        return None
    if op == "update" and echoes_context(con, session, item, condensed):
        return None
    is_rule = row["trigger"] in ("correction", "manual")
    if is_rule and not _user_evidence(item, condensed):
        return None
    text = redact(" ".join(str(item.get("text", "")).split()))[:300]
    ev = item.get("evidence", "")
    if op == "retire":
        _log(con, session, "retire", target, before=row, after=text, evidence=ev)
        from .consolidate import delete_ids
        delete_ids(con, [target])
        activity.note(con, "retired", f"retired #{target}: {text}")
        return target
    if op == "update":
        new = f"Rule from user correction: {text}" if row["trigger"] == "correction" else text
        if new == row["text"]:
            return None
        _log(con, session, "update", target, before=row, after=new, evidence=ev)
        con.execute("UPDATE memories SET text=?, updated_at=? WHERE id=?", (new, time.time(), target))
        activity.note(con, "updated", f"updated #{target}: {text}")
        return target
    return None


def echoes_context(con, session: str, item: dict, condensed: str) -> bool:
    """The item's only evidence is the main agent repeating a memory memcode already showed it this session: an
    [agent] line whose quoted part mostly repeats a shown memory. That is the memory being used, not new knowledge."""
    ev = _norm(item.get("evidence", ""))
    if not ev or any(_norm(l).startswith("[user]") and ev in _norm(l) for l in condensed.splitlines()):
        return False
    t = _terms(ev)
    if not t:
        return False
    shown = shown_ids(con, session)
    if not shown:
        return False
    marks = ",".join("?" * len(shown))
    for (text,) in con.execute(f"SELECT text FROM memories WHERE id IN ({marks})", tuple(shown)):
        o = _terms(text)
        if o and len(t & o) / len(t) >= DUP_OVERLAP:
            return True
    return False


def store_items(con, root: str, session: str, items: list[dict], condensed: str, model: str = "") -> list[int]:
    """Apply the memory agent's operations: add (default), update, retire. -> ids added or changed."""
    from . import activity
    ids = []
    for item in items:
        if item.get("op") in ("update", "retire"):
            mid = change(con, session, item, condensed)
            if mid is not None:
                ids.append(mid)
            continue
        kind = verified(item, condensed)
        text = redact(" ".join(str(item.get("text", "")).split()))[:300]
        if kind is None or is_repeat(con, text) or echoes_context(con, session, item, condensed):
            continue
        prov = {"session": session, "source": "transcript", "model": model, "ts": time.time(),
                "evidence": redact(str(item.get("evidence", "")))[:200]}
        if kind == "env":                  # the agent's environment, not the repo: an env fact (facts.py), not a memory
            import hashlib
            from . import facts
            facts.ensure(con)
            facts._set_derived(con, f"env:obs:{hashlib.sha1(text.lower().encode()).hexdigest()[:10]}", "env",
                               "observed", text, "transcript")
            activity.note(con, "saved", f"env fact: {text}")
            continue
        if kind == "rule":
            body = f"Rule from user correction: {text}"
            mid = store.add_memory(con, "correction", body, "", None, prov, 0.6, commit=False)
            activity.saved(con, "correction", body)
        else:
            a = _anchor(root, item.get("path", ""))
            h = None
            if a and os.path.isfile(os.path.join(root, a)):
                with open(os.path.join(root, a), "rb") as fh:
                    h = store.sha1(fh.read())
            mid = store.add_memory(con, "transcript", text, a, h, prov, 0.5, commit=False)
            activity.saved(con, "transcript", text, a)
        try:
            from . import scope
            sp, sk = scope.assign(con, "correction" if kind == "rule" else "transcript", text, "" if kind == "rule" else a, None)
            con.execute("UPDATE memories SET scope_path=?, scope_kind=? WHERE id=?", (sp, sk, mid))
        except Exception:  # noqa: BLE001  rescope_new retries at session start
            pass
        store.bump(con, session, "captured", commit=False)
        _log(con, session, "add", mid, after=text, evidence=item.get("evidence", ""))
        ids.append(mid)
        if len(ids) >= MAX_ITEMS:
            break
    con.commit()
    return ids


# ---- worker ----

def _claim(con):
    con.execute("BEGIN IMMEDIATE")
    row = con.execute("SELECT session, path, offset, attempts FROM transcript_scans WHERE status='pending' "
                      "ORDER BY ts LIMIT 1").fetchone()
    if row:
        con.execute("UPDATE transcript_scans SET status='working', attempts=attempts+1 WHERE session=?", (row[0],))
    con.commit()
    return row


def scan_one(con, root: str, session: str, path: str, offset: int, extract_fn=extract) -> tuple[int, list[int], float]:
    """Scan transcript lines past `offset`. -> (new offset, stored ids, cost). Raises on a model failure."""
    try:
        with open(path, errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return offset, [], 0.0
    new = lines[offset:]
    condensed = condense(new)
    if len(condensed) < MIN_NEW_CHARS and "[user] " not in condensed:
        return offset, [], 0.0                          # too little yet: kept for the next scan, never skipped
    res = extract_fn(condensed[-MAX_CHARS:], briefing(con, root, session))
    if res is None:
        raise RuntimeError("model call failed")
    ids = store_items(con, root, session, res["items"], condensed, res.get("model", ""))
    return len(lines), ids, res.get("cost_usd", 0.0)


def run_worker(root: str, extract_fn=extract) -> int:
    con = store.connect(root)
    ensure(con)
    stored = 0
    try:
        while True:
            row = _claim(con)
            if not row:
                return stored
            session, path, offset, attempts = row
            try:
                off, ids, cost = scan_one(con, root, session, path, offset, extract_fn)
                stored += len(ids)
                con.execute("UPDATE transcript_scans SET offset=?, status=CASE WHEN status='working' THEN 'idle' "
                            "ELSE status END, cost_usd=cost_usd+?, result=? WHERE session=?",
                            (off, cost, json.dumps({"stored": ids}), session))
            except Exception as e:  # noqa: BLE001
                status = "pending" if attempts + 1 < MAX_ATTEMPTS else "error"
                con.execute("UPDATE transcript_scans SET status=?, result=? WHERE session=?",
                            (status, json.dumps({"error": str(e)[:200]}), session))
            con.commit()
    finally:
        con.close()


if __name__ == "__main__":
    if os.environ.get("MEMCODE_DISABLE"):
        sys.exit(0)
    run_worker(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
