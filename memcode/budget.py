"""Storage budget: keep the memories table at or under a cap (MEMCODE_STORE_BUDGET=N; 0 / unset = off).

Runs at session start (maintenance.run) after consolidation. The cap counts EVERY row of the memories table: stale
rows, consolidated (hidden) children and lessons included. Facts live in their own table and are not counted. Over the
cap, rows are evicted (DELETEd together with their retrievals, salience log, injections and outcomes) in this order,
stopping as soon as the count is back at the cap:
  1. stale       stale level-0 memories, oldest first (created_at, then id)
  2. merged      consolidated children (parent_id -> a consolidation lesson), oldest first. "Merge before evict": the
                 lesson absorbs each one (provenance absorbed / absorbed_ts), so evidence_count and salience keep
                 counting it, and the lesson never dissolves for lack of it
  3. low_evidence  top-level live retry / dep_change notes, lowest salience first (then oldest, then id)
  4. low_salience  any other top-level live agent-derived note (fail_to_fix, revert), lowest salience first: the cap
                 holds even when the store is all fresh, distinct notes
Never evicted, in any step: user rules (trigger 'correction' / 'manual') and lessons. If only protected rows are left, enforcement stops above the cap and reports over_cap=True.
"""
from __future__ import annotations

import json
import os
import time

from . import consolidate

LOW_EVIDENCE = ("retry", "dep_change")
REASONS = ("stale", "merged", "low_evidence", "low_salience")


def cap_from_env() -> int:
    try:
        return max(0, int(os.environ.get("MEMCODE_STORE_BUDGET", "0") or 0))
    except ValueError:
        return 0


def plan(con, cap: int, now: float | None = None) -> dict[str, list[int]]:
    """Ids to evict per reason, in eviction order (nothing is written)."""
    out: dict[str, list[int]] = {k: [] for k in REASONS}
    total = con.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    need = total - cap
    if cap <= 0 or need <= 0:
        return out
    rows = con.execute("SELECT id, trigger, text, anchor_path, anchor_symbol, provenance, confidence, stale, level, "
                       "parent_id, created_at, updated_at FROM memories").fetchall()
    lessons = {r["id"] for r in rows if consolidate.is_own_lesson(r)}
    free = [r for r in rows if r["level"] == 0 and not consolidate.protected(r)]
    age = lambda r: (r["created_at"], r["id"])
    steps = [("stale", sorted((r for r in free if r["stale"]), key=age)),
             ("merged", sorted((r for r in free if not r["stale"] and r["parent_id"] in lessons), key=age))]
    for reason, cands in steps:
        take = cands[:need]
        out[reason] = [r["id"] for r in take]
        need -= len(take)
        if need <= 0:
            return out
    top = [r for r in free if not r["stale"] and r["parent_id"] not in lessons]
    if not top:
        return out
    from . import salience
    idx = salience.Index(con, now)
    key = lambda r: (salience.score(con, r, index=idx), r["created_at"], r["id"])
    for reason, cands in (("low_evidence", [r for r in top if r["trigger"] in LOW_EVIDENCE]),
                          ("low_salience", [r for r in top if r["trigger"] not in LOW_EVIDENCE])):
        take = sorted(cands, key=key)[:need]
        out[reason] = [r["id"] for r in take]
        need -= len(take)
        if need <= 0:
            break
    return out


def enforce(con, cap: int, now: float | None = None, dry_run: bool = False) -> dict:
    """Evict down to `cap` rows (see the module docstring). Returns
    {"cap", "before", "after", "evicted": {reason: n}, "evicted_ids": {reason: [ids]}, "over_cap": bool}."""
    before = con.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    ids = plan(con, cap, now)
    n = sum(len(v) for v in ids.values())
    out = {"cap": cap, "before": before, "after": before - n, "evicted": {k: len(v) for k, v in ids.items()},
           "evicted_ids": ids, "over_cap": cap > 0 and before - n > cap}
    if dry_run or not n:
        return out
    try:
        _absorb(con, ids["merged"])
        consolidate.delete_ids(con, [i for k in REASONS for i in ids[k]])
        con.commit()
    except BaseException:
        con.rollback()
        raise
    return out


def _absorb(con, child_ids: list[int]) -> None:
    """Record evicted children on their lessons: the count (evidence_count unchanged) and their timestamps."""
    if not child_ids:
        return
    by_lesson: dict[int, list[float]] = {}
    for i in child_ids:
        r = con.execute("SELECT parent_id, created_at FROM memories WHERE id=?", (i,)).fetchone()
        if r is not None and r["parent_id"] is not None:
            by_lesson.setdefault(r["parent_id"], []).append(r["created_at"])
    for lid, ts in by_lesson.items():
        row = con.execute("SELECT id, provenance FROM memories WHERE id=?", (lid,)).fetchone()
        if row is None:
            continue
        p = consolidate.prov(row)
        p["absorbed"] = int(p.get("absorbed") or 0) + len(ts)
        p["absorbed_ts"] = sorted([float(t) for t in p.get("absorbed_ts") or []] + ts)[-consolidate.ABSORBED_TS_KEEP:]
        con.execute("UPDATE memories SET provenance=? WHERE id=?", (json.dumps(p, sort_keys=True), lid))


def enforce_if_enabled(con) -> dict | None:
    """maintenance.run's entry point: enforce MEMCODE_STORE_BUDGET when it is a positive integer."""
    cap = cap_from_env()
    return enforce(con, cap, time.time()) if cap > 0 else None
