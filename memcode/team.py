"""Team memory (Phase 3): memories shared through a reviewed, committed file in the repo.

The local store (.memcode/) is git-ignored and per-developer. `memcode share ID` copies a memory into TEAM_FILE
(`.memcode-team.jsonl` at the repo root, one JSON object per line, sorted keys, so diffs are one line per memory).
Nothing is shared automatically: a memory reaches teammates only when that file change is committed and passes the
team's normal code review, the same trust path as CLAUDE.md. Sync is git itself.

At every session start `sync` imports the file into the local store (provenance {"source": "team", "team_id"}) and
removes local team copies whose line was deleted, so `git pull` is all a teammate needs. Imported memories behave like
local ones: staleness via the recorded anchor hashes, rules in the rules block, notes inside the untrusted wrapper.
MEMCODE_TEAM=0 disables the import.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time

from . import store
from .redact import redact

TEAM_FILE = ".memcode-team.jsonl"
MAX_RECORDS = 500
MAX_TEXT = 2000
TRIGGERS = {"correction", "revert", "fail_to_fix", "retry", "dep_change", "manual"}
TEAM_CONFIDENCE = 0.7


def path(root: str) -> str:
    return os.path.join(root, TEAM_FILE)


def enabled() -> bool:
    return os.environ.get("MEMCODE_TEAM", "1") != "0"


def team_id(trigger: str, text: str, anchor_path: str, anchor_symbol: str | None) -> str:
    raw = "\x1f".join([trigger, text, anchor_path or "", anchor_symbol or ""])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _prov(row) -> dict:
    try:
        p = json.loads(row["provenance"] or "{}")
        return p if isinstance(p, dict) else {}
    except ValueError:
        return {}


def _safe_anchor(root: str, p) -> str | None:
    """Repo-relative posix path, or None if it escapes the repo (a team file is repo content, not trusted input)."""
    from .mcp_server import safe_rel
    try:
        return safe_rel(root, p or "")
    except ValueError:
        return None


def read(root: str) -> list[dict]:
    """Valid records from TEAM_FILE, in file order. Malformed lines are skipped, never fatal."""
    out, seen = [], set()
    try:
        with open(path(root), encoding="utf-8") as fh:
            lines = fh.readlines()
    except (OSError, UnicodeDecodeError):
        return []
    for line in lines:
        if len(out) >= MAX_RECORDS:
            break
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not isinstance(r, dict) or r.get("trigger") not in TRIGGERS or not isinstance(r.get("text"), str):
            continue
        anchor = _safe_anchor(root, r.get("anchor_path", ""))
        if anchor is None or not r["text"].strip():
            continue
        sym = r.get("anchor_symbol") if isinstance(r.get("anchor_symbol"), str) else None
        text = redact(r["text"].strip())[:MAX_TEXT]
        rid = r.get("id") if isinstance(r.get("id"), str) and r.get("id") else team_id(r["trigger"], text, anchor, sym)
        if rid in seen:
            continue
        seen.add(rid)
        out.append({"id": rid, "trigger": r["trigger"], "text": text, "anchor_path": anchor, "anchor_symbol": sym,
                    "anchor_hash": r.get("anchor_hash") if isinstance(r.get("anchor_hash"), str) else None,
                    "symbol_hash": r.get("symbol_hash") if isinstance(r.get("symbol_hash"), str) else None,
                    "added": r.get("added") if isinstance(r.get("added"), str) else None})
    return out


def _write(root: str, records: list[dict]) -> None:
    keep = ("id", "trigger", "text", "anchor_path", "anchor_symbol", "anchor_hash", "symbol_hash", "added")
    tmp = path(root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps({k: r[k] for k in keep if r.get(k) not in (None, "") or k == "anchor_path"},
                                sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(tmp, path(root))


def _added_ts(added: str | None) -> float:
    try:
        return time.mktime(time.strptime(added, "%Y-%m-%d"))
    except (TypeError, ValueError):
        return time.time()


def sync(con, root: str) -> dict:
    """Import TEAM_FILE into the local store; drop local team copies whose line is gone. Returns counts."""
    records = read(root) if enabled() else []
    want = {r["id"]: r for r in records}
    have: dict[str, int] = {}                                   # team_id -> local memory id
    same: dict[str, object] = {}                                # computed id -> unlinked local memory
    for m in con.execute("SELECT * FROM memories"):
        tid = _prov(m).get("team_id")
        if tid:
            have[tid] = m["id"]
        else:
            same.setdefault(team_id(m["trigger"], m["text"], m["anchor_path"], m["anchor_symbol"]), m)
    added = removed = 0
    for tid, r in want.items():
        if tid in have:
            continue
        if tid in same:                                          # we already hold this exact memory: link, no copy
            m = same[tid]; p = _prov(m); p["team_id"] = tid
            con.execute("UPDATE memories SET provenance=? WHERE id=?", (json.dumps(p), m["id"]))
            have[tid] = m["id"]
            continue
        ts = _added_ts(r["added"])
        mid = store.add_memory(con, r["trigger"], r["text"], r["anchor_path"], r["anchor_hash"],
                               {"source": "team", "team_id": tid}, TEAM_CONFIDENCE, commit=False,
                               anchor_symbol=r["anchor_symbol"], symbol_hash=r["symbol_hash"])
        con.execute("UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (ts, ts, mid))
        added += 1
    for tid, mid in have.items():
        if tid in want:
            continue
        m = con.execute("SELECT provenance FROM memories WHERE id=?", (mid,)).fetchone()
        if _prov(m).get("source") == "team":                    # imported copy: the team removed it
            con.execute("DELETE FROM memories WHERE id=?", (mid,))
            removed += 1
        else:                                                    # our own memory, unshared: keep it, forget the link
            p = _prov(m); p.pop("team_id", None)
            con.execute("UPDATE memories SET provenance=? WHERE id=?", (json.dumps(p), mid))
    con.commit()
    if added:
        from . import activity
        activity.note(con, "saved", f"{added} team memor{'y' if added == 1 else 'ies'} imported", added)
    return {"records": len(records), "added": added, "removed": removed}


def share(con, root: str, memory_ids: list[int]) -> list[str]:
    """Append memories to TEAM_FILE (redacted, no session provenance). Returns their team ids."""
    records = read(root)
    by_id = {r["id"]: r for r in records}
    out = []
    for mid in memory_ids:
        m = con.execute("SELECT * FROM memories WHERE id=?", (mid,)).fetchone()
        if m is None:
            raise ValueError(f"no memory #{mid}")
        if m["stale"]:
            raise ValueError(f"memory #{mid} is stale; not sharing it")
        text = redact(m["text"])[:MAX_TEXT]
        tid = _prov(m).get("team_id") or team_id(m["trigger"], text, m["anchor_path"], m["anchor_symbol"])
        if tid not in by_id:
            if len(records) >= MAX_RECORDS:
                raise ValueError(f"{TEAM_FILE} already holds {MAX_RECORDS} memories")
            rec = {"id": tid, "trigger": m["trigger"], "text": text, "anchor_path": m["anchor_path"],
                   "anchor_symbol": m["anchor_symbol"], "anchor_hash": m["anchor_hash"],
                   "symbol_hash": m["symbol_hash"], "added": time.strftime("%Y-%m-%d")}
            records.append(rec)
            by_id[tid] = rec
        p = _prov(m); p["team_id"] = tid
        con.execute("UPDATE memories SET provenance=? WHERE id=?", (json.dumps(p), mid))
        out.append(tid)
    _write(root, records)
    con.commit()
    return out


def unshare(con, root: str, keys: list[str]) -> int:
    """Remove records by team id or local memory id. Returns how many lines were removed."""
    records = read(root)
    drop = set()
    for k in keys:
        if k.isdigit():
            m = con.execute("SELECT provenance FROM memories WHERE id=?", (int(k),)).fetchone()
            if m is not None and _prov(m).get("team_id"):
                drop.add(_prov(m)["team_id"])
        else:
            drop.add(k)
    kept = [r for r in records if r["id"] not in drop]
    if len(kept) != len(records):
        _write(root, kept)
    return len(records) - len(kept)


def status(con, root: str) -> dict:
    """What the `memcode team` dashboard shows."""
    records = read(root)
    rows = con.execute("SELECT * FROM memories").fetchall()
    team_rows = [m for m in rows if _prov(m).get("source") == "team"]
    shared_local = [m for m in rows if _prov(m).get("team_id") and _prov(m).get("source") != "team"]
    from . import salience
    now = time.time()
    suggest = []
    for m in rows:
        if _prov(m).get("team_id") or m["stale"] or m["trigger"] in ("retry",):
            continue
        ev = salience.evidence(con, m, now)
        if m["trigger"] == "correction" or ev["repeats"] >= 0.5 or ev["recurrences"] >= 0.5 or m["confidence"] >= 0.7:
            suggest.append((-(ev["repeats"] + ev["recurrences"]), -m["confidence"], m["id"], m))
    suggest.sort(key=lambda x: x[:3])
    uncommitted = None
    try:
        r = subprocess.run(["git", "-C", root, "status", "--porcelain", "--", TEAM_FILE],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            uncommitted = bool(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return {"records": len(records), "rules": sum(r["trigger"] == "correction" for r in records),
            "imported": len(team_rows), "stale_imported": sum(m["stale"] for m in team_rows),
            "shared_by_me": len(shared_local), "uncommitted": uncommitted,
            "suggest": [m for *_, m in suggest[:10]]}
