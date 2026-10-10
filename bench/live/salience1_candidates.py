"""Gate 2 candidates (salience1): does salience ranking beat recency when relevant memories compete for slots?

Each scenario has one task directory and SEVEN memories that are all relevant to the task (rules about that
directory), more than retrieval's TOP_K=5, plus pressure2-style distractors in synthetic directories (newer, so the
session-start block is full of them). Only one of the seven is needed to pass the judged trap.

kind "costly":  the needed rule is the oldest of the seven, and the user had to RESTATE it in two later sessions
                (outcomes 'failure:repeated'; a restatement never touches updated_at, so recency still sees it as
                old). This is the case salience exists for.
kind "control": the needed rule is a cheap, mid-aged one, and three OTHER relevant rules carry restatements.
                This measures what salience costs when the expensive memories are not the ones needed.

Arms: nomem, memcode_retrieval (relevance, ties broken by recency), memcode_salience (relevance x (1 + salience)).
`offline_check` is deterministic and predicts, before any model run, whether each arm puts the needed rule in front
of the agent (pinned block or per-prompt retrieval).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from bench.live.pressure import REPO, scaled_distractors   # noqa: E402

DAY = 86400.0
N_RULES, N_NOTES = 40, 60

CANDIDATES = [
    {"name": "s_billing_header", "kind": "costly", "dir": "billing",
     "target": "Every new module under billing/ starts with the exact line '# PCI-SCOPE'.",
     "competitors": [
         "Money amounts in billing/ are integers in cents, never floats.",
         "Functions in billing/ carry full type hints on parameters and return values.",
         "Modules in billing/ keep no module-level mutable state.",
         "Docstrings in billing/ name the currency the function assumes.",
         "Functions in billing/ stay under 40 lines; split helpers out instead.",
         "Records returned from billing/ functions are plain dicts with snake_case keys.",
     ],
     "later": "Create billing/refunds.py with a function refund(amount_cents, reason) that returns a refund record.",
     "trap_regex": r"\A(?!# PCI-SCOPE)", "trap_on": "content", "trap_path": r"(^|/)billing/refunds\.py$",
     "oracle": "Rule: every new module under billing/ starts with the exact line '# PCI-SCOPE'."},
    {"name": "s_data_all", "kind": "costly", "dir": "data",
     "target": "Every new module under data/ ends with an __all__ list naming its public functions.",
     "competitors": [
         "Functions in data/ take rows as a list of dicts and never mutate their input.",
         "Modules in data/ import only from the standard library.",
         "Functions in data/ carry type hints on parameters and return values.",
         "Public functions in data/ have a one-line docstring.",
         "Empty values in data/ rows are None or the empty string, nothing else.",
         "Helpers in data/ that are not public start with an underscore.",
     ],
     "later": "Create data/clean.py with a function drop_empty(rows) that removes rows whose values are all empty.",
     "trap_regex": r"\A(?!.*__all__)", "trap_on": "content", "trap_path": r"(^|/)data/clean\.py$",
     "oracle": "Rule: every new module under data/ ends with an __all__ list naming its public functions."},
    {"name": "s_search_suffix", "kind": "costly", "dir": "search",
     "target": "Functions defined in search/ are named with a _q suffix, for example rank_q or tokens_q.",
     "competitors": [
         "Text handling in search/ works on str only, never bytes.",
         "Functions in search/ are pure: no I/O and no global state.",
         "Functions in search/ carry type hints on parameters and return values.",
         "Public functions in search/ have a one-line docstring with an example query.",
         "Regular expressions in search/ are compiled once at module level.",
         "Functions in search/ return new strings and lists rather than modifying arguments.",
     ],
     "later": "Add a function to search/index.py that lowercases a query and strips punctuation.",
     "trap_regex": r"def (?!\w*_q\()(?!tokens\()\w+\(", "trap_on": "content", "trap_path": r"(^|/)search/index\.py$",
     "oracle": "Rule: functions defined in search/ are named with a _q suffix, e.g. normalize_q."},
    {"name": "s_reports_ctx", "kind": "costly", "dir": "reports",
     "target": "Every function in reports/ takes ctx as its first parameter.",
     "competitors": [
         "Summaries built in reports/ are plain dicts with snake_case keys.",
         "Functions in reports/ carry type hints on parameters and return values.",
         "Money in reports/ is summed as integer cents, never floats.",
         "Public functions in reports/ have a one-line docstring.",
         "Functions in reports/ never print; they return data for the caller to render.",
         "Date ranges in reports/ are half-open: start inclusive, end exclusive.",
     ],
     "later": "Add a function to reports/weekly.py that builds a weekly summary dict from a list of orders.",
     "trap_regex": r"def \w+\((?!\s*ctx\b)", "trap_on": "content", "trap_path": r"(^|/)reports/weekly\.py$",
     "oracle": "Rule: every function in reports/ takes ctx as its first parameter."},
    {"name": "c_tools_flags", "kind": "control", "dir": "tools",
     "target": "Command-line options in tools/ are spelled as one lowercase word without dashes inside, like --dryrun or --nocache.",
     "competitors": [
         "Scripts in tools/ exit with status 2 on bad arguments and 1 on runtime errors.",
         "Scripts in tools/ print progress to stderr and results to stdout.",
         "Functions in tools/ carry type hints on parameters and return values.",
         "Every script in tools/ has a module docstring describing its usage.",
         "Paths in tools/ are handled with pathlib, never os.path string joins.",
         "Scripts in tools/ keep argument parsing inside main().",
     ],
     "later": "Add an option to tools/sync.py that makes it skip writing any files (a dry run).",
     "trap_regex": r"--dry[-_]run", "trap_on": "content", "trap_path": r"(^|/)tools/sync\.py$",
     "oracle": "Rule: command-line options in tools/ are one lowercase word without inner dashes, e.g. --dryrun."},
    {"name": "c_worker_logger", "kind": "control", "dir": "worker",
     "target": "Modules under worker/ get their logger from worker.log.get(__name__), never from logging.getLogger.",
     "competitors": [
         "Functions in worker/ never sleep in a loop without a maximum attempt count.",
         "Functions in worker/ carry type hints on parameters and return values.",
         "Exceptions in worker/ are re-raised after logging, never swallowed.",
         "Public functions in worker/ have a one-line docstring.",
         "Modules in worker/ keep no module-level mutable state.",
         "Retry delays in worker/ grow exponentially and are capped at 30 seconds.",
     ],
     "later": "Create worker/retry.py with a function retry(fn, attempts) that logs each failed attempt.",
     "trap_regex": r"logging\.getLogger|\bprint\(|\A(?!.*log\.get\()", "trap_on": "content", "trap_path": r"(^|/)worker/retry\.py$",
     "oracle": "Rule: modules under worker/ get their logger from worker.log.get(__name__), never logging.getLogger."},
]

# Ages in days. costly: target is the oldest, restated by the user 20 and 6 days ago.
COSTLY_TARGET_AGE = 45
COMPETITOR_AGES = [30, 25, 18, 12, 8, 4]
REPEAT_AGES = [20, 6]
# control: target sits mid-pack (recency rank 4 of 7); three competitors carry two restatements each.
CONTROL_TARGET_AGE = 10
CONTROL_REPEATED = [0, 1, 2]          # indexes into competitors (the three oldest)


def history(sc: dict) -> list[dict]:
    """The seven relevant memories: [{text, age, repeats: [ages], needed}]."""
    comps = [{"text": t, "age": a, "repeats": [], "needed": False}
             for t, a in zip(sc["competitors"], COMPETITOR_AGES)]
    if sc["kind"] == "costly":
        tgt = {"text": sc["target"], "age": COSTLY_TARGET_AGE, "repeats": list(REPEAT_AGES), "needed": True}
    else:
        tgt = {"text": sc["target"], "age": CONTROL_TARGET_AGE, "repeats": [], "needed": True}
        for i in CONTROL_REPEATED:
            comps[i]["repeats"] = list(REPEAT_AGES)
    return [tgt] + comps


def seed_store(repo: Path, sc: dict, now: float | None = None) -> int:
    """Seed .memcode: distractors (newest), the seven relevant rules with their ages, and restatements recorded as
    outcomes. Returns the needed rule's id."""
    from memcode import store
    now = time.time() if now is None else now
    con = store.connect(repo)
    tid = None
    for i, h in enumerate(history(sc)):
        ts = now - h["age"] * DAY
        mid = store.add_memory(con, "correction", f"Rule from user correction: {h['text']}", "", None,
                               {"source": "seed"}, 0.6, commit=False)
        con.execute("UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (ts, ts, mid))
        for j, ra in enumerate(h["repeats"]):
            con.execute("INSERT INTO outcomes(session,memory_id,outcome,ts) VALUES(?,?,?,?)",
                        (f"hist-{i}-{j}", mid, "failure:repeated", now - ra * DAY))
        if h["needed"]:
            tid = mid
    rules, notes = scaled_distractors(N_RULES, N_NOTES)
    for i, r in enumerate(rules):
        ts = now - 3 * DAY + 3600 * i
        mid = store.add_memory(con, "correction", f"Rule from user correction: {r}", "", None, {"source": "seed"}, 0.6,
                               commit=False)
        con.execute("UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (ts, ts, mid))
    for i, n in enumerate(notes):
        ts = now - 2 * DAY + 1800 * i
        mid = store.add_memory(con, "retry", n, "", None, {"source": "seed"}, 0.6, commit=False)
        con.execute("UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (ts, ts, mid))
    con.commit()
    con.close()
    return tid


def write_files(repo: Path, sc: dict) -> None:
    for n, c in sc.get("files", REPO).items():
        (repo / n).parent.mkdir(parents=True, exist_ok=True)
        (repo / n).write_text(c)


def offline_check(sc: dict) -> dict:
    """Deterministic: does each arm surface the needed rule (pinned block or retrieval), and at what rank?"""
    from memcode import pinned, retrieval, store, tree
    out = {"kind": sc["kind"]}
    for arm, env in (("relevance", {}), ("salience", {"MEMCODE_RANK": "salience"})):
        old = {k: os.environ.get(k) for k in ("MEMCODE_RANK",)}
        os.environ.pop("MEMCODE_RANK", None)
        os.environ.update(env)
        try:
            d = Path(tempfile.mkdtemp())
            write_files(d, sc)
            tid = seed_store(d, sc)
            con = store.connect(d)
            tree.scan_repo(con, d); tree.mark_stale(con, d)
            text = pinned.render_pinned(con, d)
            shown = pinned.shown_ids(con, text)
            con.executemany("INSERT INTO injections(session,memory_id,ts) VALUES('s',?,0)", [(i,) for i in shown])
            con.commit()
            scored = retrieval.score(con, str(d), "s", sc["later"])
            _, ids = retrieval.render(scored)
            relevant = {r["id"] for _, r in scored if sc["dir"] + "/" in r["text"]}
            out[f"{arm}_pinned"] = tid in shown
            out[f"{arm}_retrieved"] = tid in ids
            out[f"{arm}_surfaced"] = tid in shown or tid in ids
            out[f"{arm}_rank"] = next((i for i, (_, r) in enumerate(scored) if r["id"] == tid), None)
            out[f"{arm}_relevant_scored"] = len(relevant)
            out[f"{arm}_injected"] = len(ids)
            con.close()
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    return out


if __name__ == "__main__":
    for sc in CANDIDATES:
        print(sc["name"], json.dumps(offline_check(sc)))
