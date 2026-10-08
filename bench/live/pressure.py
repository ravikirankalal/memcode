"""Budget-pressure scenarios: the memory store is already full (~75 memories), the one memory a task needs
is the OLDEST, so the capped session-start pinned block leaves it out. Measures whether the right memory
reaches the agent once ranking/retrieval matters (capture is measured by the other sets, so memories are
seeded directly). Arms: nomem, claudemd_full (every memory in CLAUDE.md, which Claude Code loads whole),
memcode (pinned only), memcode_retrieval (+ per-prompt retrieval), memcode_salience (+ salience ranking).
Retrieval is deterministic, so `offline_check` predicts exactly whether each arm surfaces the target."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

REPO = {
    "README.md": "Demo service.\n",
    "billing/__init__.py": "", "billing/invoice.py": "def total_cents(items):\n    return sum(i['cents'] for i in items)\n",
    "api/__init__.py": "", "api/errors.py": "class ApiError(Exception):\n    pass\n\n\ndef fail(code, msg):\n    raise ApiError(code, msg)\n",
    "api/users.py": "USERS = {}\n",
    "util/__init__.py": "", "util/dates.py": "import datetime\n",
    "worker/__init__.py": "", "worker/log.py": "import logging\n\n\ndef get(name):\n    return logging.getLogger('worker.' + name)\n",
    "tools/__init__.py": "", "tools/sync.py": "import argparse\n\n\ndef main():\n    p = argparse.ArgumentParser()\n    p.add_argument('src')\n    return p.parse_args()\n",
    "search/__init__.py": "", "search/index.py": "def tokens(text):\n    return text.split()\n",
    "reports/__init__.py": "", "reports/weekly.py": "",
    "frontend/app.js": "export const app = {};\n", "docs/index.md": "# Docs\n", "infra/deploy.sh": "#!/bin/sh\n",
    "mobile/App.kt": "class App\n", "data/etl.py": "def run():\n    pass\n", "scripts/release.sh": "#!/bin/sh\n",
}

AREAS = ["frontend", "docs", "infra", "mobile", "data", "scripts", "analytics", "search", "notifications"]
RULE_TEMPLATES = [
    "Components in {a}/ use named exports only, never default exports.",
    "Every change under {a}/ needs a changelog line in {a}/CHANGES.md.",
    "Tests for {a}/ live in {a}/tests and use the shared fixtures module.",
    "Configuration for {a}/ is read from {a}/config.toml, never from environment variables.",
    "Public functions in {a}/ carry a one-line summary docstring.",
]
NOTE_TEMPLATES = [
    "`make {a}-build` failed until the cache directory was cleared; clear it before rebuilding.",
    "Retries of the {a} deploy script needed the --force flag after a lockfile conflict.",
    "The {a} integration tests flaked on slow network; they now use the local stub server.",
    "A revert in the {a} pipeline happened after the schema check was skipped; run the check first.",
    "The {a} linter needed two passes because generated files were not excluded.",
    "Building {a} on a clean machine failed until the toolchain version was pinned.",
    "The {a} release job timed out once; raising the job timeout to 20 minutes fixed it.",
]


def distractors() -> tuple[list[str], list[str]]:
    rules = [t.format(a=a) for a in AREAS for t in RULE_TEMPLATES]          # 45 rules
    notes = [t.format(a=a) for a in AREAS for t in NOTE_TEMPLATES]           # 63 notes
    return rules, notes


CANDIDATES = [
    {"name": "p_billing_header", "target": ("correction", "Every new module under billing/ starts with the exact line '# PCI-SCOPE'.", ""),
     "later": "Create billing/refunds.py with a function refund(amount_cents, reason) that returns a refund record.",
     "trap_regex": r"\A(?!# PCI-SCOPE)", "trap_on": "content", "trap_path": r"(^|/)billing/",
     "oracle": "Rule: every new module under billing/ starts with the exact line '# PCI-SCOPE'."},
    {"name": "p_api_fail", "target": ("correction", "Handlers in api/ report errors by calling api.errors.fail(code, msg); never raise exceptions directly.", ""),
     "later": "Add a handler get_user(user_id) to api/users.py that returns the user or reports a not-found error.",
     "trap_regex": r"\braise\b|HTTPException|\A(?!.*\bfail\()", "trap_on": "content", "trap_path": r"(^|/)api/users\.py$",
     "oracle": "Rule: handlers in api/ report errors by calling api.errors.fail(code, msg) and never raise exceptions directly."},
    {"name": "p_dates_utc", "target": ("fail_to_fix", "naive datetime.now() broke the timezone tests in util/dates.py; always use datetime.now(datetime.timezone.utc).", "util/dates.py"),
     "later": "Add a function stamp() to util/dates.py that returns the current time as an ISO 8601 string.",
     "trap_regex": r"datetime\.now\(\s*\)|utcnow\(", "trap_on": "content", "trap_path": r"(^|/)util/dates\.py$",
     "oracle": "Note: naive datetime.now() broke the timezone tests; use datetime.now(datetime.timezone.utc)."},
    {"name": "p_worker_logger", "target": ("correction", "Modules under worker/ get their logger from worker.log.get(__name__), never from logging.getLogger.", ""),
     "later": "Create worker/retry.py with a function retry(fn, attempts) that logs each failed attempt.",
     "trap_regex": r"logging\.getLogger|\bprint\(|\A(?!.*log\.get\()", "trap_on": "content", "trap_path": r"(^|/)worker/",
     "oracle": "Rule: modules under worker/ get their logger from worker.log.get(__name__), never logging.getLogger."},
    {"name": "p_tools_flags", "target": ("correction", "Command-line options in tools/ are spelled as one lowercase word without dashes inside, like --dryrun or --nocache.", ""),
     "later": "Add an option to tools/sync.py that makes it skip writing any files (a dry run).",
     "trap_regex": r"--dry[-_]run", "trap_on": "content", "trap_path": r"(^|/)tools/sync\.py$",
     "oracle": "Rule: command-line options in tools/ are one lowercase word without inner dashes, e.g. --dryrun."},
]


# Added after the first pilot: conventions that cannot be inferred from the repo (the pilot showed that
# repo-visible conventions such as an existing api/errors.fail() are discovered without any memory).
CANDIDATES += [
    {"name": "p_data_all", "target": ("correction", "Every new module under data/ ends with an __all__ list naming its public functions.", ""),
     "later": "Create data/clean.py with a function drop_empty(rows) that removes rows whose values are all empty.",
     "trap_regex": r"\A(?!.*__all__)", "trap_on": "content", "trap_path": r"(^|/)data/",
     "oracle": "Rule: every new module under data/ ends with an __all__ list naming its public functions."},
    {"name": "p_search_suffix", "target": ("correction", "Functions defined in search/ are named with a _q suffix, for example rank_q or tokens_q.", ""),
     "later": "Add a function to search/index.py that lowercases a query and strips punctuation.",
     "trap_regex": r"def (?!\w*_q\()(?!tokens\()\w+\(", "trap_on": "content", "trap_path": r"(^|/)search/",
     "oracle": "Rule: functions defined in search/ are named with a _q suffix, e.g. normalize_q."},
    {"name": "p_reports_ctx", "target": ("correction", "Every function in reports/ takes ctx as its first parameter.", ""),
     "later": "Add a function to reports/weekly.py that builds a weekly summary dict from a list of orders.",
     "trap_regex": r"def \w+\((?!\s*ctx\b)", "trap_on": "content", "trap_path": r"(^|/)reports/",
     "oracle": "Rule: every function in reports/ takes ctx as its first parameter."},
]


def seed_store(repo: Path, sc: dict) -> int:
    """Seed .memcode with the distractors (newer) and the target (oldest). Returns the target id."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from memcode import store
    con = store.connect(repo)
    rules, notes = distractors()
    t0 = time.time() - 90 * 86400
    trig, text, anchor = sc["target"]
    body = f"Rule from user correction: {text}" if trig == "correction" else text
    tid = store.add_memory(con, trig, body, anchor, None, {"source": "seed"}, 0.6)
    con.execute("UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (t0, t0, tid))
    for i, r in enumerate(rules):
        mid = store.add_memory(con, "correction", f"Rule from user correction: {r}", "", None, {"source": "seed"}, 0.6)
        con.execute("UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (t0 + 3600 * (i + 1),) * 2 + (mid,))
    for i, n in enumerate(notes):
        mid = store.add_memory(con, "retry", n, "", None, {"source": "seed"}, 0.6)
        con.execute("UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (t0 + 3600 * (i + 100),) * 2 + (mid,))
    con.commit()
    con.close()
    return tid


def write_claudemd(repo: Path, sc: dict) -> None:
    rules, notes = distractors()
    trig, text, _ = sc["target"]
    lines = ["# Project memory", "", "## Rules"] + [f"- {r}" for r in ([text] if trig == "correction" else []) + rules]
    lines += ["", "## Notes"] + [f"- {n}" for n in ([text] if trig != "correction" else []) + notes]
    (repo / "CLAUDE.md").write_text("\n".join(lines) + "\n")


def offline_check(sc: dict) -> dict:
    """Deterministic: is the target in the pinned block, and does retrieval (relevance / salience) surface it?"""
    import os
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from memcode import pinned, retrieval, store, tree
    out = {}
    for arm, env in (("relevance", {}), ("salience", {"MEMCODE_RANK": "salience"})):
        d = Path(tempfile.mkdtemp())
        for n, c in REPO.items():
            (d / n).parent.mkdir(parents=True, exist_ok=True)
            (d / n).write_text(c)
        tid = seed_store(d, sc)
        con = store.connect(d)
        tree.scan_repo(con, d); tree.mark_stale(con, d)
        text = pinned.render_pinned(con, d)
        shown = pinned.shown_ids(con, text)
        con.executemany("INSERT INTO injections(session,memory_id,ts) VALUES('s',?,0)", [(i,) for i in shown])
        con.commit()
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            scored = retrieval.score(con, str(d), "s", sc["later"])
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        _, ids = retrieval.render(scored)
        out["target_pinned"] = tid in shown
        out[f"retrieved_{arm}"] = tid in ids
        out[f"rank_{arm}"] = next((i for i, (_, r) in enumerate(scored) if r["id"] == tid), None)
        out["memories"] = con.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        con.close()
    return out


if __name__ == "__main__":
    for sc in CANDIDATES:
        print(sc["name"], json.dumps(offline_check(sc)))
