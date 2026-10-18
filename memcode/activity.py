"""Activity feed for status displays: `.memcode/activity.json`, rewritten whenever memcode saves or injects memory.

  {"version": 1, "updated": <epoch s>, "counts": {"memories", "rules", "notes", "facts"},
   "events": [{"ts", "kind", "text", "n"}, ...]}            newest last, at most MAX_EVENTS

kind: saved (a memory was captured or added), start (session-start block), recalled (per-prompt retrieval),
touch (scoped memories on a first read), held (a first write refused with the folder's rules), forgot (memories
deleted with `memcode forget` / `prune-stale`). Read by the memcode
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
    live, rules = con.execute("SELECT COUNT(*), COALESCE(SUM(trigger='correction'), 0) FROM memories "
                              "WHERE stale=0").fetchone()
    try:
        facts = con.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    except Exception:  # noqa: BLE001  (no facts table yet)
        facts = 0
    return {"memories": live, "rules": rules, "notes": live - rules, "facts": facts}


def note(con, kind: str, text: str, n: int = 1) -> None:
    """Append one event and refresh the counts (atomic replace)."""
    try:
        p = _path(con)
        if not p:
            return
        try:
            with open(p) as fh:
                data = json.load(fh)
            events = data.get("events") if isinstance(data, dict) else None
        except (OSError, ValueError):
            events = None
        events = [e for e in (events or []) if isinstance(e, dict)][-(MAX_EVENTS - 1):]
        now = time.time()
        events.append({"ts": now, "kind": kind, "text": " ".join(str(text).split())[:160], "n": n})
        tmp = f"{p}.{os.getpid()}.tmp"
        with open(tmp, "w") as fh:
            json.dump({"version": 1, "updated": now, "counts": _counts(con), "events": events}, fh)
        os.replace(tmp, p)
    except Exception:  # noqa: BLE001  a status feed must never break a hook
        pass


def saved(con, trigger: str, text: str, anchor: str = "") -> None:
    if trigger == "correction":
        from .pinned import _rule_text
        note(con, "saved", f"rule: {_rule_text(text)}")
    else:
        note(con, "saved", f"{trigger.replace('_', '-')} note" + (f" on {anchor}" if anchor else "") + f": {text}")
