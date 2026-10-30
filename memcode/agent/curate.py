"""Applying the memory agent's operations (add, update, retire) after the checks, best-rated first; decisions with
their subjects and expiry; every change logged in memory_log."""
from __future__ import annotations

import json
import os
import time

from .. import store
from . import checks, db

MAX_ITEMS = 6                # memories kept per piece: the most important candidates
MIN_IMPORTANCE = 4           # a note rated below this is not kept
MIN_RULE_IMPORTANCE = 3      # the user's own rules and decisions get more room, and so do project knowledge and the unusual
MIN_REFERENCE_IMPORTANCE = 2 # links shared or opened (topic reference) and where docs and scripts live (location)
# project knowledge the agent infers (the project profile: stack, component, ...): kept from a rating of 3, and never
# pinned to its file's content (a central class's summary is updated, not hidden on every edit)
from ..kinds import PROFILE_TOPICS as KNOWLEDGE  # noqa: E402  (one list for keeping and showing)
DECISION_DAYS = 30           # a decision is shown this long after it was last stated (MEMCODE_DECISION_DAYS), then expires
MAX_LINKS = 5                # links the agent may give one memory


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
    """Delete decisions past their expiry (decision_days() after last stated); each is kept in memory_log ('expire')."""
    rows = con.execute("SELECT * FROM memories WHERE topic='decision' AND expires_at < ?", (time.time(),)).fetchall()
    for r in rows:
        _log(con, session, "expire", r["id"], before=r, after=f"expired after {decision_days():g} days")
    if rows:
        store.delete_ids(con, [r["id"] for r in rows])
        con.commit()
    return len(rows)

STALE_DAYS = 14             # a stale memory nobody updated is evicted after this long (MEMCODE_STALE_DAYS)


def stale_days() -> float:
    try:
        return float(os.environ.get("MEMCODE_STALE_DAYS") or STALE_DAYS)
    except ValueError:
        return STALE_DAYS


def evict_stale(con, session: str = "") -> int:
    """Delete memories stale for stale_days() (their file changed or went away, and the memory agent neither updated
    nor retired them); each is kept in memory_log ('evict'). Measured memories (facts) are left to facts.py."""
    from .. import activity
    cutoff = time.time() - stale_days() * 86400
    rows = con.execute("SELECT * FROM memories WHERE stale=1 AND mkey IS NULL AND updated_at < ?", (cutoff,)).fetchall()
    for r in rows:
        _log(con, session, "evict", r["id"], before=r, after=f"stale for over {stale_days():g} days")
    if rows:
        store.delete_ids(con, [r["id"] for r in rows])
        con.commit()
        activity.note(con, "retired", f"evicted {len(rows)} memor{'y' if len(rows) == 1 else 'ies'} stale for over "
                      f"{stale_days():g} days", len(rows))
    return len(rows)


def file_text(root, path: str, n: int = 0) -> str:
    """A repository file on one line ('' when missing); n > 0: its first n characters."""
    if not root or not path:
        return ""
    try:
        with open(os.path.join(str(root), path), errors="replace") as fh:
            t = " ".join(fh.read(400_000).split())
    except OSError:
        return ""
    return t[:n] if n else t


def unpin_howtos(con) -> int:
    """Notes stored before pins_content existed: drop the content pin of how-tos and non-code notes, so a still-true
    note stops going stale on every edit (session start revives the ones staled that way)."""
    rows = con.execute("SELECT id, text, anchor_path FROM memories WHERE trigger='agent' "
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

def change(con, session: str, item: dict, condensed: str, root=None) -> int | None:
    """update / retire a numbered memory. Same evidence and conflict checks as add; a user rule changes only on the
    user's own words. Retire deletes the row (staleness is recomputed from the tree, so it cannot hold a withdrawal);
    the old row is kept in memory_log. A stale memory (its file changed) may also be judged on that file's current
    text: evidence quoted from it counts; an update revives it, anchored to the file as it is now.
    -> the memory id changed, or None."""
    from .. import activity
    op = item.get("op")
    def no(why: str):
        item["_why"] = why                       # told back to the agent (store_items -> _not_kept)
        return None
    try:
        target = int(item.get("target") or 0)
    except (TypeError, ValueError):
        return no("the target is not a memory number")
    row = con.execute("SELECT * FROM memories WHERE id=?", (target,)).fetchone() if target > 0 else None
    if row is None:
        return no(f"there is no memory #{target}")
    if checks.verified(dict(item, kind="note"), condensed) is None:
        ev_n = checks._norm(item.get("evidence", ""))
        in_file = (row["stale"] and len(ev_n) >= 8 and len(" ".join(str(item.get("text", "")).split())) >= 8
                   and ev_n in checks._norm(file_text(root, row["anchor_path"])))
        if not in_file:
            return no(checks.why_not(dict(item, kind="note"), condensed, root)
                      + (" (for a stale memory, quoting its file's current text also counts)" if row["stale"] else ""))
    if op == "update" and checks.echoes_context(con, session, item, condensed):
        return no("the coding agent was only repeating a memory it was shown")
    is_rule = bool(row["from_user"])
    if is_rule and (not checks.user_evidence(item, condensed) or checks.verified(dict(item, kind="rule"), condensed) != "rule"):
        return no("a from_user memory changes only on the user's own words (a [user] line as evidence)")
    is_decision = row["topic"] == "decision"
    if is_decision and checks.verified(dict(item, kind="decision"), condensed) != "decision":
        return no("a decision changes only on the user's words or a [ran] result that settles it")
    text = " ".join(str(item.get("text", "")).split())[:300]
    ev = item.get("evidence", "")
    if op == "retire":
        _log(con, session, "retire", target, before=row, after=text, evidence=ev)
        store.delete_ids(con, [target])
        activity.note(con, "retired", f"retired #{target}: {text}")
        return target
    if op == "update":
        if text == row["text"]:
            if not row["stale"]:
                return no("the text is unchanged")
            _log(con, session, "revive", target, before=row, after="still holds as written", evidence=ev)
            con.execute("UPDATE memories SET updated_at=? WHERE id=?", (time.time(), target))
            _revive(con, root, row)                  # reviewed: it still holds as written
            activity.note(con, "updated", f"kept #{target} after its file changed: {text}")
            return target
        _log(con, session, "update", target, before=row, after=text, evidence=ev)
        now = time.time()
        con.execute("UPDATE memories SET text=?, updated_at=?, expires_at=?, unusual=? WHERE id=?",
                    (text, now, now + decision_days() * 86400 if is_decision else row["expires_at"],
                     int(item["unusual"]) if isinstance(item.get("unusual"), bool) else row["unusual"], target))
        if row["stale"]:
            _revive(con, root, row)
        activity.note(con, "updated", f"updated #{target}: {text}")
        return target
    return None

def _revive(con, root, row) -> None:
    """A stale memory the agent updated holds for the file as it is now: anchor it there and mark it fresh."""
    h, sh = row["anchor_hash"], row["symbol_hash"]
    p = os.path.join(str(root), row["anchor_path"]) if root and row["anchor_path"] else ""
    if p and os.path.isfile(p):
        if h is not None:
            with open(p, "rb") as fh:
                h = store.sha1(fh.read())
        if row["anchor_symbol"]:
            try:
                from .. import symbols
                with open(p, errors="replace") as fh:
                    sh = symbols.current_symbol_hash(fh.read(), row["anchor_symbol"])
            except (ValueError, OSError):
                pass
    elif row["anchor_path"]:
        h = sh = None                    # the file is gone: keep the memory, tied to nothing that can change under it
    con.execute("UPDATE memories SET stale=0, anchor_hash=?, symbol_hash=? WHERE id=?", (h, sh, row["id"]))


def flat(item: dict) -> dict:
    """The agent's flat output (from_user, topic) in the shape the checks read (kind, category). Items in the older
    shape (kind, category) pass through; an old 'env' item is an environment memory like any other."""
    if "from_user" not in item:
        return dict(item, kind="note", category=item.get("category") or "environment") if item.get("kind") == "env" else item
    topic = str(item.get("topic") or "")
    # a decision is dated context, never an instruction, even when the agent marks it from_user (seen in eval-agent:
    # "G16 is parked" marked from_user was checked as a rule and refused as a request for now)
    kind = "decision" if topic == "decision" else "rule" if item.get("from_user") is True else "note"
    return dict(item, kind=kind, category=topic)

def _link(con, mid: int, links) -> None:
    """The agent's links from memory mid to numbered live memories (graph.py)."""
    from .. import graph
    for n in (links if isinstance(links, list) else [])[:MAX_LINKS]:
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        if n != mid and con.execute("SELECT 1 FROM memories WHERE id=? AND stale=0", (n,)).fetchone():
            graph.link(con, mid, n, "related", 1.0, "agent")

MAX_RECALLS = 3              # memories the agent may flag per piece of log

def queue_recall(con, session: str, item: dict, condensed: str) -> int | None:
    """The agent flagged a numbered memory for what the session is doing now: queue it, with its reason, for the next
    prompt or tool call (retrieval.flagged). Its evidence must quote the transcript. -> the memory id, or None."""
    try:
        target = int(item.get("target") or 0)
    except (TypeError, ValueError):
        return None
    ev = checks._norm(item.get("evidence", ""))
    if target <= 0 or len(ev) < 8 or not any(ev in checks._norm(l) for l in condensed.splitlines()):
        return None
    if not con.execute("SELECT 1 FROM memories WHERE id=? AND stale=0", (target,)).fetchone():
        return None
    why = " ".join(str(item.get("text", "")).split())[:240]
    con.execute("INSERT OR REPLACE INTO pending_recalls(session, memory_id, why, ts) VALUES(?,?,?,?)",
                (session, target, why, time.time()))
    return target

KEEP_PROPOSALS_DAYS = 7


def _not_kept(con, session: str, item: dict, reason: str) -> None:
    """Note a proposal memcode did not keep, and why; the memory agent hears it in its next message."""
    db.ensure(con)
    try:
        target = int(item.get("target") or 0) or None
    except (TypeError, ValueError):
        target = None
    con.execute("INSERT INTO proposals(ts, session, op, target, text, reason, evidence) VALUES(?,?,?,?,?,?,?)",
                (time.time(), session, str(item.get("op") or "add"), target,
                 " ".join(str(item.get("text", "")).split())[:200], reason, str(item.get("evidence", ""))[:200]))
    con.execute("DELETE FROM proposals WHERE ts < ?", (time.time() - KEEP_PROPOSALS_DAYS * 86400,))


def store_items(con, root: str, session: str, items: list[dict], condensed: str, model: str = "",
                max_items: int = MAX_ITEMS) -> list[int]:
    """Apply the memory agent's operations: add (default), update, retire, and recall (queued for the coding agent's
    next step, not a change: not in the ids). -> ids added or changed."""
    from .. import activity
    ids = []
    added = 0

    def rating(item) -> int:
        try:
            return int(item.get("importance", MIN_IMPORTANCE))   # older callers without ratings: kept as before
        except (TypeError, ValueError):
            return MIN_IMPORTANCE
    # corrections first (update / retire keep the memory true whatever their rating), then the most important adds
    items = sorted([flat(i) for i in items], key=lambda it: (it.get("op") not in ("update", "retire"), -rating(it)))
    recalls = 0
    for item in items:
        if item.get("op") == "recall":
            if recalls >= MAX_RECALLS:
                _not_kept(con, session, item, f"at most {MAX_RECALLS} recalls per message")
            elif queue_recall(con, session, item, condensed) is not None:
                recalls += 1
            else:
                _not_kept(con, session, item, "no such memory, or the evidence is not an exact quote of the transcript")
            continue
        if item.get("op") in ("update", "retire"):
            mid = change(con, session, item, condensed, root)
            if mid is not None:
                ids.append(mid)
                if item.get("op") == "update":
                    _link(con, mid, item.get("links"))
            else:
                _not_kept(con, session, item, item.get("_why") or "it did not pass the checks")
            continue
        knowledge = item.get("kind") == "note" and item.get("category") in KNOWLEDGE
        unusual = item.get("unusual") is True
        floor = MIN_RULE_IMPORTANCE if item.get("kind") in ("rule", "decision") or knowledge or unusual else MIN_IMPORTANCE
        if item.get("category") in ("reference", "location"):   # a link, or where a doc or script lives: cheap to keep,
            floor = MIN_REFERENCE_IMPORTANCE                     # exact, and rated low (eval-agent: dashboard, runbook at 2)
        if rating(item) < floor:
            _not_kept(con, session, item, f"rated {rating(item)}; this kind is kept from {floor}")
            continue
        if added >= max_items:
            _not_kept(con, session, item, f"only the {max_items} most important of a piece are kept")
            continue
        kind = checks.verified(item, condensed, root)
        text = " ".join(str(item.get("text", "")).split())[:300]
        if kind is None:
            _not_kept(con, session, item, checks.why_not(item, condensed, root))
            continue
        if checks.is_repeat(con, text):
            _not_kept(con, session, item, "the memory already says it")
            continue
        if checks.echoes_context(con, session, item, condensed):
            _not_kept(con, session, item, "the coding agent was only repeating a memory it was shown")
            continue
        prov = {"session": session, "source": "agent", "model": model, "ts": time.time(),
                "evidence": str(item.get("evidence", ""))[:200],
                "category": str(item.get("category", ""))[:20], "importance": rating(item)}
        if kind == "decision":
            if not decisions_enabled(root):
                _not_kept(con, session, item, "decision capture is off in this repository")
                continue
            subject = " ".join(str(item.get("subject", "")).split())[:40].lower()
            prov["subject"] = subject
            if subject:                    # a newer decision on the same subject replaces the older one
                old = [r for r in con.execute("SELECT * FROM memories WHERE topic='decision'")
                       if (db.loads(r["provenance"]).get("subject") or "") == subject]
                for r in old:
                    _log(con, session, "retire", r["id"], before=r, after=f"replaced by a newer decision on {subject}",
                         evidence=item.get("evidence", ""))
                if old:
                    store.delete_ids(con, [r["id"] for r in old])
            mid = store.add_memory(con, "agent", text, "", None, prov, 0.6, commit=False, from_user=False,
                                   topic="decision", importance=rating(item),
                                   expires_at=time.time() + decision_days() * 86400)
            activity.saved(con, "agent", text, from_user=False, topic="decision")
        elif kind == "rule":
            cat = str(item.get("category", ""))[:20]
            mid = store.add_memory(con, "agent", text, "", None, prov, 0.6, commit=False, from_user=True,
                                   topic="" if cat in ("rule", "decision") else cat, importance=rating(item),
                                   unusual=unusual)
            activity.saved(con, "agent", text, from_user=True)
        else:
            a = _anchor(root, item.get("path", ""))
            h = None
            if a and os.path.isfile(os.path.join(root, a)) and checks.pins_content(text, a) and not knowledge:
                with open(os.path.join(root, a), "rb") as fh:
                    h = store.sha1(fh.read())
            cat = str(item.get("category", ""))[:20]
            mid = store.add_memory(con, "agent", text, a, h, prov, 0.5, commit=False, from_user=False,
                                   topic="" if cat in ("rule", "decision") else cat, importance=rating(item),
                                   unusual=unusual)
            activity.saved(con, "agent", text, a, from_user=False, topic="" if cat in ("rule", "decision") else cat)
        try:
            from .. import scope
            if kind != "decision":             # decisions are repo-wide context: no folder scope
                sp, sk = scope.assign(con, "agent", text, "" if kind == "rule" else a, None,
                                      from_user=kind == "rule")
                con.execute("UPDATE memories SET scope_path=?, scope_kind=? WHERE id=?", (sp, sk, mid))
        except Exception:  # noqa: BLE001  rescope_new retries at session start
            pass
        _link(con, mid, item.get("links"))
        store.bump(con, session, "captured", commit=False)
        _log(con, session, "add", mid, after=text, evidence=item.get("evidence", ""))
        ids.append(mid)
        added += 1
    con.commit()
    try:
        from .. import graph
        graph.update(con)                      # vectors and links of what changed (session start catches up otherwise)
    except Exception:  # noqa: BLE001
        pass
    return ids
