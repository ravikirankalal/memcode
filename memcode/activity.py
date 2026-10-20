"""Activity feed for status displays: `.memcode/activity.json`, rewritten whenever memcode saves or injects memory.

  {"version": 1, "updated": <epoch s>, "counts": {"memories", "rules", "notes", "facts"},
   "events": [{"ts", "kind", "text", "n"}, ...],            newest last, at most MAX_EVENTS
   "problems": {"capture": "<why>"},                         what is broken right now; absent when nothing is
   "busy": {"agent": <since epoch s>}}                       what is working right now (the memory agent reading)

kind: saved (a memory was captured or added), start (session-start block), recalled (per-prompt retrieval),
touch (scoped memories on a first read), held (a first write refused with the folder's rules), forgot (memories
deleted with `memcode forget` / `prune-stale`), scanned (the memory agent read the latest turns: candidates, kept),
updated / retired (the memory agent changed a memory). Read by the memcode
status mod (mods/memcode-status) and anything else that wants a live view; never read back by memcode itself.
Writing it can never break a hook: every failure is swallowed.
"""
from __future__ import annotations

import json
import os
import time

MAX_EVENTS = 20
FILE = "activity.json"


def _path(con) -> str | None:
    for _, name, path in con.execute("PRAGMA database_list"):
        if name == "main" and path:
            return os.path.join(os.path.dirname(path), FILE)
    return None


def _counts(con) -> dict:
    live, rules = con.execute("SELECT COUNT(*), COALESCE(SUM(from_user), 0) FROM memories "
                              "WHERE stale=0").fetchone()
    try:
        facts = con.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    except Exception:  # noqa: BLE001  (no facts table yet)
        facts = 0
    return {"memories": live, "rules": rules, "notes": live - rules, "facts": facts}


def note(con, kind: str, text: str, n: int = 1) -> None:
    """Append one event and refresh the counts (atomic replace)."""
    _write(con, {"ts": time.time(), "kind": kind, "text": " ".join(str(text).split())[:160], "n": n})


def problem(con, key: str, text: str | None) -> None:
    """Set (text) or clear (None) a standing problem, shown until it is cleared (#34: a failing memory agent)."""
    _write(con, None, (key, " ".join(text.split())[:240] if text else None))


def busy(con, key: str, on: bool) -> None:
    """Mark (on) or clear a piece of memcode as working right now, e.g. the memory agent reading a turn; the status bar
    shows it while it lasts (and ignores a mark left behind by a worker that died)."""
    _write(con, None, busy=(key, time.time() if on else None))


def _write(con, event: dict | None, prob: tuple[str, str | None] | None = None,
           busy: tuple[str, float | None] | None = None) -> None:
    try:
        p = _path(con)
        if not p:
            return
        try:
            with open(p) as fh:
                data = json.load(fh)
            data = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            data = {}
        events = [e for e in (data.get("events") or []) if isinstance(e, dict)]
        problems = data.get("problems") if isinstance(data.get("problems"), dict) else {}
        working = data.get("busy") if isinstance(data.get("busy"), dict) else {}
        if busy:
            if busy[1]:
                working[busy[0]] = busy[1]
            elif busy[0] in working:
                working.pop(busy[0])
            else:
                return
        if prob:
            if prob[1]:
                problems[prob[0]] = prob[1]
            elif prob[0] in problems:
                problems.pop(prob[0])
            else:
                return                     # nothing to clear: no rewrite
        if event:
            events = events[-(MAX_EVENTS - 1):] + [event]
        now = time.time()
        tmp = f"{p}.{os.getpid()}.tmp"
        out = {"version": 1, "updated": now, "counts": _counts(con), "events": events}
        if problems:
            out["problems"] = problems
        if working:
            out["busy"] = working
        with open(tmp, "w") as fh:
            json.dump(out, fh)
        os.replace(tmp, p)
    except Exception:  # noqa: BLE001  a status feed must never break a hook
        pass


def saved(con, trigger: str, text: str, anchor: str = "", from_user: bool | None = None) -> None:
    if trigger == "correction" if from_user is None else from_user:
        from .pinned import _rule_text
        note(con, "saved", f"rule: {_rule_text(text)}")
    else:
        note(con, "saved", f"{trigger.replace('_', '-')} note" + (f" on {anchor}" if anchor else "") + f": {text}")
