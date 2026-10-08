"""Reinforcement signal, shadow mode: memories gain or lose confidence from verified outcomes.

Retrieval alone never reinforces (that is the rich-get-richer loop the plan warns about). A memory
shown in a session (see the `injections` table) gets an outcome only from evidence in that session:

  anchored memory (file or function):
    success   the agent edited the anchor file after the memory was shown, and a later test command passed
    failure   the same kind of mistake recurred on that anchor in the session (a new fail_to_fix/revert there)
    irrelevant  the anchor was not touched            -> no change
    exposed     touched, but no passing test followed  -> no change
  user rule (repo-wide `correction`):
    failure   the user had to state the same rule again (recorded when the duplicate is detected)
    exposed   otherwise -> no change. Whether a rule was relevant cannot be verified without semantics,
              so rules are never positively reinforced.

Sessions are scored lazily at the next SessionStart, once quiet for QUIET_S, from the logged events.
Only `memories.confidence` changes; `updated_at` (used for ordering) is untouched, so nothing here
affects what the pinned block shows. Confidence is not used for ranking in Phase 1.
"""
from __future__ import annotations

import json
import os
import re
import time

# A test runner in COMMAND position (start of the command or after ; & |), not as an argument
# (so `cat pytest.ini` or `echo npm test` are not tests).
TEST_CMD = re.compile(r"(?:^|[;&|]\s*)(?:(?:\S*/)?(?:pytest|py\.test|tox|nox|jest|vitest|rspec)|\./qa"
                      r"|(?:python3?|py) -m (?:pytest|unittest)"
                      r"|(?:npm|yarn|pnpm) (?:run )?test|(?:go|cargo|mvn|gradle|dotnet|mix) test"
                      r"|make (?:test|check))(?=\s|$)")
QUIET_S = 30 * 60
UP, DOWN, FLOOR, CAP = 0.1, 0.7, 0.05, 0.95


def record(con, session: str, memory_id: int, outcome: str, commit: bool = True) -> bool:
    """Store one outcome per (session, memory); the first one wins. Returns True if new."""
    cur = con.execute("INSERT OR IGNORE INTO outcomes(session, memory_id, outcome, ts) VALUES(?,?,?,?)",
                      (session, memory_id, outcome, time.time()))
    if cur.rowcount and outcome.startswith(("success", "failure")):
        _apply(con, memory_id, outcome)
    if commit:
        con.commit()
    return bool(cur.rowcount)


def _apply(con, memory_id: int, outcome: str) -> None:
    r = con.execute("SELECT confidence FROM memories WHERE id=?", (memory_id,)).fetchone()
    if r is None:
        return
    c = r[0]
    new = min(CAP, c + UP * (1.0 - c) + 0.02) if outcome.startswith("success") else max(FLOOR, c * DOWN)
    con.execute("UPDATE memories SET confidence=? WHERE id=?", (new, memory_id))   # NOT updated_at


def _rel(root: str, p: str) -> str:
    if not p:
        return ""
    if os.path.isabs(p):
        try:
            p = os.path.relpath(os.path.realpath(p), os.path.realpath(root))
        except ValueError:
            return ""
    return p.replace(os.sep, "/").lstrip("./") if not p.startswith("..") else ""


def _score_session(con, root: str, sess: str) -> int:
    events = [json.loads(r[0]) for r in con.execute("SELECT payload FROM events WHERE session=? ORDER BY id", (sess,))]
    edits: list[tuple[int, str]] = []          # (event index, rel path) of agent edits
    passes: list[int] = []                     # event indexes of passing test commands
    for i, e in enumerate(events):
        tool = str(e.get("tool") or "").lower()
        inp = e.get("input") if isinstance(e.get("input"), dict) else {}
        if e.get("kind") == "tool_use" and tool in ("edit", "write", "multiedit", "notebookedit"):
            edits.append((i, _rel(root, inp.get("file_path") or inp.get("notebook_path") or "")))
        if e.get("kind") == "tool_result" and tool == "bash" and e.get("exit_code") == 0 \
                and TEST_CMD.search(str(inp.get("command") or e.get("command") or "")):
            passes.append(i)
    born = con.execute("SELECT trigger, anchor_path, anchor_symbol, provenance FROM memories "
                       "WHERE trigger IN ('fail_to_fix','revert')").fetchall()
    recurred = {(r[1], r[2]) for r in born if json.loads(r[3] or "{}").get("session") == sess}
    n = 0
    shown = con.execute("""SELECT DISTINCT m.id, m.trigger, m.anchor_path, m.anchor_symbol FROM injections i
                           JOIN memories m ON m.id=i.memory_id WHERE i.session=?""", (sess,)).fetchall()
    for mid, trig, anchor, sym in shown:
        if not anchor:                      # repo-wide rule: only the write-time "repeated" failure applies
            n += record(con, sess, mid, "exposed", commit=False)
            continue
        if (anchor, sym) in recurred or (not sym and any(a == anchor for a, _ in recurred)):
            n += record(con, sess, mid, "failure:recurred", commit=False)
            continue
        touched = [i for i, p in edits if p == anchor]
        if not touched:
            n += record(con, sess, mid, "irrelevant", commit=False)
        elif any(p > touched[-1] for p in passes):
            n += record(con, sess, mid, "success:tests_passed", commit=False)
        else:
            n += record(con, sess, mid, "exposed", commit=False)
    return n


def score_finished_sessions(con, root: str, current_session: str | None = None,
                            now: float | None = None) -> int:
    """Score every session that was shown memories, is not the current one, has been quiet for
    QUIET_S, and has not been scored yet. Idempotent. Returns the number of outcomes recorded."""
    now = time.time() if now is None else now
    todo = con.execute("""SELECT i.session, MAX(i.ts) FROM injections i
                          WHERE i.session NOT IN (SELECT session FROM scored_sessions) GROUP BY i.session""").fetchall()
    n = 0
    for sess, shown_at in todo:
        if sess == current_session:
            continue
        last = con.execute("SELECT MAX(ts) FROM events WHERE session=?", (sess,)).fetchone()[0]
        if max(last or 0, shown_at or 0) > now - QUIET_S:
            continue                        # may still be running (e.g. another terminal)
        n += _score_session(con, root, sess)
        con.execute("INSERT OR IGNORE INTO scored_sessions(session, ts) VALUES(?,?)", (sess, now))
    con.commit()
    return n
