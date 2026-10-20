"""Applying the memory agent's operations (add, update, retire) after the checks, best-rated first; decisions with
their subjects and expiry; every change logged in memory_log."""
from __future__ import annotations

import hashlib
import json
import os
import time

from .. import store
from . import checks, db

MAX_ITEMS = 4                # memories kept per piece: the most important candidates
MIN_IMPORTANCE = 4           # a note rated below this is not kept
MIN_RULE_IMPORTANCE = 3      # the user's own rules and decisions get more room
DECISION_DAYS = 30           # a decision is shown this long after it was last stated (MEMCODE_DECISION_DAYS), then expires
MAX_ENV_FACTS = 12           # observed environment limits kept (newest win)


def decisions_enabled(root) -> bool:
    """Decision capture (#42): on with the memory agent; off with `memcode config decision-capture off` or
    MEMCODE_DECISION_CAPTURE=0."""
    from .. import config
    return config.switch(root, "MEMCODE_DECISION_CAPTURE", "decision_capture", True)

def decision_days() -> float:
    try:
        return float(os.environ.get("MEMCODE_DECISION_DAYS") or DECISION_DAYS)
    except ValueError:
        return DECISION_DAYS

def expire_decisions(con, session: str = "") -> int:
    """Delete decisions not restated for decision_days(); each is kept in memory_log ('expire')."""
    cutoff = time.time() - decision_days() * 86400
    rows = con.execute("SELECT * FROM memories WHERE trigger='decision' AND updated_at < ?", (cutoff,)).fetchall()
    for r in rows:
        _log(con, session, "expire", r["id"], before=r, after=f"expired after {decision_days():g} days")
    if rows:
        store.delete_ids(con, [r["id"] for r in rows])
        con.commit()
    return len(rows)

def unpin_howtos(con) -> int:
    """Notes stored before pins_content existed: drop the content pin of how-tos and non-code notes, so a still-true
    note stops going stale on every edit (session start revives the ones staled that way)."""
    rows = con.execute("SELECT id, text, anchor_path FROM memories WHERE trigger='transcript' "
                       "AND anchor_hash IS NOT NULL").fetchall()
    ids = [r["id"] for r in rows if not checks.pins_content(r["text"], r["anchor_path"])]
    if ids:
        con.executemany("UPDATE memories SET anchor_hash=NULL WHERE id=?", [(i,) for i in ids])
        con.commit()
    return len(ids)

def _anchor(root: str, path: str) -> str:
    p = (path or "").strip().strip("/")
    if not p or p.startswith("..") or os.path.isabs(p):
        return ""
    return p if os.path.exists(os.path.join(root, p)) else ""

def _log(con, session, op, mid, before=None, after=None, evidence=""):
    db.ensure(con)
    con.execute("INSERT INTO memory_log(ts, session, op, memory_id, before, after, evidence) VALUES(?,?,?,?,?,?,?)",
                (time.time(), session, op, mid, json.dumps(dict(before)) if before is not None else None, after,
                 str(evidence)[:200]))

def change(con, session: str, item: dict, condensed: str) -> int | None:
    """update / retire a numbered memory. Same evidence and conflict checks as add; a user rule changes only on the
    user's own words. Retire deletes the row (staleness is recomputed from the tree, so it cannot hold a withdrawal);
    the old row is kept in memory_log. -> the memory id changed, or None."""
    from .. import activity
    op = item.get("op")
    try:
        target = int(item.get("target") or 0)
    except (TypeError, ValueError):
        return None
    row = con.execute("SELECT * FROM memories WHERE id=? AND stale=0", (target,)).fetchone() if target > 0 else None
    if row is None or checks.verified(dict(item, kind="note"), condensed) is None:
        return None
    if op == "update" and checks.echoes_context(con, session, item, condensed):
        return None
    is_rule = row["trigger"] in ("correction", "manual")
    if is_rule and (not checks.user_evidence(item, condensed) or checks.verified(dict(item, kind="rule"), condensed) != "rule"):
        return None
    if row["trigger"] == "decision" and checks.verified(dict(item, kind="decision"), condensed) != "decision":
        return None
    text = " ".join(str(item.get("text", "")).split())[:300]
    ev = item.get("evidence", "")
    if op == "retire":
        _log(con, session, "retire", target, before=row, after=text, evidence=ev)
        store.delete_ids(con, [target])
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

def store_items(con, root: str, session: str, items: list[dict], condensed: str, model: str = "",
                stats: dict | None = None) -> list[int]:
    """Apply the memory agent's operations: add (default), update, retire. -> ids added or changed."""
    from .. import activity
    ids = []
    added = 0

    def rating(item) -> int:
        try:
            return int(item.get("importance", MIN_IMPORTANCE))   # older callers without ratings: kept as before
        except (TypeError, ValueError):
            return MIN_IMPORTANCE
    # corrections first (update / retire keep the memory true whatever their rating), then the most important adds
    items = sorted(items, key=lambda it: (it.get("op") not in ("update", "retire"), -rating(it)))
    for item in items:
        if item.get("op") in ("update", "retire"):
            mid = change(con, session, item, condensed)
            if mid is not None:
                ids.append(mid)
            continue
        floor = MIN_RULE_IMPORTANCE if item.get("kind") in ("rule", "decision") else MIN_IMPORTANCE
        if rating(item) < floor or added >= MAX_ITEMS:
            continue
        kind = checks.verified(item, condensed, root)
        text = " ".join(str(item.get("text", "")).split())[:300]
        if kind is None or checks.is_repeat(con, text) or checks.echoes_context(con, session, item, condensed):
            continue
        prov = {"session": session, "source": "transcript", "model": model, "ts": time.time(),
                "evidence": str(item.get("evidence", ""))[:200],
                "category": str(item.get("category", ""))[:20], "importance": rating(item)}
        if kind == "env":                  # the agent's environment, not the repo: an env fact (facts.py), not a memory
            from .. import facts
            facts.ensure(con)
            facts._set_derived(con, f"env:obs:{hashlib.sha1(text.lower().encode()).hexdigest()[:10]}", "env",
                               "observed", text, "transcript")
            con.execute("""DELETE FROM facts WHERE key LIKE 'env:obs:%' AND key NOT IN (SELECT key FROM facts
                           WHERE key LIKE 'env:obs:%' ORDER BY last_seen DESC LIMIT ?)""", (MAX_ENV_FACTS,))
            activity.note(con, "saved", f"env fact: {text}")
            added += 1
            if stats is not None:                 # kept, though not a memory row: counted for the scan line
                stats["facts"] = stats.get("facts", 0) + 1
            continue
        if kind == "decision":
            if not decisions_enabled(root):
                continue
            subject = " ".join(str(item.get("subject", "")).split())[:40].lower()
            prov["subject"] = subject
            if subject:                    # a newer decision on the same subject replaces the older one
                old = [r for r in con.execute("SELECT * FROM memories WHERE trigger='decision'")
                       if (db.loads(r["provenance"]).get("subject") or "") == subject]
                for r in old:
                    _log(con, session, "retire", r["id"], before=r, after=f"replaced by a newer decision on {subject}",
                         evidence=item.get("evidence", ""))
                if old:
                    store.delete_ids(con, [r["id"] for r in old])
            mid = store.add_memory(con, "decision", text, "", None, prov, 0.6, commit=False)
            activity.note(con, "saved", f"decision: {text}")
        elif kind == "rule":
            body = f"Rule from user correction: {text}"
            mid = store.add_memory(con, "correction", body, "", None, prov, 0.6, commit=False)
            activity.saved(con, "correction", body)
        else:
            a = _anchor(root, item.get("path", ""))
            h = None
            if a and os.path.isfile(os.path.join(root, a)) and checks.pins_content(text, a):
                with open(os.path.join(root, a), "rb") as fh:
                    h = store.sha1(fh.read())
            mid = store.add_memory(con, "transcript", text, a, h, prov, 0.5, commit=False)
            activity.saved(con, "transcript", text, a)
        try:
            from .. import scope
            if kind != "decision":             # decisions are repo-wide context: no folder scope
                sp, sk = scope.assign(con, "correction" if kind == "rule" else "transcript", text,
                                      "" if kind == "rule" else a, None)
                con.execute("UPDATE memories SET scope_path=?, scope_kind=? WHERE id=?", (sp, sk, mid))
        except Exception:  # noqa: BLE001  rescope_new retries at session start
            pass
        store.bump(con, session, "captured", commit=False)
        _log(con, session, "add", mid, after=text, evidence=item.get("evidence", ""))
        ids.append(mid)
        added += 1
    con.commit()
    return ids
