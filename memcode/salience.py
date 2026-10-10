"""Salience: how costly a memory was to learn, from observable evidence (Phase 2).

Logged every session (shadow mode). Used for ranking ONLY when MEMCODE_RANK=salience (retrieval: relevance x
(1 + score); pinned notes: ordered by score). User rules keep their oldest-to-newest order regardless.
"""
from __future__ import annotations

import math
import time

HALF_LIFE_S = 14 * 86400.0

_SURPRISE = {"fail_to_fix": 0.85, "retry": 0.45, "revert": 0.35, "dep_change": 0.3}
_FRICTION = {"correction": 0.85, "retry": 0.4, "revert": 0.3, "fail_to_fix": 0.3}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def decay(age_s: float) -> float:
    return 0.5 ** (max(0.0, age_s) / HALF_LIFE_S)


def _squash(x: float) -> float:
    return _clamp(1.0 - math.exp(-x))


def _under(anchor: str, folder: str) -> bool:
    return folder == "" or anchor == folder or anchor.startswith(folder + "/")


def _folder_of(con, anchor: str) -> str:
    if anchor == "":
        return ""
    r = con.execute("SELECT kind FROM paths WHERE path=?", (anchor,)).fetchone()
    if r is not None and r["kind"] == "dir":
        return anchor
    return anchor.rsplit("/", 1)[0] if "/" in anchor else ""


def _decayed(now: float, ts: float) -> float:
    return decay(now - (ts or now))


def evidence(con, memory_row, now: float | None = None) -> dict:
    """Observable evidence behind a memory, each event age-decayed (half-life HALF_LIFE_S):
    recurrences   other fail_to_fix memories on the same anchor (and symbol, when both have one)
    repeats       times the user had to restate this rule (outcomes 'failure:repeated')
    reverts/fails reverts and fail_to_fix memories under the anchor's folder (none for repo-wide memories)
    verified      verified successes / failures recorded for this memory (outcomes.py)"""
    now = time.time() if now is None else now
    mid, anchor, sym = memory_row["id"], memory_row["anchor_path"], memory_row["anchor_symbol"]
    ev = {"recurrences": 0.0, "repeats": 0.0, "reverts": 0.0, "fails": 0.0, "verified_ok": 0, "verified_bad": 0}
    if anchor:
        folder = _folder_of(con, anchor)
        for r in con.execute("SELECT id, trigger, anchor_path, anchor_symbol, created_at FROM memories "
                             "WHERE trigger IN ('revert','fail_to_fix') AND id != ?", (mid,)):
            w = _decayed(now, r["created_at"])
            if r["trigger"] == "fail_to_fix" and r["anchor_path"] == anchor and (not sym or not r["anchor_symbol"]
                                                                               or r["anchor_symbol"] == sym):
                ev["recurrences"] += w
            if _under(r["anchor_path"], folder):
                ev["reverts" if r["trigger"] == "revert" else "fails"] += w
    for o in con.execute("SELECT outcome, ts FROM outcomes WHERE memory_id=?", (mid,)):
        if o["outcome"] == "failure:repeated":
            ev["repeats"] += _decayed(now, o["ts"])
        if o["outcome"].startswith("success"):
            ev["verified_ok"] += 1
        elif o["outcome"].startswith("failure"):
            ev["verified_bad"] += 1
    return ev


CAP = 0.9            # intensity cap per dimension and for the score: no memory saturates the ranking
WEIGHTS = {"surprise": 0.3, "friction": 0.3, "fragility": 0.25, "confidence": 0.15}


def compute(con, memory_row, now: float | None = None) -> dict:
    """Four dimensions in [0, CAP], all from observable evidence and age-decayed (confidence excepted)."""
    now = time.time() if now is None else now
    trig = memory_row["trigger"]
    own = _decayed(now, memory_row["created_at"])
    ev = evidence(con, memory_row, now)
    cap = lambda x: min(CAP, _clamp(x))
    return {
        "surprise": cap(max(_SURPRISE.get(trig, 0.1) * own, _squash(ev["recurrences"]))),
        "friction": cap(max(_FRICTION.get(trig, 0.1) * own, _squash(ev["repeats"]))),
        "fragility": cap(_squash(ev["reverts"] + 0.5 * ev["fails"])),
        "confidence": cap(memory_row["confidence"]),
    }


def score(con, memory_row, now: float | None = None) -> float:
    """One salience value in [0, CAP]. Retrieval counts are deliberately NOT an input (rich-get-richer guard)."""
    dims = compute(con, memory_row, now)
    return min(CAP, sum(WEIGHTS[k] * v for k, v in dims.items()))


def explain(con, memory_row, now: float | None = None) -> str:
    """Human-readable reasons, e.g. 'fail-to-fix recurred 2x on billing/x.py; 1 revert under billing/'."""
    ev = evidence(con, memory_row, now)
    parts = [f"recorded from a {memory_row['trigger'].replace('_', '-')}"]
    if ev["recurrences"] >= 0.5:
        parts.append(f"same failure recurred ~{ev['recurrences']:.0f}x on {memory_row['anchor_path']}")
    if ev["repeats"] >= 0.5:
        parts.append(f"user restated it ~{ev['repeats']:.0f}x")
    if ev["reverts"] >= 0.5 or ev["fails"] >= 0.5:
        folder = _folder_of(con, memory_row["anchor_path"]) or "/"
        parts.append(f"{ev['reverts']:.0f} reverts and {ev['fails']:.0f} failures under {folder} (decayed)")
    if ev["verified_ok"] or ev["verified_bad"]:
        parts.append(f"verified outcomes: {ev['verified_ok']} ok, {ev['verified_bad']} bad")
    return "; ".join(parts)


def log_all(con, now: float | None = None) -> int:
    now = time.time() if now is None else now
    rows = con.execute("SELECT * FROM memories ORDER BY id").fetchall()
    for m in rows:
        s = compute(con, m, now)
        con.execute("INSERT INTO salience_log(memory_id,surprise,friction,fragility,"
                    "confidence,logged_at) VALUES(?,?,?,?,?,?)",
                    (m["id"], s["surprise"], s["friction"], s["fragility"],
                     s["confidence"], now))
    con.commit()
    return len(rows)


def rollup(con, now: float | None = None, fail_weight: float = 0.0) -> dict[str, float]:
    """Fragility per path, rolled up to every ancestor (root is ''), age-decayed. Reverts count 1;
    fail_to_fix memories count fail_weight (the map zoom uses 0.5, matching compute()'s fragility)."""
    now = time.time() if now is None else now
    acc: dict[str, float] = {}
    for r in con.execute("SELECT trigger, anchor_path, created_at FROM memories "
                         "WHERE stale=0 AND trigger IN ('revert','fail_to_fix')"):
        w = decay(now - r["created_at"]) * (1.0 if r["trigger"] == "revert" else fail_weight)
        if w <= 0:
            continue
        p = r["anchor_path"]
        while True:
            acc[p] = acc.get(p, 0.0) + w
            if p == "":
                break
            p = p.rsplit("/", 1)[0] if "/" in p else ""
    return {p: _squash(v) for p, v in sorted(acc.items())}


def reinforce(con, memory_id: int) -> float:
    """Raise confidence (cap 0.95). Call ONLY after a verified success."""
    r = con.execute("SELECT confidence FROM memories WHERE id=?", (memory_id,)).fetchone()
    if r is None:
        raise KeyError(memory_id)
    c = r["confidence"]
    new = max(c, min(0.95, c + 0.1 * (1.0 - c) + 0.02))
    con.execute("UPDATE memories SET confidence=?, updated_at=? WHERE id=?",
                (new, time.time(), memory_id))
    con.commit()
    return new
