"""Shadow-mode salience. Logged for offline analysis; NEVER used for ranking in Phase 1."""
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


def compute(con, memory_row, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    trig = memory_row["trigger"]
    folder = _folder_of(con, memory_row["anchor_path"])
    weight = 0.0
    for r in con.execute("SELECT anchor_path, created_at FROM memories "
                         "WHERE trigger='revert'"):
        if _under(r["anchor_path"], folder):
            weight += decay(now - r["created_at"])
    return {
        "surprise": _clamp(_SURPRISE.get(trig, 0.1)),
        "friction": _clamp(_FRICTION.get(trig, 0.1)),
        "fragility": _squash(weight),
        "confidence": _clamp(memory_row["confidence"]),
    }


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


def rollup(con, now: float | None = None) -> dict[str, float]:
    """Fragility per path, rolled up to every ancestor (root is ''), age-decayed."""
    now = time.time() if now is None else now
    acc: dict[str, float] = {}
    for r in con.execute("SELECT anchor_path, created_at FROM memories "
                         "WHERE trigger='revert'"):
        w = decay(now - r["created_at"])
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
