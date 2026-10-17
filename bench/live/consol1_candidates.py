"""consol1 candidates: does consolidation (MEMCODE_CONSOLIDATE=1) put a crowded-out memory back in front of the agent,
and where can it hurt?

Every scenario has one hot file with many near-duplicate derived notes (fail_to_fix, reverts) written by memcode's
triggers in the exact template texts, all newer than the memory the task needs; 40 newer distractor rules in synthetic
directories keep the needed rule out of the session-start rules block (newest MAX_RULES=20), and 30 distractor notes.
Arms: flat (MEMCODE_RETRIEVAL=1, default split ranking = run.py memcode_split) vs consol (flat + MEMCODE_CONSOLIDATE=1).

shape "gain_rule":  the needed memory is a user rule about the directory. The prompt names the hot file, so every
                    near-duplicate anchored there scores PATH_W (3) while the rule scores SCOPE_W (2): under flat
                    ranking they fill TOP_K and split's promotions; consolidated into a few lessons they leave room.
shape "gain_note":  the needed memory is an agent-saved note (trigger 'manual', never consolidated) on the hot file;
                    it ties with the near-duplicates on relevance and loses on recency under flat ranking.
shape "control_child_detail": the needed fact is the quoted snippet inside ONE revert note on the hot file, among
                    other reverts that differ only inside their quotes. Flat retrieval ranks it first (it shares the
                    prompt's words). The planned signature normalizes quoted spans, so the revert joins a lesson whose
                    text is the most recent representative: consolidation can DROP the fact (predicted harm).
shape "control_lookalike": the needed fact is a revert on feeds/atom.py; a look-alike revert with a different value
                    sits on the sibling feeds/rss.py. Each is the only revert on its file, so neither may be merged
                    (different anchors, group size 1). Consolidation must not hurt (predicted: no change).

Conventions are arbitrary and not visible in the starter files; traps judge only the exact file the task creates
or edits. `offline_check` predicts, per arm, whether the needed fact reaches the agent (by id and by key text) and
the tokens injected. `simulate_consolidation` is a design sanity check of the PLANNED grouping (not a prediction):
it lets the scenarios be checked before the real consolidate.py exists.
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from bench.consolidation_eval import NA, Feature, _maintenance_wired, arm_env   # noqa: E402
from bench.live.pressure import scaled_distractors                             # noqa: E402

DAY = 86400.0
N_RULES, N_NOTES = 40, 30

FILES = {
    "README.md": "Demo shop service.\n",
    "app.py": "def main():\n    return 0\n",
    "pricing/__init__.py": "",
    "pricing/rules.py": "def round_cents(value):\n    return int(round(value))\n\n\nTIERS = {'basic': 0, 'pro': 10}\n",
    "alerts/__init__.py": "",
    "alerts/rules.py": "THRESHOLDS = {'cpu': 90, 'disk': 95, 'mem': 85}\n",
    "catalog/__init__.py": "",
    "catalog/items.py": "ITEMS = {}\n\n\ndef get(sku):\n    return ITEMS.get(sku)\n",
    "sessions/__init__.py": "",
    "sessions/store.py": "def save(backend, session_id, data):\n    backend[session_id] = data\n",
    "feeds/__init__.py": "",
    "feeds/atom.py": "def entries(items):\n    return [{'title': i} for i in items]\n",
    "feeds/rss.py": "def items(entries):\n    return [{'title': e} for e in entries]\n",
    "util/__init__.py": "", "util/text.py": "def slug(s):\n    return s.lower().replace(' ', '-')\n",
}

TOPICS = ["totals", "rounding", "tiers", "limits", "empty", "negative", "unicode", "order", "paging", "defaults",
          "zero", "large", "missing", "types", "repeat", "format", "parse", "sort", "merge", "edge"]
# snippet pairs for near-duplicate reverts: never contain a word of any scenario prompt or key
NOISE_EDITS = [("TIMEOUT = {a}", "TIMEOUT = {b}"), ("retries={a}", "retries={b}"), ("if not data:", "if data is None:"),
               ("return None", "raise LookupError(k)"), ("LIMIT = {a}", "LIMIT = {b}"), ("x.strip()", "x.rstrip()"),
               ("sorted(rows)", "sorted(rows, reverse=True)"), ("level={a}", "level={b}")]


def _revert(path: str, old: str, new: str) -> str:
    return (f"Agent edit to {path} was undone by a later edit (changed \"{old}\" -> \"{new}\" and back). "
            f"That change was wrong or unwanted.")


FLAGS = ["-q", "--lf", "-vv", "-q --lf", "-k {t}", "-q -k {t}", "--maxfail=1", "-q --maxfail=1", "-rA", "-q -rA",
         "--ff", "-q --ff", "-k {t} --lf", "-vv -k {t}", "--tb=short", "-q --tb=short", "--durations=5", "-q -s"]


def redundant(path: str, test_cmds: tuple, n_fail: int, n_rev: int, n_checkout: int, seed: int,
              ages: tuple = (0.5, 20.0), others: tuple = ()) -> list:
    """Near-duplicate derived notes on one file, in memcode/triggers.py's templates, newest of the history.
    fail_to_fix: the same test command(s) with different flags and edited-file lists (all distinct texts, as the
    trigger stores no exact duplicate; same command key, so the planned consolidation groups them per command);
    revert: distinct snippets (never merged: quoted spans stay in the signature) and plain checkouts."""
    rnd = random.Random(seed)
    out, seen = [], set()
    k = 0
    while len(out) < n_fail and k < 50 * n_fail:
        cmd = test_cmds[k % len(test_cmds)]
        flag = FLAGS[(k // len(test_cmds)) % len(FLAGS)].format(t=TOPICS[k % len(TOPICS)])
        extra = rnd.sample(list(others), min(len(others), rnd.randint(0, 2))) if others else []
        files = ", ".join(extra + [path])
        text = f"`{cmd} {flag}` failed and passed after editing {files}. Fix was in {path}."
        k += 1
        if text in seen:
            continue
        seen.add(text)
        out.append({"trigger": "fail_to_fix", "anchor": path, "role": "redundant", "text": text})
    for j in range(n_rev):
        o, n = NOISE_EDITS[j % len(NOISE_EDITS)]
        a, b = rnd.randint(1, 50), rnd.randint(51, 99)
        out.append({"trigger": "revert", "anchor": path, "role": "redundant",
                    "text": _revert(path, o.format(a=a, b=b), n.format(a=a, b=b))})
    via = [f"git checkout -- {path}", f"git restore {path}", f"git checkout HEAD -- {path}"]
    for j in range(n_checkout):
        out.append({"trigger": "revert", "anchor": path, "role": "redundant",
                    "text": f"Agent edits to {path} were reverted via `{via[j % len(via)]}`."})
    lo, hi = ages
    for i, m in enumerate(out):                      # spread ages, interleaving the families
        m["age"] = round(lo + (hi - lo) * ((i * 7919) % len(out)) / max(1, len(out) - 1), 3)
    return out


def _retry(key: str, variants: list) -> str:
    return f"Command `{key}` needed multiple attempts with different flags/fixes: " + "; ".join(f"`{v}`" for v in variants)


QA = "#!/bin/sh\n# runs the test suite\nexec python3 -m pytest -q\n"


CANDIDATES = [
    {"name": "g_pricing_header", "shape": "gain_rule", "dir": "pricing", "hot": "pricing/rules.py",
     "needed": {"trigger": "correction", "anchor": "", "age": 30,
                "text": "Every new module under pricing/ starts with the exact line '# owner: pricing-core'."},
     "noise": (("pytest tests/test_pricing.py", "./qa pricing"), 30, 3, 2),
     "later": "Create pricing/discounts.py with a function apply_discount(price_cents, percent) that reuses round_cents "
              "from pricing/rules.py.",
     "trap_regex": r"\A(?!# owner: pricing-core)", "trap_on": "content", "trap_path": r"(^|/)pricing/discounts\.py$",
     "key": r"# owner: pricing-core",
     "oracle": "Rule: every new module under pricing/ starts with the exact line '# owner: pricing-core'."},
    {"name": "g_alerts_runid", "shape": "gain_rule", "dir": "alerts", "hot": "alerts/rules.py",
     "needed": {"trigger": "correction", "anchor": "", "age": 30,
                "text": "Every function in alerts/ takes a parameter named run_id."},
     "noise": (("pytest tests/test_alerts.py", "./qa alerts"), 30, 3, 2),
     "later": "Add a function to alerts/rules.py that returns the names of the metrics whose value is above their "
              "threshold in THRESHOLDS.",
     "trap_regex": r"def \w+\((?![^)]*\brun_id\b)", "trap_on": "content", "trap_path": r"(^|/)alerts/rules\.py$",
     "key": r"run_id",
     "oracle": "Rule: every function in alerts/ takes a parameter named run_id."},
    {"name": "g_catalog_rev", "shape": "gain_note", "dir": "catalog", "hot": "catalog/items.py",
     "needed": {"trigger": "manual", "anchor": "catalog/items.py", "age": 30,
                "text": "catalog/: every new module under catalog/ must define CATALOG_REV = 7 at module level; the "
                        "nightly importer skips modules without it."},
     "noise": (("pytest tests/test_catalog.py", "./qa catalog"), 30, 3, 2),
     "later": "Create catalog/search.py with a function find(prefix) that returns the SKUs from ITEMS in catalog/items.py "
              "that start with prefix.",
     "trap_regex": r"\A(?!.*CATALOG_REV\s*=\s*7\b)", "trap_on": "content", "trap_path": r"(^|/)catalog/search\.py$",
     "key": r"CATALOG_REV",
     "oracle": "Note from an earlier session: every new module under catalog/ must define CATALOG_REV = 7 at module "
               "level; the nightly importer skips modules without it."},
    {"name": "c_child_detail", "shape": "control_child_detail", "dir": "sessions", "hot": "sessions/store.py",
     "needed": {"trigger": "revert", "anchor": "sessions/store.py", "age": 12,
                "text": _revert("sessions/store.py", "KEY_PREFIX = 'sx2:'", "KEY_PREFIX = 'session:'")},
     "noise": (("pytest tests/test_sessions.py",), 20, 6, 2),
     "noise_ages": (0.5, 10.0),                       # the other reverts are newer: the lesson's representative
     "later": "Create sessions/cache.py with a function cache_key(session_id) that returns the cache key for a session; "
              "sessions/store.py will use it.",
     "trap_regex": r"\A(?!.*sx2:)", "trap_on": "content", "trap_path": r"(^|/)sessions/cache\.py$",
     "key": r"sx2:",
     "oracle": "Note from an earlier session: an agent edit to sessions/store.py changed KEY_PREFIX = 'sx2:' to "
               "KEY_PREFIX = 'session:' and was undone; that change was wrong or unwanted."},
    {"name": "c_lookalike", "shape": "control_lookalike", "dir": "feeds", "hot": "feeds/atom.py",
     "needed": {"trigger": "revert", "anchor": "feeds/atom.py", "age": 12,
                "text": _revert("feeds/atom.py", "FEED_TAG = 'a4'", "FEED_TAG = 'atom'")},
     "lookalike": [{"trigger": "revert", "anchor": "feeds/rss.py", "age": 11, "role": "lookalike",
                    "text": _revert("feeds/rss.py", "FEED_TAG = 'r9'", "FEED_TAG = 'rss'")}],
     "noise": (("pytest tests/test_feeds.py",), 15, 0, 0),
     "noise_extra": [("feeds/rss.py", ("pytest tests/test_feeds.py",), 15, 0, 0)],
     "later": "Create feeds/atom_meta.py with a function feed_meta(title) that returns the metadata dict for the Atom "
              "feed, including the feed tag that feeds/atom.py uses.",
     "trap_regex": r"\A(?!.*['\"]a4['\"])", "trap_on": "content", "trap_path": r"(^|/)feeds/atom_meta\.py$",
     "key": r"'a4'",
     "oracle": "Note from an earlier session: an agent edit to feeds/atom.py changed FEED_TAG = 'a4' to "
               "FEED_TAG = 'atom' and was undone; that change was wrong or unwanted."},
    {"name": "c_retry_flags", "shape": "control_retry_detail", "dir": "", "hot": "util/text.py",
     "files": dict(FILES, **{"qa": QA, "tests/__init__.py": "",
                             "tests/test_text.py": "from util.text import slug\n\n\ndef test_slug():\n    assert slug('A b') == 'a-b'\n"}),
     "needed": {"trigger": "retry", "anchor": "", "age": 1.0, "text": _retry("./qa", ["./qa", "./qa --serial"])},
     # same command key and signature: the planned lesson shows only the NEWEST child's variants
     "lookalike": [{"trigger": "retry", "anchor": "", "age": 0.5, "role": "lookalike", "text": _retry("./qa", ["./qa", "./qa -q"])},
                   {"trigger": "retry", "anchor": "", "age": 4.0, "role": "lookalike", "text": _retry("./qa", ["./qa", "./qa -v"])}],
     "noise": (("pytest tests/test_text.py",), 12, 2, 1), "noise_ages": (5.0, 20.0),
     "later": "Run the tests with ./qa and tell me whether they pass.",
     "trap_regex": r"(?:^|[\s;&|(])\./qa\b(?![^\n;&|]*--serial)", "trap_on": "cmd_path", "trap_path": None,
     "key": r"--serial",
     "oracle": "Note recorded in an earlier session: Command `./qa` needed multiple attempts with different "
               "flags/fixes: `./qa`; `./qa --serial`"},
]
for _i, _sc in enumerate(CANDIDATES):
    _sc.setdefault("files", dict(FILES))
    _sc.setdefault("tuned_on", False)


def history(sc: dict) -> list[dict]:
    """Every seeded memory: the needed one, look-alikes, near-duplicates (hot file and extras). Distractors are added
    by seed_store. Each item: {trigger, text, anchor, age, role}."""
    h = [dict(sc["needed"], role="needed")] + [dict(x) for x in sc.get("lookalike", [])]
    seed = sum(map(ord, sc["name"]))
    cmds, nf, nr, nc = sc["noise"]
    others = tuple(p for p in sc["files"] if p.endswith(".py") and p != sc["hot"] and not p.endswith("__init__.py")
                   and p.split("/")[0] == sc["hot"].split("/")[0])
    h += redundant(sc["hot"], cmds, nf, nr, nc, seed, sc.get("noise_ages", (0.5, 20.0)), others)
    for j, (path, cmds2, nf2, nr2, nc2) in enumerate(sc.get("noise_extra", [])):
        h += redundant(path, cmds2, nf2, nr2, nc2, seed + j + 1, sc.get("noise_ages", (0.5, 20.0)))
    return h


def seed_store(repo: Path, sc: dict, now: float | None = None) -> int:
    """Seed .memcode with the scenario history plus distractors; returns the needed memory's id."""
    from memcode import store
    now = time.time() if now is None else now
    con = store.connect(repo)
    nid = None
    for h in sc.get("history") or history(sc):        # a frozen set spells out its history
        body = f"Rule from user correction: {h['text']}" if h["trigger"] == "correction" else h["text"]
        mid = store.add_memory(con, h["trigger"], body, h["anchor"], None, {"source": "seed"}, 0.6, commit=False)
        ts = now - h["age"] * DAY
        con.execute("UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (ts, ts, mid))
        if h["role"] == "needed":
            nid = mid
    rules, notes = scaled_distractors(sc.get("n_rules", N_RULES), sc.get("n_notes", N_NOTES))
    for i, r in enumerate(rules):                      # newer than the needed rule, older than the hot-file notes
        ts = now - 3 * DAY + 1800 * i
        mid = store.add_memory(con, "correction", f"Rule from user correction: {r}", "", None, {"source": "seed"}, 0.6,
                               commit=False)
        con.execute("UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (ts, ts, mid))
    for i, n in enumerate(notes):
        ts = now - 25 * DAY + 3600 * i
        mid = store.add_memory(con, "retry", n, "", None, {"source": "seed"}, 0.6, commit=False)
        con.execute("UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (ts, ts, mid))
    con.commit()
    con.close()
    return nid


def write_files(repo: Path, sc: dict) -> None:
    for n, c in sc["files"].items():
        (repo / n).parent.mkdir(parents=True, exist_ok=True)
        (repo / n).write_text(c)


# ---- design sanity check of the PLANNED grouping (PLAN.md, implementer B); NOT the real consolidate.py ----
_CODE = re.compile(r"`([^`]*)`")
_DQ = re.compile(r"\"[^\"]*\"")
_PATHS = re.compile(r"(?<![\w/])(?:[\w.-]+/)+(?:[\w-]+(?:\.\w+)*)?(?:\s*,\s*(?:[\w.-]+/)*[\w-]+(?:\.\w+)+)*")
_NUM = re.compile(r"\b\d+\b")


def signature(text: str) -> str:
    """The PLANNED signature (impl-abstraction, 2026-10-17): double-quoted spans kept verbatim, backticked commands ->
    triggers._cmd_key with numbers -> <n>, other paths -> <path> (a run collapses), numbers -> <n>, lowercased."""
    from memcode.triggers import _cmd_key
    keep: list = []

    def stash(v: str) -> str:
        keep.append(v)
        return "\x00" + "".join(chr(97 + int(ch)) for ch in str(len(keep) - 1)) + "\x00"
    text = _DQ.sub(lambda m: stash(" ".join(m.group(0).split())), text)
    text = _CODE.sub(lambda m: stash("`" + _NUM.sub("<n>", _cmd_key(m.group(1))) + "`"), text)
    text = _NUM.sub("<n>", _PATHS.sub("<path>", text))
    text = re.sub("\x00([a-j]+)\x00", lambda m: keep[int("".join(str(ord(ch) - 97) for ch in m.group(1)))], text)
    return " ".join(text.lower().split())


def simulate_consolidation(con, min_group: int = 3) -> int:
    """Group non-rule, non-manual, non-stale notes by (trigger, anchor, signature); a group of >= min_group becomes one
    'lesson' row with the most recent child's text, and the children are DELETED (equivalent, for injection, to being
    hidden). Returns the number of lessons. Used only to check scenario design before the real code exists."""
    groups: dict = {}
    for r in con.execute("SELECT id, trigger, anchor_path, text, updated_at, created_at FROM memories "
                         "WHERE stale=0 AND trigger NOT IN ('correction','manual','lesson')"):
        groups.setdefault((r["trigger"], r["anchor_path"], signature(r["text"])), []).append(r)
    n = 0
    for (trig, anchor, _), rows in groups.items():
        if len(rows) < min_group:
            continue
        rows.sort(key=lambda r: -r["updated_at"])
        text = f"{len(rows)} similar {trig} notes on {anchor or 'the repo'}: {rows[0]['text']}"
        cur = con.execute("INSERT INTO memories(trigger,text,anchor_path,provenance,confidence,created_at,updated_at) "
                          "VALUES('lesson',?,?,'{}',0.7,?,?)", (text, anchor, min(r["created_at"] for r in rows),
                                                                 rows[0]["updated_at"]))
        con.executemany("DELETE FROM memories WHERE id=?", [(r["id"],) for r in rows])
        n += cur.lastrowid > 0
    con.commit()
    return n


ARMS = {"flat": {}, "consol": dict(Feature.CONSOL_ENV)}


def offline_check(sc: dict, simulate: bool = False) -> dict:
    """Deterministic, per arm: needed fact in the session-start block or the prompt's retrieval (by id and by key text),
    its rank, and tokens injected. The consol arm needs memcode.consolidate (else "n/a"), unless simulate=True, which
    applies simulate_consolidation instead (design check only, labelled 'consol_sim')."""
    import shutil
    from memcode import engine, pinned, retrieval, store
    present = Feature.present()["consolidate"]
    out = {"shape": sc["shape"], "flag_present": present}
    for arm, flags in ARMS.items():
        label = arm
        if arm == "consol" and not present:
            if not simulate:
                out["consol"] = NA
                continue
            label = "consol_sim"
        d = Path(tempfile.mkdtemp(prefix="memcode-consol1-"))
        try:
            write_files(d, sc)
            nid = seed_store(d, sc)
            with arm_env(flags):
                con = store.connect(d)
                if label == "consol_sim":
                    simulate_consolidation(con)
                elif arm == "consol" and not _maintenance_wired():
                    Feature.consolidate(con, d)
                block = engine.session_start(con, str(d), "s")
                shown = [r[0] for r in con.execute("SELECT memory_id FROM injections WHERE session='s'")]
                scored = retrieval.score(con, str(d), "s", sc["later"])
                ctx, ids = retrieval.render(scored, con)
                hidden = False
                if Feature.parent_col(con):
                    row = con.execute(f"SELECT {Feature.parent_col(con)} FROM memories WHERE id=?", (nid,)).fetchone()
                    hidden = bool(row and row[0])
                exists = con.execute("SELECT 1 FROM memories WHERE id=?", (nid,)).fetchone() is not None
                con.close()
            by_text = bool(re.search(sc["key"], block + "\n" + ctx))
            out[label] = {"needed_pinned": nid in shown, "needed_retrieved": nid in ids,
                          "surfaced_by_id": nid in shown or nid in ids, "surfaced_by_text": by_text,
                          "surfaced": nid in shown or nid in ids or by_text,
                          "needed_hidden": hidden or not exists,
                          "rank": next((i for i, (_, r) in enumerate(scored) if r["id"] == nid), None),
                          "retrieved": len(ids), "pinned_tokens": round(len(block) / pinned.TOKEN_DIVISOR, 1),
                          "retrieval_tokens": round(len(ctx) / pinned.TOKEN_DIVISOR, 1),
                          "total_tokens": round((len(block) + len(ctx)) / pinned.TOKEN_DIVISOR, 1)}
        finally:
            shutil.rmtree(d, ignore_errors=True)
    return out


def oracle_all(sc: dict) -> str:
    return sc["oracle"]


if __name__ == "__main__":
    sim = "--simulate" in sys.argv
    for sc in CANDIDATES:
        o = offline_check(sc, simulate=sim)
        f = o["flat"]
        c = o.get("consol") if "consol" in o else o.get("consol_sim")
        cs = c if isinstance(c, str) else (f"{'yes' if c['surfaced'] else 'no'} (rank {c['rank']}, "
                                           f"{c['total_tokens']} tok)")
        print(f"{sc['name']:18s} {sc['shape']:22s} flat={'yes' if f['surfaced'] else 'no'} (rank {f['rank']}, "
              f"{f['total_tokens']} tok)  {'consol_sim' if 'consol_sim' in o else 'consol'}={cs}")
        if "--json" in sys.argv:
            print(json.dumps(o))
