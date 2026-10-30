"""The detached worker: the Stop hook queues the session's log, the worker reads the new part piece by piece within the
session budget, applies what the model proposes, and reports scans, failures and a spent budget on the status feed."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .. import store
from . import conversation, curate, db, model, transcript

MIN_NEW_CHARS = 400          # a scan needs at least this much new condensed text
MAX_ATTEMPTS = 2
USD_PER_1K_LINES = 0.03      # about what scanning 1,000 transcript lines costs on Haiku (for the docs; no limit)


def session_budget(n_lines: int) -> float:
    """What one session may spend: unlimited by default (every turn is read); MEMCODE_CAPTURE_BUDGET_USD sets a limit,
    past which the rest of that session is skipped and reported. (Each model call is still capped at $0.25.)"""
    env = os.environ.get("MEMCODE_CAPTURE_BUDGET_USD")
    if env:
        try:
            v = float(env)
            if v > 0:
                return v
        except ValueError:
            pass
    return float("inf")

def enabled(root) -> bool:
    """On by default since 0.9.0 (tc2 gate, bench/live/RESULTS.md Run 17). Off with MEMCODE_TRANSCRIPT_CAPTURE=0 or
    `memcode config memory-agent off`, and wherever the `claude` CLI it calls is not installed."""
    from .. import config
    if not config.switch(root, "MEMCODE_TRANSCRIPT_CAPTURE", "transcript_capture", True):
        return False
    import shutil
    return shutil.which("claude") is not None

def enqueue(con, session: str, path: str) -> None:
    db.ensure(con)
    con.execute("""INSERT INTO transcript_scans(session, path, status, ts) VALUES(?,?,'pending',?)
                   ON CONFLICT(session) DO UPDATE SET path=excluded.path, status='pending', attempts=0,
                   ts=excluded.ts, offset=CASE WHEN transcript_scans.path=excluded.path THEN offset ELSE 0 END""",
                (session, path, time.time()))          # another transcript file: its lines start at 0
    con.commit()

def spawn_worker(root: str, *extra: str) -> None:
    """Start a detached worker; it exits when nothing is pending (extra: ['--bootstrap'] reads the repository once
    instead, agent/bootstrap.py). Never raises."""
    try:
        pkg_parent = str(Path(__file__).resolve().parent.parent.parent)
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in (pkg_parent, os.environ.get("PYTHONPATH")) if p))
        # started from the plugin's own directory: `-m` puts the working directory first on the import path, and the
        # user's repository must never shadow memcode's imports
        subprocess.Popen([sys.executable, "-m", "memcode.agent", str(root), *extra], env=env, cwd=pkg_parent,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
    except OSError:
        pass

def pending(con) -> int:
    db.ensure(con)
    return con.execute("SELECT COUNT(*) FROM transcript_scans WHERE status IN ('pending','working')").fetchone()[0]

def _claim(con):
    con.execute("BEGIN IMMEDIATE")
    row = con.execute("SELECT session, path, offset, attempts FROM transcript_scans WHERE status='pending' "
                      "ORDER BY ts LIMIT 1").fetchone()
    if row:
        con.execute("UPDATE transcript_scans SET status='working', attempts=attempts+1 WHERE session=?", (row[0],))
    con.commit()
    return row

def scan_one(con, root: str, session: str, path: str, offset: int, extract_fn=model.extract,
             stats: dict | None = None) -> tuple[int, list[int], float]:
    """Scan transcript lines past `offset`, a chunk of at most MAX_CHARS condensed text per model call, oldest first.
    The offset and cost are saved after each chunk, so a failure (or the session budget running out) never skips
    text that was not sent (#34). -> (new offset, stored ids, cost). Raises on a model failure."""
    try:
        with open(path, errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return offset, [], 0.0
    if offset > len(lines):
        offset = 0                                      # the file was rewritten shorter: scan it again from the top
    new = lines[offset:]
    condensed = transcript.condense(new)
    if len(condensed) < MIN_NEW_CHARS and "[user] " not in condensed:
        return offset, [], 0.0                          # too little yet: kept for the next scan, never skipped
    from .. import feedback
    row = con.execute("SELECT result FROM transcript_scans WHERE session=?", (session,)).fetchone()
    judged_at = db.loads(row[0]).get("judged_at") if row else None
    if judged_at is not None or offset == 0:            # did the coding agent use what memcode showed it?
        feedback.judge(con, session, condensed, since=judged_at or 0.0)
    # (a session read before judging existed: its earlier showings were answered in text already read, so this scan
    # only starts the clock)
    con.execute("UPDATE transcript_scans SET result=json_set(COALESCE(result, '{}'), '$.judged_at', ?) WHERE session=?",
                (time.time(), session))
    budget = session_budget(len(lines))
    spent = con.execute("SELECT cost_usd FROM transcript_scans WHERE session=?", (session,)).fetchone()
    total = (spent[0] if spent else 0.0) + conversation.opening_cost(con, session)
    ids: list[int] = []
    cost, start = 0.0, offset
    for end, piece in transcript.chunks(new):
        if total + cost >= budget:                      # this session's budget is spent: skip the rest, and say so
            _skipped(con, session, len(lines) - offset, budget)
            return len(lines), ids, cost
        if _converses(extract_fn):                      # the running conversation: briefing once, then deltas
            ctx, convo = conversation.call_args(con, root, session, piece)
            res = extract_fn(piece, ctx, session=convo)
        else:                                           # a one-off call with the full briefing
            res = extract_fn(piece, model.briefing(con, root, session))
        if res is None or "error" in res:
            raise RuntimeError((res or {}).get("error") or "model call failed")
        if _converses(extract_fn):
            conversation.record(con, session, res)
        ids += curate.store_items(con, root, session, res["items"], piece, res.get("model", ""))
        cost += res.get("cost_usd", 0.0)
        if stats is not None:
            stats["candidates"] = stats.get("candidates", 0) + len(res["items"])
            stats["pieces"] = stats.get("pieces", 0) + 1
        offset = start + end
        con.execute("UPDATE transcript_scans SET offset=?, cost_usd=? WHERE session=?",
                    (offset, total + cost, session))
        con.commit()
    return offset, ids, cost

def _converses(extract_fn) -> bool:
    import inspect
    try:
        return "session" in inspect.signature(extract_fn).parameters
    except (TypeError, ValueError):
        return False


def open_conversations(con, root: str, extract_fn=model.extract) -> int:
    """Send the opening briefing of every conversation started at SessionStart and not opened yet. -> opened."""
    if not _converses(extract_fn):
        return 0
    n = 0
    for session in conversation.pending_openings(con):
        ctx, convo = conversation.call_args(con, root, session, "")
        res = extract_fn("", ctx, session=convo)
        if res is None or "error" in res:
            from .. import activity
            activity.problem(con, "capture", f"memory agent: {(res or {}).get('error') or 'model call failed'}")
            continue
        conversation.record(con, session, res, opening=True)
        n += 1
    return n


def _skipped(con, session: str, n: int, budget: float) -> None:
    """Add `n` to the session's unscanned lines (they never get scanned) and note the budget that applied."""
    con.execute("UPDATE transcript_scans SET result=json_set(COALESCE(result, '{}'), '$.skipped_lines', "
                "COALESCE(json_extract(result, '$.skipped_lines'), 0) + ?, '$.budget_usd', ?) WHERE session=?",
                (n, round(budget, 2), session))

def _skipped_lines(con, session: str) -> int:
    row = con.execute("SELECT result FROM transcript_scans WHERE session=?", (session,)).fetchone()
    return int(db.loads(row[0]).get("skipped_lines") or 0) if row else 0

def run_worker(root: str, extract_fn=model.extract) -> int:
    con = store.connect(root)
    db.ensure(con)
    curate.unpin_howtos(con)
    curate.expire_decisions(con)
    curate.evict_stale(con)
    stored = 0
    from .. import activity
    try:
        if conversation.pending_openings(con):          # the coding agent just started: open its memory agent first
            activity.busy(con, "agent", True)
            open_conversations(con, root, extract_fn)
        while True:
            row = _claim(con)
            if not row:
                return stored
            activity.busy(con, "agent", True)          # the status bar shows the agent reading
            session, path, offset, attempts = row
            skipped_before = _skipped_lines(con, session)
            stats: dict = {}
            try:
                off, ids, _ = scan_one(con, root, session, path, offset, extract_fn, stats)   # saves cost per chunk
                stored += len(ids)
                if stats.get("pieces"):          # the agent looked: say so, also when it kept nothing
                    activity.note(con, "scanned", scan_line(stats["candidates"], len(ids)),
                                  stats["candidates"])
                prev = con.execute("SELECT result FROM transcript_scans WHERE session=?", (session,)).fetchone()
                last = db.loads(prev[0]) if prev else {}
                keep = {k: last[k] for k in ("skipped_lines", "budget_usd") if k in last and last.get("skipped_lines")}
                if "judged_at" in last:          # the feedback clock (scan_one) must survive this rewrite
                    keep["judged_at"] = last["judged_at"]
                con.execute("UPDATE transcript_scans SET offset=?, status=CASE WHEN status='working' THEN 'idle' "
                            "ELSE status END, result=? WHERE session=?",
                            (off, json.dumps({"stored": ids, **keep}), session))
                activity.problem(con, "capture", None)
                if keep.get("skipped_lines", 0) > skipped_before:   # the budget ran out in this scan: on the bar too
                    activity.problem(con, "budget", f"memory agent: this session's ${keep['budget_usd']} budget is "
                                     f"spent; {keep['skipped_lines']} transcript lines not scanned (raise "
                                     f"MEMCODE_CAPTURE_BUDGET_USD)")
                else:
                    activity.problem(con, "budget", None)
            except Exception as e:  # noqa: BLE001
                status = "pending" if attempts + 1 < MAX_ATTEMPTS else "error"
                con.execute("UPDATE transcript_scans SET status=?, result=? WHERE session=?",
                            (status, json.dumps({"error": str(e)[:300]}), session))
                if status == "error":                   # say so where the user looks: status bar, /memcode:status
                    activity.problem(con, "capture", f"memory agent: {str(e)[:200]}")
            con.commit()
    finally:
        activity.busy(con, "agent", False)
        con.close()


def scan_line(candidates: int, kept: int) -> str:
    """'15 candidates, kept 6': kept counts every memory added or changed (environment ones included)."""
    return f"{candidates} candidate{'s' * (candidates != 1)}, kept {kept}"


def health(con) -> str | None:
    """One line for `memcode stats` / `/memcode:status` when the memory agent is failing or skipped text, else None."""
    db.ensure(con)
    row = con.execute("SELECT session, status, result, ts FROM transcript_scans ORDER BY ts DESC LIMIT 1").fetchone()
    if row is None:
        return None
    res = db.loads(row["result"])
    if row["status"] == "error" or (row["status"] == "pending" and res.get("error")):
        return f"memory agent FAILING: {res.get('error') or 'unknown error'} (session {row['session'][:8]})"
    if res.get("skipped_lines"):
        return (f"memory agent: session {row['session'][:8]} spent its budget (${res.get('budget_usd', '?')}; raise it "
                f"with MEMCODE_CAPTURE_BUDGET_USD); {res['skipped_lines']} transcript lines were not scanned")
    return None

