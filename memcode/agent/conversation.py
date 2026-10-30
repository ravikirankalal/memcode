"""The memory agent's running conversation: one per coding session, started when the coding agent starts.

At every SessionStart (startup, resume, clear or compact) memcode opens a fresh conversation with the model: the role
prompt and the full briefing (the memory as it stands), "the coding session starts now". After that, each piece of log
resumes the same conversation and brings only what is new: the latest turns, and a short delta (which of the agent's
last proposals memcode kept, memories that changed by other paths, memories newly shown to the coding agent). The
conversation is started over, with a fresh briefing, after MAX_CALLS calls or once it holds MAX_CONTEXT_TOKENS.
"""
from __future__ import annotations

import glob
import os
import time
import uuid

from . import db, model

MAX_CALLS = 30
MAX_CONTEXT_TOKENS = 40_000
OPENING_NOTE = ("The coding session starts now. There is no transcript yet: reply with an empty items list. From now "
                "on each message brings the newest turns and what changed in the memory since your last reply.")


def start(con, session: str) -> str:
    """A fresh conversation for this coding session (the old one, if any, is dropped). -> its id."""
    db.ensure(con)
    old = con.execute("SELECT agent_session FROM agent_sessions WHERE session=?", (session,)).fetchone()
    sid, now = str(uuid.uuid4()), time.time()
    con.execute("""INSERT INTO agent_sessions(session, agent_session, ready, calls, context_tokens, cost_usd, started,
                   last_ts) VALUES(?,?,0,0,0,0,?,?) ON CONFLICT(session) DO UPDATE SET agent_session=excluded.agent_session,
                   ready=0, calls=0, context_tokens=0, started=excluded.started, last_ts=excluded.last_ts""",
                (session, sid, now, now))
    con.commit()
    if old:
        _forget_file(old[0])
    return sid


def current(con, session: str):
    db.ensure(con)
    row = con.execute("SELECT * FROM agent_sessions WHERE session=?", (session,)).fetchone()
    if row is None:
        start(con, session)
        row = con.execute("SELECT * FROM agent_sessions WHERE session=?", (session,)).fetchone()
    return row


def pending_openings(con) -> list[str]:
    db.ensure(con)
    return [r[0] for r in con.execute("SELECT session FROM agent_sessions WHERE ready=0 AND calls=0")]


def call_args(con, root: str, session: str, piece: str) -> tuple[str, dict]:
    """(context, session) for the next call: the full briefing when the conversation has not opened yet, else the
    delta since the agent's last reply."""
    row = current(con, session)
    cwd = str(_cwd(root))
    if not row["ready"]:
        ctx = model.briefing(con, root, session) + ("" if piece else "\n\n" + OPENING_NOTE)
        return ctx, {"id": row["agent_session"], "resume": False, "cwd": cwd}
    return delta(con, session, row["last_ts"], root), {"id": row["agent_session"], "resume": True, "cwd": cwd}


def record(con, session: str, res: dict, opening: bool = False) -> None:
    """After a call: count it, remember when the agent replied and how big the conversation is; start over when it is
    too long (the next call opens a fresh one with a new briefing)."""
    tokens = int(res.get("context_tokens") or 0)
    con.execute("UPDATE agent_sessions SET ready=1, calls=calls+1, context_tokens=?, last_ts=?, cost_usd=cost_usd+? "
                "WHERE session=?", (tokens, time.time(), float(res.get("cost_usd") or 0) if opening else 0.0, session))
    con.commit()
    row = current(con, session)
    if row["calls"] >= MAX_CALLS or row["context_tokens"] >= MAX_CONTEXT_TOKENS:
        start(con, session)
        con.execute("UPDATE agent_sessions SET calls=-1 WHERE session=?", (session,))   # reopened inline, not by the worker
        con.commit()


def opening_cost(con, session: str) -> float:
    row = con.execute("SELECT cost_usd FROM agent_sessions WHERE session=?", (session,)).fetchone()
    return float(row[0]) if row else 0.0


def delta(con, session: str, since: float, root=None) -> str:
    """What changed since the agent's last reply: what memcode kept of its proposals, memories added or changed by other
    paths (pattern triggers, the user), memories newly shown to the coding agent, and which of those it used."""
    from ..pinned import day, label
    lines = ["Memory changes since your last reply:"]
    for r in con.execute("SELECT op, memory_id, after FROM memory_log WHERE session=? AND ts>? ORDER BY id",
                         (session, since)):
        lines.append(f"- memcode applied your {r['op']} #{r['memory_id']}: {' '.join(str(r['after'] or '').split())[:200]}")
    for r in con.execute("SELECT id, trigger, text, anchor_path, from_user, topic, updated_at FROM memories WHERE stale=0 AND mkey IS NULL "
                         "AND updated_at>? AND "
                         "id NOT IN (SELECT memory_id FROM memory_log WHERE ts>? AND memory_id IS NOT NULL) ORDER BY id",
                         (since, since)):
        kind = f"from you, {day(r['updated_at'])}" if r["from_user"] else label(r)
        text = r["text"]
        lines.append(f"- new or changed #{r['id']} {kind} [{r['anchor_path'] or 'repo'}] ({r['trigger']}): "
                     f"{' '.join(text.split())[:200]}")
    shown = [r[0] for r in con.execute("SELECT DISTINCT memory_id FROM injections WHERE session=? AND ts>? ORDER BY 1",
                                       (session, since))]
    if shown:
        lines.append("- shown to the coding agent since: " + ", ".join(f"#{i}" for i in shown))
    from .. import feedback
    lines += feedback.delta_lines(con, session, since)             # what the coding agent used, and what it did not
    db.ensure(con)
    for r in con.execute("SELECT op, target, text, reason, evidence FROM proposals WHERE session=? AND ts>? ORDER BY id",
                         (session, since)):
        what = f"{r['op']} #{r['target']}" if r["target"] else r["op"]
        lines.append(f"- not kept, your {what} \"{r['text'][:120]}\" (evidence \"{r['evidence'][:80]}\"): {r['reason']}")
    from .curate import file_text
    for r in con.execute("SELECT id, trigger, text, anchor_path, topic, updated_at, unusual FROM memories WHERE stale=1 "
                         "AND mkey IS NULL AND updated_at>? ORDER BY id", (since,)):
        now = file_text(root, r["anchor_path"], 300)
        lines.append(f"- went stale (its file changed): #{r['id']} {label(r)} [{r['anchor_path']}]: "
                     f"{' '.join(r['text'].split())[:200]}" + (f" | the file now begins: {now}" if now
                                                                else " | the file is gone"))
    if len(lines) == 1:
        lines.append("- none")
    return "\n".join(lines)


def _cwd(root: str):
    """Where the conversation lives: Claude Code keeps resumable sessions per working directory."""
    from ..store import memdir
    d = memdir(root) / "agent"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _forget_file(agent_session: str) -> None:
    """Best effort: remove a finished conversation's saved transcript so they do not pile up."""
    for p in glob.glob(os.path.expanduser(f"~/.claude/projects/*/{agent_session}.jsonl")):
        try:
            os.remove(p)
        except OSError:
            pass
