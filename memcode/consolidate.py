"""Abstraction hierarchy: redundant agent-derived notes are grouped under one lesson (level 1).

Runs at session start (maintenance.run) only when MEMCODE_CONSOLIDATE=1, which is also what makes injection show the
lesson instead of its children (store.injectable_sql hides rows with a parent_id). Deterministic, idempotent and
incremental: every run recomputes the grouping from the live store in O(n) and writes only what changed.

Candidates: level-0, non-stale memories that are NOT user rules (trigger 'correction' / 'manual') and not lessons.
Grouping key:
  (trigger, anchor_path, anchor_symbol, signature(text))
signature(): lowercased, whitespace collapsed, and
  `backticked commands`  -> triggers._cmd_key (flags and their values dropped: the retry trigger's own "same
                            command" rule), numbers -> <n>; paths inside a command are kept (they name the command)
  "double-quoted spans"  -> kept verbatim: they are the code a revert note is about, so reverts with different
                            snippets never merge
  other paths            -> <path> (a run "a.py, b.py and c.py" -> one <path>); other numbers -> <n>
  a run of identical commands (`x`; `x`) -> one
A group of >= MIN_GROUP live members gets ONE lesson row:
  trigger 'lesson', level 1, parent_id NULL, evidence_count N = live members + absorbed (see budget.py),
  text "{N} similar {trigger} notes on {anchor or 'the repo'}: {text of the most recent member}" (retry: the
  newest member's text with the distinct flag variants of all members, newest first, at most MAX_VARIANTS),
  anchor_path / anchor_symbol = the group's, anchor_hash / symbol_hash = the newest member's (so the lesson goes
  stale exactly when its live members do), scope = the members' common scope, labels = union of the members',
  confidence = max, created_at = oldest member, updated_at = newest member,
  provenance {"source": "consolidate", "trigger", "sig", "rep", "absorbed", "absorbed_ts"};
and every member gets parent_id = lesson id. Lessons are rendered like any other note ("- (lesson) ...") inside the
untrusted wrapper, because their text is agent-derived.
Dissolve rule: a lesson whose live members + absorbed (evicted children) drop below MIN_KEEP is deleted and its
remaining children are unlinked. Stale, forgotten or no-longer-matching children are unlinked every run (a child
that comes back to life relinks). Model-based summarization of lessons is a follow-up, not done here.
"""
from __future__ import annotations

import json
import os
import re

MIN_GROUP = 3          # live members needed to create a lesson
MIN_KEEP = 2           # live members + absorbed below which a lesson dissolves
MAX_VARIANTS = 8       # retry lessons: distinct command variants listed
ABSORBED_TS_KEEP = 100 # newest absorbed-child timestamps kept on the lesson (salience evidence)
LESSON = "lesson"
PROTECTED_TRIGGERS = ("correction", "manual", "decision")
SOURCE = "consolidate"

_CODE = re.compile(r"`[^`]*`|\"[^\"]*\"")
_PATH = re.compile(r"(?<![\w<>])(?:[\w.-]+/)+[\w.-]*|(?<![\w/<>.-])[\w-]+(?:\.[\w-]+)*\.[a-z][a-z0-9]{0,7}(?![\w/])")
_NUM = re.compile(r"\d+")
_PATH_RUN = re.compile(r"<path>(?:\s*(?:,|and|&|;)\s*<path>)+")
_CODE_RUN = re.compile(r"(`[^`]*`)(?:\s*[;,]\s*\1)+")
_RETRY = re.compile(r"^Command `([^`]*)` needed multiple attempts with different flags/fixes: (.*)$", re.S)
_TICKS = re.compile(r"`([^`]*)`")


def prov(row) -> dict:
    try:
        p = json.loads(row["provenance"] or "{}")
        return p if isinstance(p, dict) else {}
    except (ValueError, TypeError):
        return {}


def is_lesson(row) -> bool:
    return row["trigger"] == LESSON


def is_own_lesson(row) -> bool:
    return is_lesson(row) and prov(row).get("source") == SOURCE


def protected(row) -> bool:
    """User rules and lessons: never grouped under a lesson, never evicted."""
    return row["trigger"] in PROTECTED_TRIGGERS or is_lesson(row)


def _norm_cmd(cmd: str) -> str:
    from .triggers import _cmd_key
    key = " ".join((_cmd_key(cmd) or cmd).split()).lower()
    return _NUM.sub("<n>", key)


def _path_sub(m) -> str:
    return "<path>." if m.group(0).endswith(".") else "<path>"


def _norm_prose(s: str) -> str:
    s = _PATH.sub(_path_sub, s.lower())
    s = _NUM.sub("<n>", s)
    return _PATH_RUN.sub("<path>", s)


def signature(text: str) -> str:
    """Normalized text used for grouping (see the module docstring)."""
    text = text or ""
    parts, pos = [], 0
    for m in _CODE.finditer(text):
        parts.append(_norm_prose(text[pos:m.start()]))
        span = m.group(0)
        parts.append("`" + _norm_cmd(span[1:-1]) + "`" if span[0] == "`" else '"' + " ".join(span[1:-1].split()) + '"')
        pos = m.end()
    parts.append(_norm_prose(text[pos:]))
    return _CODE_RUN.sub(r"\1", " ".join("".join(parts).split()))


def group_key(row) -> tuple:
    return (row["trigger"], row["anchor_path"] or "", row["anchor_symbol"] or "", signature(row["text"]))


def _lesson_key(row) -> tuple:
    p = prov(row)
    return (p.get("trigger"), row["anchor_path"] or "", row["anchor_symbol"] or "", p.get("sig"))


def _newest(rows):
    return max(rows, key=lambda r: (r["updated_at"], r["created_at"], r["id"]))


def representative(trigger: str, members) -> str:
    """The lesson's body: the newest member's text; retry notes list every member's distinct variants."""
    rows = sorted(members, key=lambda r: (r["updated_at"], r["created_at"], r["id"]), reverse=True)
    rep = rows[0]["text"]
    if trigger != "retry":
        return rep
    m = _RETRY.match(rep)
    if not m:
        return rep
    seen: list[str] = []
    for r in rows:
        mm = _RETRY.match(r["text"])
        for v in _TICKS.findall(mm.group(2)) if mm else []:
            if v not in seen:
                seen.append(v)
    return (f"Command `{m.group(1)}` needed multiple attempts with different flags/fixes: "
            + "; ".join(f"`{v}`" for v in seen[:MAX_VARIANTS]) + (" ..." if len(seen) > MAX_VARIANTS else ""))


def lesson_text(trigger: str, anchor: str, n: int, rep: str) -> str:
    return f"{n} similar {trigger} notes on {anchor or 'the repo'}: {rep}"


def _common_scope(members) -> tuple[str, str]:
    scopes = {(r["scope_path"] or "", r["scope_kind"] or "repo") for r in members}
    if len(scopes) == 1:
        return scopes.pop()
    from .store import scope_chain
    chains = [scope_chain(sp) for sp, _ in scopes]
    common = next(p for p in chains[0] if all(p in c for c in chains[1:]))
    return common, ("dir" if common else "repo")


def delete_ids(con, ids) -> int:
    """Delete memories and the rows that reference them (retrievals, salience log, injections, outcomes)."""
    ids = [(i,) for i in ids]
    if not ids:
        return 0
    for t in ("retrievals", "salience_log", "injections", "outcomes"):
        con.executemany(f"DELETE FROM {t} WHERE memory_id=?", ids)
    return sum(con.execute("DELETE FROM memories WHERE id=?", i).rowcount for i in ids)


_COLS = ("id, trigger, text, anchor_path, anchor_hash, anchor_symbol, symbol_hash, provenance, confidence, stale, "
         "created_at, updated_at, parent_id, level, labels, scope_path, scope_kind, evidence_count")


def run(con, now: float | None = None, dry_run: bool = False) -> dict:
    """Group, create / update / dissolve lessons, (re)link children. `now` is accepted for API symmetry (the result
    depends only on the store). Returns counts; dry_run computes them without writing."""
    from . import labels as labelmod
    rows = con.execute(f"SELECT {_COLS} FROM memories").fetchall()
    by_id = {r["id"]: r for r in rows}
    groups: dict[tuple, list] = {}
    lessons: dict[tuple, list] = {}
    foreign_lessons: set[int] = set()
    for r in rows:
        if is_lesson(r):
            if prov(r).get("source") == SOURCE:
                lessons.setdefault(_lesson_key(r), []).append(r)
            else:
                foreign_lessons.add(r["id"])
        elif r["level"] == 0 and not r["stale"] and not protected(r):
            groups.setdefault(group_key(r), []).append(r)
    out = {"candidates": sum(len(v) for v in groups.values()), "created": 0, "updated": 0, "dissolved": 0,
           "linked": 0, "unlinked": 0, "lessons": 0, "children": 0}
    want_parent: dict[int, int] = {}         # child id -> lesson id (or a placeholder for lessons to be created)
    deletes: list[int] = []
    updates: list[tuple] = []
    creates: list[tuple] = []                # (key, members, fields)

    def fields(key, members, absorbed, absorbed_ts, old):
        trig, anchor, sym, sig = key
        n = len(members) + absorbed
        if members:
            newest = _newest(members)
            rep = representative(trig, members)
            sp, sk = _common_scope(members)
            labs = set()
            for m in members:
                labs.update(labelmod.of(m))
            f = {"text": lesson_text(trig, anchor, n, rep),
                 "anchor_hash": newest["anchor_hash"], "symbol_hash": newest["symbol_hash"] if sym else None,
                 "confidence": max(m["confidence"] for m in members),
                 "created_at": min([m["created_at"] for m in members] + list(absorbed_ts)),
                 "updated_at": newest["updated_at"], "stale": 0, "scope_path": sp, "scope_kind": sk,
                 "labels": labelmod.fmt(labs)}
        else:                                 # only absorbed children left: keep the lesson as it is, recount
            rep = prov(old).get("rep") or old["text"]
            f = {"text": lesson_text(trig, anchor, n, rep)}
        p = dict(prov(old)) if old is not None else {}
        p.update({"source": SOURCE, "trigger": trig, "sig": sig, "rep": rep, "absorbed": absorbed,
                  "absorbed_ts": list(absorbed_ts)[-ABSORBED_TS_KEEP:]})
        f["provenance"] = json.dumps(p, sort_keys=True)
        f["evidence_count"] = n
        return f

    for key in sorted(set(groups) | set(lessons), key=lambda k: (k[0] or "", k[1], k[2], k[3] or "")):
        members = groups.get(key, [])
        have = sorted(lessons.get(key, []), key=lambda r: r["id"])
        lesson, extra = (have[0], have[1:]) if have else (None, [])
        absorbed, absorbed_ts = 0, []
        for les in have:                      # duplicates (e.g. after a rename joined two groups) fold into one
            p = prov(les)
            absorbed += int(p.get("absorbed") or 0)
            absorbed_ts += [float(t) for t in p.get("absorbed_ts") or [] if isinstance(t, (int, float))]
        absorbed_ts.sort()
        deletes += [x["id"] for x in extra]
        if lesson is None:
            if len(members) >= MIN_GROUP:
                creates.append((key, members, fields(key, members, 0, [], None)))
            continue
        if len(members) + absorbed < MIN_KEEP:
            deletes.append(lesson["id"])
            out["dissolved"] += 1
            continue
        f = fields(key, members, absorbed, absorbed_ts, lesson)
        changed = {k: v for k, v in f.items() if lesson[k] != v}
        if changed:
            updates.append((lesson["id"], changed))
        for m in members:
            want_parent[m["id"]] = lesson["id"]

    out["created"] = len(creates)
    out["updated"] = len(updates)
    own_ids = {r["id"] for v in lessons.values() for r in v}
    gone = set(deletes)
    creating = {m["id"] for _, ms, _ in creates for m in ms}
    relink: list[tuple] = []                  # (parent or None, id)
    for r in rows:
        if is_lesson(r) or r["id"] in creating:
            continue
        cur, want = r["parent_id"], want_parent.get(r["id"])
        if cur == want:
            continue
        if want is None and cur is not None and cur in foreign_lessons:
            continue                          # someone else's grouping: leave it alone
        if want is None and cur is not None and cur not in own_ids and cur in by_id and cur not in gone:
            continue                          # parent is a non-lesson row: not ours to manage
        relink.append((want, r["id"]))
    out["linked"] = sum(1 for w, _ in relink if w is not None) + sum(len(m) for _, m, _ in creates)
    out["unlinked"] = sum(1 for w, _ in relink if w is None)
    out["lessons"] = len(lessons) - len(gone & own_ids) + len(creates)
    out["children"] = len(want_parent) + sum(len(m) for _, m, _ in creates)
    if dry_run:
        return out
    try:
        for want, i in relink:                # unlink / move first, so deleted lessons leave no dangling children
            con.execute("UPDATE memories SET parent_id=? WHERE id=?", (want, i))
        if deletes:
            con.executemany("UPDATE memories SET parent_id=NULL WHERE parent_id=?", [(i,) for i in deletes])
            delete_ids(con, deletes)
        for lid, changed in updates:
            cols = sorted(changed)
            con.execute(f"UPDATE memories SET {', '.join(c + '=?' for c in cols)} WHERE id=?",
                        [changed[c] for c in cols] + [lid])
        for (trig, anchor, sym, _), members, f in creates:
            cur = con.execute(
                """INSERT INTO memories(trigger, text, anchor_path, anchor_hash, anchor_symbol, symbol_hash, provenance,
                     confidence, stale, created_at, updated_at, level, labels, scope_path, scope_kind, evidence_count)
                   VALUES(?,?,?,?,?,?,?,?,0,?,?,1,?,?,?,?)""",
                (LESSON, f["text"], anchor, f["anchor_hash"], sym or None, f["symbol_hash"], f["provenance"],
                 f["confidence"], f["created_at"], f["updated_at"], f["labels"], f["scope_path"], f["scope_kind"],
                 f["evidence_count"]))
            con.executemany("UPDATE memories SET parent_id=? WHERE id=?", [(cur.lastrowid, m["id"]) for m in members])
        con.commit()
    except BaseException:
        con.rollback()
        raise
    return out


def enabled() -> bool:
    return os.environ.get("MEMCODE_CONSOLIDATE") == "1"


def run_if_enabled(con) -> dict | None:
    """maintenance.run's entry point: consolidate only when MEMCODE_CONSOLIDATE=1 (off: the store is untouched)."""
    return run(con) if enabled() else None


def undo(con) -> int:
    """Dissolve every consolidation lesson and unlink its children (`memcode consolidate --undo`). Children that the
    storage budget already evicted are gone; their lesson was the only record of them. Returns lessons removed."""
    ids = [r["id"] for r in con.execute("SELECT id, trigger, provenance FROM memories WHERE trigger=?", (LESSON,))
           if prov(r).get("source") == SOURCE]
    if ids:
        con.executemany("UPDATE memories SET parent_id=NULL WHERE parent_id=?", [(i,) for i in ids])
        delete_ids(con, ids)
        con.commit()
    return len(ids)
