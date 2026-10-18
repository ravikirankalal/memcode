"""Deterministic evaluation of hierarchical memory: consolidation (abstraction hierarchy), the storage budget and
labels. No model calls. Question: "is it useful, what do we gain over the run that does not use it?"

Stores are synthetic but shaped like memcode's real captures (texts follow memcode/triggers.py templates):
  noise     many near-duplicate fail_to_fix / revert / retry notes, concentrated on a few hot files (Zipf-like)
  stale     notes anchored to files that no longer exist (mark_stale hides them)
  rules     distractor user rules about synthetic areas (pressure.scaled_distractors), plus a few needed rules
  valuable  a fixed set of distinct notes and rules, each NEEDED by one task prompt (PROMPTS)
Arms (each on a fresh copy of the same store; MEMCODE_* stripped, then set):
  flat      MEMCODE_RETRIEVAL=1, default split ranking (= run.py memcode_split)
  consol    flat + the consolidation flag (+ the explicit consolidation entry point, if the plan names one)
  budget    consol + the storage budget at BUDGET_FRACTION of the store size
  labels    flat + the labels flag: must not change what is shown (ids and order)
Measures (shared with bench-scope, see the bulletin): tokens = chars / pinned.TOKEN_DIVISOR of the session-start block
and of the per-prompt retrieval context; needed_surfaced by id (pinned.shown_ids / retrieval ids) and by text (the
prompt's key regex in the injected text, so a lesson that keeps the fact counts and one that drops it does not).

Until the developers' code exists every flag-on cell prints "n/a (feature not present)"; flag-off numbers are never
copied into a flag-on column. The developers' names live ONLY in the adapter below (`Feature`).

  python3 bench/consolidation_eval.py                         # sizes 100,1000,5000 + latency at 5000,20000
  python3 bench/consolidation_eval.py --sizes 100 --latency ""  # quick
  python3 bench/consolidation_eval.py --labels-only
Results: bench/live/results/consolidation_eval.{json,md} (git-ignored).
"""
from __future__ import annotations

import argparse
import contextlib
import importlib
import inspect
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NA = "n/a (feature not present)"
DAY = 86400.0
BUDGET_FRACTION = 0.5


# ============================================================================================================
# Adapter: the ONLY place that names the developers' API. Update these names from the bulletin plan.
# ============================================================================================================
class Feature:
    """Names from PLAN.md (coordinator, 20:39): MEMCODE_CONSOLIDATE=1 runs consolidate.run_if_enabled inside
    engine.session_start (maintenance.run) and hides children (parent_id set) from injection; MEMCODE_STORE_BUDGET=N
    runs budget.enforce_if_enabled there too; labels are always assigned (labels.backfill), display only."""
    CONSOL_ENV = {"MEMCODE_CONSOLIDATE": "1"}
    BUDGET_ENV = "MEMCODE_STORE_BUDGET"
    LABELS_ENV: dict = {}                            # labels have no flag: always assigned, never rendered or ranked
    CONSOL = ("memcode.consolidate", ("run", "consolidate"))
    BUDGET = ("memcode.budget", ("enforce", "enforce_budget"))
    LABELS = ("memcode.labels", ("auto", "auto_labels", "labels_for"))
    PARENT_COLS = ("parent_id",)

    @staticmethod
    def _find(spec):
        mod_name, names = spec
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            return None
        return next((getattr(mod, n) for n in names if callable(getattr(mod, n, None))), None)

    @classmethod
    def consolidate_fn(cls):
        return cls._find(cls.CONSOL)

    @classmethod
    def budget_fn(cls):
        return cls._find(cls.BUDGET)

    @classmethod
    def label_fn(cls):
        return cls._find(cls.LABELS)

    @classmethod
    def parent_col(cls, con) -> str | None:
        cols = {r[1] for r in con.execute("PRAGMA table_info(memories)")}
        return next((c for c in cls.PARENT_COLS if c in cols), None)

    @classmethod
    def present(cls) -> dict:
        """Which features exist in the installed memcode (checked on a throwaway store for the schema)."""
        from memcode import store
        d = Path(tempfile.mkdtemp(prefix="memcode-consol-probe-"))
        try:
            con = store.connect(d)
            col = cls.parent_col(con)
            con.close()
        finally:
            shutil.rmtree(d, ignore_errors=True)
        return {"consolidate": cls.consolidate_fn() is not None and col is not None,
                "budget": cls.budget_fn() is not None, "labels": cls.label_fn() is not None, "parent_col": col}

    @staticmethod
    def _call(fn, con, root, **kw):
        """fn(con[, root][, now=...][, cap=...]) whatever subset its signature takes."""
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            return fn(con, **kw)
        names = list(params)
        args = [con]
        if len(names) > 1 and names[1] in ("root", "repo_root", "repo"):
            args.append(str(root))
        extra = {k: v for k, v in kw.items() if k in params}
        if "now" in params and "now" not in extra:
            extra["now"] = time.time()
        return fn(*args, **extra)

    @classmethod
    def consolidate(cls, con, root):
        """Explicit run (latency only: with CONSOL_ENV set, engine.session_start runs it anyway)."""
        fn = cls.consolidate_fn()
        return None if fn is None else cls._call(fn, con, root)

    @classmethod
    def enforce_budget(cls, con, root, cap: int):
        fn = cls.budget_fn()
        return None if fn is None else cls._call(fn, con, root, cap=cap)

    @classmethod
    def labels(cls, text: str, trigger: str = "manual", anchor: str = "") -> set[str]:
        """The automatic labeller: labels.auto(trigger, text, anchor_path)."""
        fn = cls.label_fn()
        if fn is None:
            return set()
        try:
            out = fn(trigger, text, anchor)
        except TypeError:
            out = fn(text)
        return {str(x) for x in (out or [])}

    @classmethod
    def children(cls, con) -> dict[int, list[int]]:
        col = cls.parent_col(con)
        if not col:
            return {}
        out: dict[int, list[int]] = {}
        for r in con.execute(f"SELECT id, {col} FROM memories WHERE {col} IS NOT NULL"):
            out.setdefault(r[1], []).append(r[0])
        return out


@contextlib.contextmanager
def arm_env(flags: dict):
    """Strip inherited MEMCODE_* (as bench/live/run.py does), set retrieval on plus the arm's flags."""
    saved = {k: v for k, v in os.environ.items() if k.startswith("MEMCODE_") or k == "CLAUDE_PROJECT_DIR"}
    for k in saved:
        os.environ.pop(k)
    os.environ.update({"MEMCODE_RETRIEVAL": "1", "MEMCODE_HIER": "0", **flags})   # flat unless an arm says so
    try:
        yield
    finally:
        for k in [k for k in os.environ if k.startswith("MEMCODE_") or k == "CLAUDE_PROJECT_DIR"]:
            os.environ.pop(k)
        os.environ.update(saved)


# ============================================================================================================
# Synthetic repo and store
# ============================================================================================================
AREAS = {   # dir -> (files, test commands)
    "api": (["handlers.py", "routes.py", "schemas.py", "auth.py"],
            ["pytest tests/test_api.py", "./qa api", "make test-api"]),
    "billing": (["invoice.py", "tax.py", "refunds.py", "currency.py"],
                ["pytest tests/test_billing.py", "./qa billing", "make test-billing"]),
    "worker": (["jobs.py", "queue.py", "scheduler.py"], ["pytest tests/test_worker.py", "./qa worker"]),
    "search": (["index.py", "rank.py", "tokenize.py"], ["pytest tests/test_search.py", "./qa search"]),
    "db": (["models.py", "migrate.py", "session.py"], ["pytest tests/test_db.py", "./qa db"]),
    "util": (["dates.py", "strings.py", "io.py"], ["pytest tests/test_util.py"]),
    "cli": (["main.py", "commands.py"], ["pytest tests/test_cli.py"]),
    "tests": (["test_api.py", "test_billing.py", "test_worker.py", "test_search.py", "test_db.py", "test_util.py",
               "test_cli.py", "factories.py"], ["pytest", "./qa"]),
}
TOP_FILES = {"README.md": "Demo service.\n", "requirements.txt": "requests==2.31.0\n", "Makefile": "docs:\n\ttrue\n",
             "pyproject.toml": "[project]\nname = 'demo'\n", "docs/index.md": "# Docs\n"}
HOT = [("api/handlers.py", 5), ("billing/invoice.py", 4), ("worker/jobs.py", 3), ("search/index.py", 2),
       ("tests/test_api.py", 2)]
HOT_SHARE = 0.65                                     # share of noise on the hot files; the rest spreads over all files
NOISE_MIX = (("fail_to_fix", 0.45), ("revert", 0.27), ("retry", 0.28))
TOPICS = ["create", "update", "delete", "list", "auth", "totals", "retry", "rank", "parse", "limits", "paging",
          "timeout", "encoding", "schema", "cache", "order", "refund", "tokens", "dates", "export"]
EDITS = [("timeout={a}", "timeout={b}"), ("retries={a}", "retries={b}"), ("limit = {a}", "limit = {b}"),
         ("return None", "raise KeyError(key)"), ("if not items:", "if items is None:"), ("page_size={a}", "page_size={b}"),
         ("sorted(rows)", "sorted(rows, reverse=True)"), ("x.strip()", "x.rstrip()"), ("cache[k] = v", "cache.setdefault(k, v)")]


def repo_files() -> dict[str, str]:
    out = dict(TOP_FILES)
    for d, (files, _) in AREAS.items():
        if d != "tests":
            out[f"{d}/__init__.py"] = ""
        for f in files:
            out[f"{d}/{f}"] = f"# {d}/{f}\n\ndef placeholder():\n    return None\n"
    return out


def _cmd_for(path: str, rnd: random.Random) -> str:
    d = path.split("/", 1)[0]
    return rnd.choice(AREAS.get(d, (None, ["pytest -q"]))[1])


FLAGS = ["-q", "--lf", "-vv", "-q --lf", "-k {t}", "-q -k {t}", "--maxfail=1", "-q --maxfail=1", "-rA", "-q -rA",
         "--ff", "-q --ff", "-k {t} --lf", "-vv -k {t}", "--tb=short", "-q --tb=short", "--durations=5", "-q -s"]


def _noise(trig: str, path: str, k: int, rnd: random.Random) -> tuple[str, str, str]:
    """(text, anchor, cluster) for one near-duplicate derived note, in memcode/triggers.py's exact templates.
    Variation is the realistic kind (the trigger never stores an exact duplicate): fail_to_fix = one of the area's
    test commands with different flags and edited-file lists; revert = a distinct snippet (or a plain checkout);
    retry = the same command tried with two flag variants. cluster = (trigger, anchor or command): what a reader
    would call 'the same lesson'."""
    d = path.split("/", 1)[0]
    files, cmds = AREAS.get(d, ([], ["pytest"]))
    if trig == "fail_to_fix":
        sib = [f"{d}/{f}" for f in files if f"{d}/{f}" != path]
        extra = rnd.sample(sib, min(len(sib), rnd.choice([0, 0, 1, 2])))
        flag = rnd.choice(FLAGS).format(t=f"{rnd.choice(TOPICS)}{'' if k % 3 else k % 97}")
        return (f"`{rnd.choice(cmds)} {flag}` failed and passed after editing {', '.join(extra + [path])}. "
                f"Fix was in {path}."), path, f"fail_to_fix:{path}"
    if trig == "revert":
        if rnd.random() < 0.15:
            via = rnd.choice([f"git checkout -- {path}", f"git restore {path}", f"git checkout HEAD -- {path}"])
            return f"Agent edits to {path} were reverted via `{via}`.", path, f"revert:{path}"
        o, n = rnd.choice(EDITS)
        a, b = rnd.randint(1, 99), rnd.randint(100, 999) + k
        return (f"Agent edit to {path} was undone by a later edit (changed \"{o.format(a=a, b=b)}\" -> "
                f"\"{n.format(a=a, b=b)}\" and back). That change was wrong or unwanted."), path, f"revert:{path}"
    key = rnd.choice(cmds)
    f1, f2 = rnd.sample(FLAGS, 2)
    t = f"{rnd.choice(TOPICS)}{k % 89}"
    return _retry(key, [f"{key} {f1.format(t=t)}", f"{key} {f2.format(t=t)}"]), "", f"retry:{key}"


def _retry(key: str, variants: list) -> str:
    return f"Command `{key}` needed multiple attempts with different flags/fixes: " + "; ".join(f"`{v}`" for v in variants)


# Valuable items: distinct facts, each needed by one prompt below. kind: rule | note
VALUABLE = [
    {"tag": "r_billing_cents", "kind": "rule", "age": 40,
     "text": "Amounts in billing/ are integer cents; never use float or Decimal for money."},
    {"tag": "r_tests_factories", "kind": "rule", "age": 38,
     "text": "Tests in tests/ build objects with the factories in tests/factories.py, never by hand."},
    {"tag": "r_cli_exit3", "kind": "rule", "age": 36,
     "text": "Commands in cli/ exit with status 3 on bad input, never 1 or 2."},
    {"tag": "t_api_tuple", "kind": "rule", "age": 50,
     "text": "Handlers in api/ return (status, body) tuples and never raise HTTP errors."},
    {"tag": "t_queue_256kb", "kind": "note", "trigger": "manual", "anchor": "worker/queue.py", "age": 45,
     "text": "worker/queue.py drops messages larger than 256 KB without an error; split payloads before enqueueing."},
    {"tag": "n_jobs_idempotent", "kind": "note", "trigger": "manual", "anchor": "worker/jobs.py", "age": 35,
     "text": "worker/jobs.py: jobs must be idempotent; the scheduler re-delivers a job after a 30 s visibility timeout."},
    {"tag": "n_migrate_down", "kind": "note", "trigger": "manual", "anchor": "db/migrate.py", "age": 33,
     "text": "db/migrate.py: every upgrade() needs a matching downgrade(); the release check runs both."},
    {"tag": "n_search_casefold", "kind": "note", "trigger": "revert", "anchor": "search/index.py", "age": 30,
     "text": "Agent edit to search/index.py was undone by a later edit (changed \"text.casefold()\" -> \"text.lower()\" "
             "and back). That change was wrong or unwanted."},
    {"tag": "n_docs_sphinxopts", "kind": "note", "trigger": "retry", "anchor": "", "age": 28,
     "text": "Command `make docs` needed multiple attempts with different flags/fixes: `make docs`; "
             "`make docs SPHINXOPTS=-W --keep-going`"},
    {"tag": "n_routes_v2", "kind": "note", "trigger": "revert", "anchor": "api/routes.py", "age": 26,
     "text": "Agent edit to api/routes.py was undone by a later edit (changed \"prefix='/v2'\" -> \"prefix='/api'\" "
             "and back). That change was wrong or unwanted."},
    {"tag": "n_schemas_forbid", "kind": "note", "trigger": "revert", "anchor": "api/schemas.py", "age": 26,
     "text": "Agent edit to api/schemas.py was undone by a later edit (changed \"extra='forbid'\" -> \"extra='ignore'\" "
             "and back). That change was wrong or unwanted."},
]
MUST_NOT_MERGE = [("n_routes_v2", "n_schemas_forbid"), ("n_search_casefold", "n_jobs_idempotent")]

# shape: crowded_* = needed fact competes with many near-duplicates on the file the prompt names (consolidation
# should help); control_* = consolidation could hurt (detail inside a consolidatable note, look-alike siblings) or
# has nothing to fix (cold file / cold directory).
PROMPTS = [
    {"name": "billing_discount", "shape": "crowded_rule", "needed": "r_billing_cents", "key": r"integer cents",
     "prompt": "Add a function to billing/invoice.py that applies a percentage discount to an invoice total."},
    {"name": "api_delete", "shape": "crowded_old_rule", "needed": "t_api_tuple", "key": r"\(status, body\)",
     "prompt": "Add a handler to api/handlers.py that deletes a user by id."},
    {"name": "test_delete", "shape": "crowded_rule", "needed": "r_tests_factories", "key": r"never by hand",
     "prompt": "Write a test in tests/test_api.py for the user deletion handler."},
    {"name": "nightly_job", "shape": "crowded_note", "needed": "n_jobs_idempotent", "key": r"idempotent",
     "prompt": "Add a job to worker/jobs.py that recomputes search rankings every night."},
    {"name": "queue_export", "shape": "manual_note", "needed": "t_queue_256kb", "key": r"256 KB",
     "prompt": "Send the nightly export through worker/queue.py as one message."},
    {"name": "migration", "shape": "control_cold_note", "needed": "n_migrate_down", "key": r"downgrade",
     "prompt": "Write a migration in db/migrate.py that adds an email column to users."},
    {"name": "normalise_query", "shape": "control_child_detail", "needed": "n_search_casefold", "key": r"casefold",
     "prompt": "Normalise query text in search/index.py before tokenising it."},
    {"name": "mount_routes", "shape": "control_lookalike", "needed": "n_routes_v2", "key": r"/v2",
     "prompt": "Mount the user routes in api/routes.py."},
    {"name": "schema_field", "shape": "control_lookalike", "needed": "n_schemas_forbid", "key": r"forbid",
     "prompt": "Add a nickname field to the user schema in api/schemas.py."},
    {"name": "cli_verbose", "shape": "control_cold_rule", "needed": "r_cli_exit3", "key": r"status 3",
     "prompt": "Add a --verbose option to cli/main.py."},
    {"name": "docs_build", "shape": "distinct_retry", "needed": "n_docs_sphinxopts", "key": r"SPHINXOPTS",
     "prompt": "Build the docs with make docs and fix any warnings."},
]


def mix_for(n: int) -> dict:
    """How a store of n memories splits."""
    fixed = len(VALUABLE)
    rules = max(5, round(0.06 * n))
    stale = max(3, round(0.08 * n))
    noise = max(0, n - fixed - rules - stale)
    return {"valuable": fixed, "distractor_rules": rules, "stale": stale, "noise": noise}


def _git_init(d: Path) -> None:
    for c in (["init", "-q"], ["add", "."], ["-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "i"]):
        subprocess.run(["git", *c], cwd=d, check=True, capture_output=True)


def build_store(n: int, seed: int = 0, now: float | None = None) -> tuple[Path, dict]:
    """A git repo with a seeded .memcode of exactly n memories. Returns (repo, meta); meta["ids"] maps memory id ->
    {"cluster", "tag", "kind"} and meta["tags"] maps a valuable tag -> its memory id."""
    from bench.live.pressure import scaled_distractors
    from memcode import store
    now = time.time() if now is None else now
    rnd = random.Random(1000 + n + seed)
    d = Path(tempfile.mkdtemp(prefix=f"memcode-consol-{n}-")) / "r"
    d.mkdir(parents=True)
    for p, c in repo_files().items():
        (d / p).parent.mkdir(parents=True, exist_ok=True)
        (d / p).write_text(c)
    _git_init(d)
    mix = mix_for(n)
    con = store.connect(d)
    meta: dict = {"ids": {}, "tags": {}, "n": n, "mix": mix}

    def put(trig, text, anchor, age, cluster, kind, tag=None):
        mid = store.add_memory(con, trig, text, anchor, None, {"source": "seed"}, 0.6, commit=False)
        ts = now - age * DAY
        con.execute("UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (ts, ts, mid))
        meta["ids"][mid] = {"cluster": cluster, "tag": tag, "kind": kind}
        if tag:
            meta["tags"][tag] = mid
        return mid

    for v in VALUABLE:
        if v["kind"] == "rule":
            put("correction", f"Rule from user correction: {v['text']}", "", v["age"], v["tag"], "rule", v["tag"])
        elif v["kind"] == "note":
            put(v["trigger"], v["text"], v["anchor"], v["age"], v["tag"], "note", v["tag"])
    rules, _ = scaled_distractors(mix["distractor_rules"], 0)
    for i, r in enumerate(rules):
        put("correction", f"Rule from user correction: {r}", "", rnd.uniform(0, 60), f"drule:{i}", "distractor_rule")
    for k in range(mix["stale"]):
        trig = rnd.choice(["fail_to_fix", "revert"])
        text, _, _ = _noise(trig, f"legacy/gone_{k % 40}.py", k, rnd)
        put(trig, text, f"legacy/gone_{k % 40}.py", rnd.uniform(5, 90), f"stale:{k % 40}", "stale")
    all_files = [p for p in repo_files() if p.endswith(".py")]
    hot_w = [w for _, w in HOT]
    trigs, tw = zip(*NOISE_MIX)
    seen: set = set()
    k = 0
    while k < mix["noise"]:
        path = rnd.choices([p for p, _ in HOT], hot_w)[0] if rnd.random() < HOT_SHARE else rnd.choice(all_files)
        trig = rnd.choices(trigs, tw)[0]
        text, anchor, cluster = _noise(trig, path, k, rnd)
        if (trig, anchor, text) in seen:          # the trigger never stores an exact duplicate
            continue
        seen.add((trig, anchor, text))
        put(trig, text, anchor, rnd.uniform(0, 60), cluster, "noise")
        k += 1
    con.commit()
    con.close()
    return d, meta


def copy_store(src: Path) -> Path:
    dst = Path(tempfile.mkdtemp(prefix="memcode-consol-run-")) / "r"
    shutil.copytree(src, dst, symlinks=True)
    return dst


def _rmtree(d: Path) -> None:
    shutil.rmtree(d.parent if d.name == "r" else d, ignore_errors=True)


# ============================================================================================================
# One arm on one store
# ============================================================================================================
ARMS = {   # arm -> (features it needs, flags)
    "flat": ((), {}),
    "consol": (("consolidate",), dict(Feature.CONSOL_ENV)),
    "budget": (("consolidate", "budget"), dict(Feature.CONSOL_ENV)),      # + BUDGET_ENV=cap; merge before evict
    "labels_user": (("labels",), {}),     # flat + a random user label on every row: injection must not change
    "labels_empty": (("labels",), {}),    # flat with labelling switched off (labels.backfill no-op, column cleared)
}


def _maintenance_wired() -> bool:
    """True once engine.session_start runs memcode/maintenance.py (the integration branch after the shared commit)."""
    try:
        importlib.import_module("memcode.maintenance")
        return True
    except ImportError:
        return False


def measure(template: Path, meta: dict, arm: str, prompts: list[dict] = PROMPTS, budget_cap: int | None = None) -> dict:
    """Run one arm on a fresh copy: session start (which runs consolidation / the budget when their flags are set),
    then each prompt in its own session that was shown the same block. Returns aggregates and per-prompt rows."""
    from memcode import engine, pinned, retrieval, store
    feat = Feature.present()
    need, flags = ARMS[arm]
    missing = [f for f in need if not feat[f]]
    if missing:
        return {"arm": arm, "present": False, "missing": missing}
    flags = dict(flags)
    if arm == "budget":
        flags[Feature.BUDGET_ENV] = str(budget_cap)
    d = copy_store(template)
    out: dict = {"arm": arm, "present": True, "flags": flags}
    patched = None
    with arm_env(flags):
        con = store.connect(d)
        before = _census(con, meta)
        if arm == "labels_user":
            from memcode import labels as _labels
            vocab = sorted(getattr(_labels, "VOCAB", LABEL_VOCAB))
            rnd = random.Random(7)
            con.executemany("UPDATE memories SET labels=? WHERE id=?",
                            [(",".join(sorted(rnd.sample(vocab, 2))), r[0]) for r in con.execute("SELECT id FROM memories")])
            con.commit()
        if arm == "labels_empty":
            from memcode import labels as _labels
            patched = (_labels, _labels.backfill)
            _labels.backfill = lambda *a, **k: 0
            con.execute("UPDATE memories SET labels=''")
            con.commit()
        if not _maintenance_wired():          # before the shared commit: run the steps the way maintenance.run will
            if arm in ("consol", "budget"):
                Feature.consolidate(con, d)
            if arm == "budget":
                Feature.enforce_budget(con, d, budget_cap)
        try:
            t = time.perf_counter()
            block = engine.session_start(con, str(d), "s0")
            out["session_start_ms"] = round((time.perf_counter() - t) * 1000, 1)
        finally:
            if patched:
                patched[0].backfill = patched[1]
        shown = [r[0] for r in con.execute("SELECT memory_id FROM injections WHERE session='s0' ORDER BY id")]
        kids = Feature.children(con)
        out["store_before"], out["store_after"] = before, _census(con, meta)
        out["pinned_text"] = block
        out["pinned_tokens"] = round(len(block) / pinned.TOKEN_DIVISOR, 1)
        out["pinned_rules"], out["pinned_notes"] = pinned.count_injected(block)
        rule_ids = {r[0] for r in con.execute("SELECT id FROM memories WHERE trigger='correction'")}
        out["pinned_clusters"] = len(_clusters([i for i in shown if i not in rule_ids], meta, kids))
        out["pinned_useful"] = sorted(_useful_present(block, shown, meta, kids))
        out["pinned_ids"] = shown
        rows = []
        for i, p in enumerate(prompts):
            sid = f"q{i}"
            con.executemany("INSERT INTO injections(session,memory_id,ts) VALUES(?,?,?)",
                            [(sid, m, time.time()) for m in shown])
            con.commit()
            t = time.perf_counter()
            scored = retrieval.score(con, str(d), sid, p["prompt"])
            ctx, ids = retrieval.render(scored, con)
            ms = (time.perf_counter() - t) * 1000
            nid = meta["tags"].get(p["needed"])
            text_all = block + "\n" + ctx
            by_id = nid in shown or nid in ids
            by_text = bool(re.search(p["key"], text_all))
            parents = {pid for pid, ch in kids.items() if nid in ch}
            rows.append({"prompt": p["name"], "shape": p["shape"], "needed_pinned": nid in shown,
                         "needed_retrieved": nid in ids, "surfaced_by_id": by_id, "surfaced_by_text": by_text,
                         "surfaced": by_id or by_text, "needed_hidden": bool(parents),
                         "via_parent_without_text": bool(parents & (set(shown) | set(ids))) and not by_text,
                         "needed_exists": con.execute("SELECT 1 FROM memories WHERE id=?", (nid,)).fetchone() is not None,
                         "rank": next((j for j, (_, r) in enumerate(scored) if r["id"] == nid), None),
                         "retrieval_text": ctx, "retrieval_tokens": round(len(ctx) / pinned.TOKEN_DIVISOR, 1),
                         "retrieved_ids": ids, "retrieved_clusters": len(_clusters(ids, meta, kids)),
                         "retrieved_n": len(ids), "retrieval_ms": round(ms, 1)})
        out["prompts"] = rows
        out["wrong_merges"] = [list(pair) for pair in MUST_NOT_MERGE
                               if any(meta["tags"][pair[0]] in ch and meta["tags"][pair[1]] in ch for ch in kids.values())]
        out["parents"] = len(kids)
        out["children_hidden"] = sum(len(v) for v in kids.values())
        con.close()
    _rmtree(d)
    n = len(rows) or 1
    out["surfaced"] = sum(r["surfaced"] for r in rows)
    out["surfaced_by_id"] = sum(r["surfaced_by_id"] for r in rows)
    out["via_parent_without_text"] = sum(r["via_parent_without_text"] for r in rows)
    out["mean_retrieval_tokens"] = round(sum(r["retrieval_tokens"] for r in rows) / n, 1)
    out["mean_total_tokens"] = round(out["pinned_tokens"] + out["mean_retrieval_tokens"], 1)
    out["mean_retrieved_clusters"] = round(sum(r["retrieved_clusters"] for r in rows) / n, 2)
    out["mean_retrieved_n"] = round(sum(r["retrieved_n"] for r in rows) / n, 2)
    return out


def _clusters(ids, meta, kids) -> set[str]:
    out = set()
    for i in ids:
        for j in kids.get(i, [i]) if i in kids else [i]:
            m = meta["ids"].get(j) or meta["ids"].get(str(j))
            if m:
                out.add(m["cluster"])
    return out


def _useful_present(block: str, shown: list[int], meta: dict, kids: dict) -> set[str]:
    """Valuable tags whose fact is in the session-start block: shown by id, or its key text present."""
    keys = {p["needed"]: p["key"] for p in PROMPTS}
    out = set()
    for tag, mid in meta["tags"].items():
        if mid in shown or (tag in keys and re.search(keys[tag], block)):
            out.add(tag)
    return out


def _census(con, meta) -> dict:
    """Memories table only (facts are a separate table). rules = ids that must never be evicted."""
    rows = con.execute("SELECT id, trigger, stale, provenance FROM memories").fetchall()
    return {"total": len(rows), "live": sum(1 for r in rows if not r["stale"]),
            "rules": sorted(r["id"] for r in rows if r["trigger"] == "correction"),
            "valuable": sorted(t for t, i in meta["tags"].items() if any(r["id"] == i for r in rows))}


def budget_check(res: dict) -> dict:
    """Store size after the budget and the invariant: no user rule evicted."""
    if not res.get("present"):
        return {"present": False}
    b, a = res["store_before"], res["store_after"]
    lost_rules = sorted(set(b["rules"]) - set(a["rules"]))
    return {"present": True, "before": b["total"], "after": a["total"], "live_after": a["live"],
            "rules_evicted": lost_rules, "invariants_ok": not lost_rules,
            "valuable_lost": sorted(set(b["valuable"]) - set(a["valuable"]))}


# ============================================================================================================
# Labels: hand-labelled sample + scoring (display/filter only; must not change ranking)
# ============================================================================================================
LABEL_VOCAB = ("tests", "build", "deps", "vcs", "api", "db", "config", "style", "docs", "security", "perf", "ci")
# Map the developers' label names onto LABEL_VOCAB once the plan names their vocabulary (identity by default).
LABEL_ALIASES: dict[str, str] = {"test": "tests", "testing": "tests", "dependencies": "deps", "dependency": "deps",
                                 "git": "vcs", "revert": "vcs", "database": "db", "documentation": "docs",
                                 "performance": "perf", "configuration": "config", "lint": "style"}
LABELLED = [   # (trigger, anchor, text, gold labels) — realistic memcode memory texts, labelled by hand
    ("fail_to_fix", "tests/test_api.py", "`pytest -q tests/test_api.py` failed and passed after editing tests/test_api.py. Fix was in tests/test_api.py.", {"tests"}),
    ("fail_to_fix", "api/handlers.py", "`pytest -q tests/test_api.py::test_delete` failed and passed after editing api/handlers.py. Fix was in api/handlers.py.", {"tests", "api"}),
    ("retry", "", "Command `npm run build` needed multiple attempts with different flags/fixes: `npm run build`; `npm run build -- --force`", {"build"}),
    ("retry", "", "Command `make build` needed multiple attempts with different flags/fixes: `make build`; `make clean build`", {"build"}),
    ("dep_change", "requirements.txt", "Dependency/config file requirements.txt was changed by the agent.", {"deps"}),
    ("dep_change", "package.json", "Dependency/config file package.json was changed by the agent.", {"deps"}),
    ("dep_change", "pyproject.toml", "Dependency/config file pyproject.toml was changed by the agent.", {"deps", "config"}),
    ("revert", "db/models.py", "Agent edits to db/models.py were reverted via `git checkout -- db/models.py`.", {"vcs", "db"}),
    ("revert", "api/routes.py", "Agent edit to api/routes.py was undone by a later edit (changed \"prefix='/v2'\" -> \"prefix='/api'\" and back). That change was wrong or unwanted.", {"vcs", "api"}),
    ("revert", "util/strings.py", "Agent edits were reverted via `git stash` (last edited util/strings.py).", {"vcs"}),
    ("correction", "", "Rule from user correction: Never commit directly to main; open a pull request.", {"vcs"}),
    ("correction", "", "Rule from user correction: Commit messages start with the ticket id, e.g. PROJ-12: fix login.", {"vcs"}),
    ("correction", "", "Rule from user correction: Use tabs for indentation in Go files.", {"style"}),
    ("correction", "", "Rule from user correction: Functions in search/ are named with a _q suffix.", {"style"}),
    ("correction", "", "Rule from user correction: Run the tests with ./qa, never call pytest directly.", {"tests"}),
    ("correction", "", "Rule from user correction: Tests go in checks/, never tests/.", {"tests"}),
    ("correction", "", "Rule from user correction: Database migrations must be reversible; every upgrade() needs a downgrade().", {"db"}),
    ("correction", "", "Rule from user correction: Never log API tokens or passwords; redact them first.", {"security"}),
    ("correction", "", "Rule from user correction: Settings live in conf/settings.toml, never in .env files.", {"config"}),
    ("correction", "", "Rule from user correction: Update docs/api.md whenever an endpoint changes.", {"docs", "api"}),
    ("manual", "worker/jobs.py", "worker/jobs.py: jobs must be idempotent; the scheduler re-delivers a job after a 30 s visibility timeout.", set()),
    ("manual", "search/rank.py", "search/rank.py: ranking over 10k documents is slow; cache the idf table instead of recomputing it per query.", {"perf"}),
    ("manual", "db/session.py", "db/session.py: open one connection per request; the pool has only 5 slots.", {"db", "perf"}),
    ("manual", ".github/workflows/ci.yml", "The CI job runs on Python 3.9; avoid match statements and | in type hints.", {"ci"}),
    ("fail_to_fix", ".github/workflows/ci.yml", "`act -j test` failed and passed after editing .github/workflows/ci.yml. Fix was in .github/workflows/ci.yml.", {"ci", "tests"}),
    ("retry", "", "Command `docker compose up` needed multiple attempts with different flags/fixes: `docker compose up`; `docker compose up --build`", {"build"}),
    ("retry", "", "Command `make docs` needed multiple attempts with different flags/fixes: `make docs`; `make docs SPHINXOPTS=-W`", {"docs", "build"}),
    ("fail_to_fix", "conf/settings.toml", "`python3 -m app --check` failed and passed after editing conf/settings.toml. Fix was in conf/settings.toml.", {"config"}),
    ("manual", "api/auth.py", "api/auth.py: tokens are compared with hmac.compare_digest to avoid timing attacks.", {"security", "api"}),
    ("fail_to_fix", "util/dates.py", "`pytest -q tests/test_util.py` failed and passed after editing util/dates.py. Fix was in util/dates.py.", {"tests"}),
]


def normalise_labels(labels) -> set[str]:
    out = set()
    for x in labels or ():
        x = str(x).strip().lower().lstrip("#")
        out.add(LABEL_ALIASES.get(x, x))
    return out


def score_labels(pred: list[set[str]], gold: list[set[str]] = None) -> dict:
    """Micro/macro precision and recall of predicted labels against the hand labels, over LABEL_VOCAB. Predicted
    labels outside the vocabulary (after LABEL_ALIASES) are reported, and count as false positives in micro scores."""
    gold = [g for *_, g in LABELLED] if gold is None else gold
    assert len(pred) == len(gold)
    tp = fp = fn = 0
    per: dict[str, list[int]] = {lab: [0, 0, 0] for lab in LABEL_VOCAB}
    unknown: dict[str, int] = {}
    for p, g in zip(pred, gold):
        p = normalise_labels(p)
        for lab in p:
            if lab not in per:
                unknown[lab] = unknown.get(lab, 0) + 1
        for lab in p | g:
            hit_p, hit_g = lab in p, lab in g
            tp += hit_p and hit_g
            fp += hit_p and not hit_g
            fn += hit_g and not hit_p
            if lab in per:
                per[lab][0] += hit_p and hit_g
                per[lab][1] += hit_p and not hit_g
                per[lab][2] += hit_g and not hit_p
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    used = [lab for lab, (a, b, c) in per.items() if a + b + c]
    macro_p = statistics.mean([per[lab][0] / (per[lab][0] + per[lab][1]) if per[lab][0] + per[lab][1] else 0.0 for lab in used]) if used else 0.0
    macro_r = statistics.mean([per[lab][0] / (per[lab][0] + per[lab][2]) if per[lab][0] + per[lab][2] else 0.0 for lab in used]) if used else 0.0
    return {"micro_precision": round(prec, 3), "micro_recall": round(rec, 3),
            "micro_f1": round(2 * prec * rec / (prec + rec), 3) if prec + rec else 0.0,
            "macro_precision": round(macro_p, 3), "macro_recall": round(macro_r, 3),
            "coverage": round(sum(1 for p in pred if p) / len(pred), 3), "unknown_labels": unknown,
            "per_label": {lab: {"tp": a, "fp": b, "fn": c} for lab, (a, b, c) in per.items() if a + b + c}}


def labels_eval() -> dict:
    if not Feature.present()["labels"]:
        return {"present": False}
    pred = [Feature.labels(text, trig, anchor) for trig, anchor, text, _ in LABELLED]
    return {"present": True, **score_labels(pred), "pred": [sorted(p) for p in pred]}


def labels_rank_check(base: dict, lab: dict) -> dict:
    """Labels are display/filter only: the injected text (block and per-prompt context) and the shown ids must be
    identical between two runs that differ only in labels (random user labels vs labelling switched off)."""
    if not lab.get("present") or not base.get("present"):
        return {"present": False}
    same_pinned = base["pinned_ids"] == lab["pinned_ids"] and base["pinned_text"] == lab["pinned_text"]
    diff = [a["prompt"] for a, b in zip(base["prompts"], lab["prompts"])
            if a["retrieved_ids"] != b["retrieved_ids"] or a["retrieval_text"] != b["retrieval_text"]]
    return {"present": True, "pinned_identical": same_pinned, "prompts_changed": diff, "ok": same_pinned and not diff,
            "token_delta": round(lab["mean_total_tokens"] - base["mean_total_tokens"], 1)}


# ============================================================================================================
# Latency (in-process, like bench/perf.py but without interpreter start-up)
# ============================================================================================================
def latency(n: int, reps: int = 3) -> dict:
    """session start and per-prompt retrieval, flat vs consolidation on; consolidation alone on a raw store (first
    run) and again (incremental). Before maintenance is wired into session start, the flag-on session start is timed
    as explicit consolidation + session start."""
    from memcode import engine, retrieval, store
    template, meta = build_store(n)
    feat = Feature.present()
    with arm_env({}):                      # warm the terms cache once, as a store in steady use has it
        con = store.connect(template)
        retrieval.score(con, str(template), "warm", "warm up")
        con.close()
    out: dict = {"memories": n}
    for arm in ("flat", "consol"):
        if arm == "consol" and not feat["consolidate"]:
            out[arm] = NA
            continue
        flags = Feature.CONSOL_ENV if arm == "consol" else {}
        st, pr, co, co2 = [], [], [], []
        for i in range(reps):
            with arm_env(flags):
                if arm == "consol":
                    d = copy_store(template)
                    con = store.connect(d)
                    t = time.perf_counter(); Feature.consolidate(con, d); co.append((time.perf_counter() - t) * 1000)
                    t = time.perf_counter(); Feature.consolidate(con, d); co2.append((time.perf_counter() - t) * 1000)
                    con.close()
                    _rmtree(d)
                d = copy_store(template)
                con = store.connect(d)
                t = time.perf_counter()
                if arm == "consol" and not _maintenance_wired():
                    Feature.consolidate(con, d)
                engine.session_start(con, str(d), f"s{i}")
                st.append((time.perf_counter() - t) * 1000)
                t = time.perf_counter()
                for p in PROMPTS[:4]:
                    retrieval.render(retrieval.score(con, str(d), f"s{i}", p["prompt"]), con)
                pr.append((time.perf_counter() - t) * 1000 / 4)
                con.close()
                _rmtree(d)
        out[arm] = {"session_start_ms": _st(st), "prompt_retrieval_ms": _st(pr)}
        if co:
            out[arm].update(consolidate_first_ms=_st(co), consolidate_again_ms=_st(co2))
    _rmtree(template)
    return out


def _st(xs):
    xs = sorted(xs)
    return {"median": round(statistics.median(xs), 1), "p95": round(xs[min(len(xs) - 1, int(0.95 * len(xs)))], 1)}


# ============================================================================================================
# Report
# ============================================================================================================
def run_size(n: int) -> dict:
    template, meta = build_store(n)
    cap = int(BUDGET_FRACTION * n)
    res = {"n": n, "mix": meta["mix"], "budget_cap": cap}
    for arm in ARMS:
        res[arm] = measure(template, meta, arm, budget_cap=cap)
    res["budget_check"] = budget_check(res["budget"])
    res["labels_rank"] = labels_rank_check(res["labels_empty"], res["labels_user"])
    _rmtree(template)
    for arm in ARMS:                       # keep the JSON small: texts were only needed for the comparisons
        res[arm].pop("pinned_text", None)
        for row in res[arm].get("prompts", []):
            row.pop("retrieval_text", None)
    return res


def _cell(r: dict, f) -> str:
    return f(r) if r.get("present") else NA


def markdown(results: list[dict], lat: list[dict], lab: dict) -> str:
    out = ["# Consolidation / storage budget / labels: deterministic evaluation", "",
           f"Features present: {json.dumps(Feature.present())}", ""]
    nprompts = len(PROMPTS)
    out += ["## Needed facts surfaced and tokens injected (flag-off vs flag-on)", "",
            "| memories | arm | needed surfaced (id or text) | by id | parent shown, fact lost | useful in block | "
            "block notes / distinct note clusters | block tokens | mean retrieval tokens | mean total tokens | "
            "wrong merges |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        for arm in ("flat", "consol", "budget"):
            a = r[arm]
            out.append("| " + " | ".join([
                str(r["n"]), arm,
                _cell(a, lambda a: f"{a['surfaced']}/{nprompts}"), _cell(a, lambda a: f"{a['surfaced_by_id']}/{nprompts}"),
                _cell(a, lambda a: str(a["via_parent_without_text"])),
                _cell(a, lambda a: f"{len(a['pinned_useful'])}/{len(VALUABLE)}"),
                _cell(a, lambda a: f"{a['pinned_notes']} / {a['pinned_clusters']}"),
                _cell(a, lambda a: str(a["pinned_tokens"])), _cell(a, lambda a: str(a["mean_retrieval_tokens"])),
                _cell(a, lambda a: str(a["mean_total_tokens"])), _cell(a, lambda a: str(len(a["wrong_merges"])))]) + " |")
    out += ["", "## Per prompt (surfaced: flat -> consol -> budget)", "",
            "| prompt | shape | " + " | ".join(f"{r['n']}" for r in results) + " |",
            "|---|---|" + "---|" * len(results)]
    for i, p in enumerate(PROMPTS):
        cells = []
        for r in results:
            vals = []
            for arm in ("flat", "consol", "budget"):
                a = r[arm]
                if not a.get("present"):
                    vals.append("n/a")
                    continue
                row = a["prompts"][i]
                vals.append(("yes" if row["surfaced"] else "no") + (f"(r{row['rank']})" if row["rank"] is not None and not row["surfaced"] else ""))
            cells.append(" -> ".join(vals))
        out.append(f"| {p['name']} | {p['shape']} | " + " | ".join(cells) + " |")
    out += ["", f"## Storage budget (cap = {BUDGET_FRACTION:.0%} of the store)", "",
            "| memories | cap | store before | store after | live after | rules evicted | valuable lost |",
            "|---|---|---|---|---|---|---|"]
    for r in results:
        b = r["budget_check"]
        if not b.get("present"):
            out.append(f"| {r['n']} | {r['budget_cap']} | {r['flat']['store_before']['total']} | {NA} | {NA} | {NA} | {NA} |")
        else:
            out.append(f"| {r['n']} | {r['budget_cap']} | {b['before']} | {b['after']} | {b['live_after']} | "
                       f"{len(b['rules_evicted'])} | {', '.join(b['valuable_lost']) or '-'} |")
    out += ["", "## Hook latency (in-process, ms median / p95)", "",
            "| memories | arm | session start | per-prompt retrieval | consolidation (first run) | consolidation (again) |",
            "|---|---|---|---|---|---|"]
    for row in lat:
        for arm in ("flat", "consol"):
            a = row[arm]
            if not isinstance(a, dict):
                out.append(f"| {row['memories']} | {arm} | {a} | {a} | {a} | {a} |")
                continue
            f = lambda k: f"{a[k]['median']} / {a[k]['p95']}" if k in a else "-"
            out.append(f"| {row['memories']} | {arm} | {f('session_start_ms')} | {f('prompt_retrieval_ms')} | "
                       f"{f('consolidate_first_ms')} | {f('consolidate_again_ms')} |")
    out += ["", "## Labels", ""]
    if lab.get("present"):
        out.append(f"Automatic labeller on {len(LABELLED)} hand-labelled memories: micro P/R/F1 = "
                   f"{lab['micro_precision']}/{lab['micro_recall']}/{lab['micro_f1']}, macro P/R = "
                   f"{lab['macro_precision']}/{lab['macro_recall']}, coverage {lab['coverage']}, "
                   f"unknown labels {lab['unknown_labels']}.")
    else:
        out.append(f"Labeller: {NA}.")
    for r in results:
        lr = r["labels_rank"]
        out.append(f"- {r['n']} memories: labels change ranking? " + (NA if not lr.get("present") else
                   ("no (identical ids and order)" if lr["ok"] else f"YES: pinned identical={lr['pinned_identical']}, "
                                                                   f"prompts changed={lr['prompts_changed']}")
                   + (f"; token delta {lr['token_delta']}" if lr.get("present") else "")))
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="100,1000,5000")
    ap.add_argument("--latency", default="5000,20000", help="store sizes for the latency table ('' to skip)")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--labels-only", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "bench" / "live" / "results" / "consolidation_eval"))
    a = ap.parse_args()
    lab = labels_eval()
    if a.labels_only:
        print(json.dumps(lab, indent=1))
        return
    results = []
    for n in [int(x) for x in a.sizes.split(",") if x]:
        t = time.time()
        results.append(run_size(n))
        print(f"size {n}: {time.time() - t:.0f}s", file=sys.stderr, flush=True)
    lat = []
    for n in [int(x) for x in a.latency.split(",") if x]:
        t = time.time()
        lat.append(latency(n, a.reps))
        print(f"latency {n}: {time.time() - t:.0f}s", file=sys.stderr, flush=True)
    md = markdown(results, lat, lab)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out + ".json").write_text(json.dumps({"present": Feature.present(), "sizes": results, "latency": lat,
                                                 "labels": lab}, indent=1, default=str))
    Path(a.out + ".md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
