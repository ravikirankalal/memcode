"""Live Gate 1 benchmark: nomem vs builtin vs memcode across sessions, on throwaway repos.

Runs real headless `claude -p` sessions (costs money). NOT run in CI.
Safety: NO permission bypass. Only the tools in ALLOWED are pre-approved, each run is
confined to a fresh temp repo (cwd), with --max-turns and a timeout.

Configs
  nomem    CLAUDE_CODE_DISABLE_AUTO_MEMORY=1, no plugin     (floor)
  builtin  Claude Code's own memory (default), no plugin    (the incumbent; Gate 1 baseline)
  claudemd like builtin, but the correction turn also says 'Save this rule to CLAUDE.md.' (a fair incumbent)
  memcode  plugin loaded on top of default built-in memory  (what a real user would run)
  memcode_model   memcode with opt-in model capture (MEMCODE_MODEL_CAPTURE=1); the harness waits for the
                  background capture queue to drain before copying memory to later sessions
  memcode_legacy  same, but MEMCODE_FRAMING=legacy (old all-untrusted framing): an A/B for the pinned-block fix

Later sessions start from a CLEAN copy of the original repo plus only the memory store
(.memcode / CLAUDE.md / auto-memory dir), so code written in session 1 cannot leak the convention.

  python3 bench/live/run.py --dry-run
  python3 bench/live/run.py --repeats 3 --workers 6 --model haiku
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from bench.live import metrics  # noqa: E402

ALLOWED = ("Read Edit Write Bash(pytest:*) Bash(python3:*) Bash(ls:*) Bash(find:*) Bash(grep:*) "
           "Bash(cat:*) Bash(./qa:*) Bash(mv:*) Bash(git mv:*) Bash(mkdir:*) "
           "Bash(git add:*) Bash(git commit:*) Bash(git status:*) Bash(git diff:*) Bash(git log:*)")
CONFIGS = ("nomem", "builtin", "claudemd", "memcode", "memcode_legacy", "memcode_model",
           "claudemd_full", "memcode_retrieval", "memcode_salience", "memcode_split")
PLUGIN = ("memcode", "memcode_legacy", "memcode_model", "memcode_retrieval", "memcode_salience", "memcode_split")

BASE = {"app.py": "def add(a, b):\n    return a + b\n",
        "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
        "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"}
TEST = {"test_app.py": "from app import add\n\ndef test_add(three):\n    assert add(1, 2) == three\n"}

# Every trap exists only in the user's correction: a competent agent cannot infer it from the repo.
# `tuned_on` marks scenarios used while fixing triggers; the rest are untuned (held-out).
SCENARIOS = [
    {"name": "tests_in_checks", "tuned_on": True, "files": dict(BASE), "trap_regex": r"(^|/)tests/",
     "s1": ["Add a test for add() in app.py.",
            "No - in this repo tests go in checks/, never tests/. Move it there and remember that."],
     "later": "Add a test for add() that checks negative numbers."},
    {"name": "run_via_qa", "tuned_on": True, "files": dict(BASE, **TEST), "trap_regex": r"pytest",
     "s1": ["Run the tests and report the result.",
            "No - never call pytest directly here; always run ./qa. Remember that."],
     "later": "Run the tests and report the result."},
    {"name": "logging_not_print", "tuned_on": True,
     "files": dict(BASE, **{"log.py": "import logging\n\nlogger = logging.getLogger('app')\n"}),
     "trap_regex": r"\bprint\(", "trap_on": "content",
     "s1": ["Add a function greet(name) to app.py that reports 'hello <name>' somewhere visible.",
            "No - never use print() in this repo; always use logger from log.py. Fix it and remember that."],
     "later": "Add a function farewell(name) to app.py that reports 'bye <name>' somewhere visible."},
    {"name": "commit_prefix", "tuned_on": True, "files": dict(BASE, **TEST),
     "trap_regex": r"git commit(?!.*PROJ-\d+:)",
     "s1": ["Add a docstring to add() in app.py and commit it.",
            "No - commit messages here must always start with 'PROJ-101: '. Redo the commit and remember that."],
     "later": "Add a docstring to the test in test_app.py and commit it."},
    {"name": "config_not_env", "tuned_on": False, "files": dict(BASE, **{"conf/settings.toml": "[app]\nname = 'demo'\n"}),
     "trap_regex": r"\.env\b",
     "s1": ["Add a DEBUG=false setting for the app.",
            "No - never use .env files here; all settings live in conf/settings.toml. Fix it and remember that."],
     "later": "Add a LOG_LEVEL=info setting for the app."},
    {"name": "import_alias", "tuned_on": False, "files": dict(BASE, **TEST),
     "trap_regex": r"from app import", "trap_on": "content",
     "s1": ["Add a second test to test_app.py for add(0, 0).",
            "No - never write 'from app import ...' here; always 'import app as core' and call core.add. Fix it and remember that."],
     "later": "Add another test to test_app.py for add(-1, 1)."},
]


def claude(cwd: Path, prompt: str, model: str, config: str, resume: str | None = None) -> list[dict]:
    cmd = ["claude", "-p", prompt, "--model", model, "--output-format", "stream-json", "--verbose",
           "--max-turns", "10", "--allowedTools", ALLOWED]
    if config in PLUGIN:
        cmd += ["--plugin-dir", str(ROOT)]
    if resume:
        cmd += ["--resume", resume]
    else:
        # Child processes otherwise inherit the PARENT Claude Code session's id (via the environment), so
        # every run would share one session id and memcode's per-session state would leak between them.
        cmd += ["--session-id", str(uuid.uuid4())]
    # Never inherit memcode switches from the launching shell (a project that enables memcode, e.g. this repo's
    # .claude/settings.json, exports MEMCODE_RETRIEVAL=1); each arm sets exactly the flags it is defined by.
    env = {k: v for k, v in os.environ.items() if not k.startswith("MEMCODE_")}
    if config == "nomem":
        env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    if config == "memcode_legacy":
        env["MEMCODE_FRAMING"] = "legacy"
    if config == "memcode_model":
        env["MEMCODE_MODEL_CAPTURE"] = "1"
    if config in ("memcode_retrieval", "memcode_salience", "memcode_split"):
        env["MEMCODE_RETRIEVAL"] = "1"
    if config == "memcode_split":
        env["MEMCODE_RANK"] = "split"
    if config == "memcode_salience":
        env["MEMCODE_RANK"] = "salience"
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300, env=env)
    except subprocess.TimeoutExpired:
        return []
    return metrics.parse_stream(p.stdout)


def make_repo(sc: dict) -> Path:
    d = Path(tempfile.mkdtemp(prefix="memcode-live-"))
    for n, c in sc["files"].items():
        (d / n).parent.mkdir(parents=True, exist_ok=True)
        (d / n).write_text(c)
    if (d / "qa").exists():
        (d / "qa").chmod(0o755)
    for c in (["init", "-q"], ["add", "."], ["-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "i"]):
        subprocess.run(["git", *c], cwd=d, check=True)
    return d


def memcode_memories(repo: Path) -> int:
    db = repo / ".memcode" / "memory.db"
    if not db.exists():
        return -1
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    finally:
        con.close()


def builtin_memory_written(repo: Path) -> bool:
    """CLAUDE.md in the repo or any file in Claude Code's per-project auto-memory dir."""
    if (repo / "CLAUDE.md").exists():
        return True
    key = str(repo.resolve()).replace("/", "-").replace(".", "-")
    return any(Path(p).is_file() for p in glob.glob(os.path.expanduser(f"~/.claude/projects/{key}/memory/**"), recursive=True))


def automem_dir(repo: Path) -> Path:
    key = str(repo.resolve()).replace("/", "-").replace(".", "-")
    return Path(os.path.expanduser(f"~/.claude/projects/{key}/memory"))


def fresh_with_memory(sc: dict, src: Path, config: str) -> Path:
    """New pristine repo + ONLY the memory carried over from `src` (no session-1 code)."""
    import shutil
    dst = make_repo(sc)
    if config in PLUGIN and (src / ".memcode").exists():
        shutil.copytree(src / ".memcode", dst / ".memcode")
    if config in ("builtin", "claudemd", "claudemd_full") or config in PLUGIN:
        if (src / "CLAUDE.md").exists():
            shutil.copy(src / "CLAUDE.md", dst / "CLAUDE.md")
        a = automem_dir(src)
        if a.exists():
            b = automem_dir(dst)
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(a, b, dirs_exist_ok=True)
    return dst


def teach(repo: Path, sc: dict, model: str, config: str) -> None:
    """Teaching phase. `teach` = list of sessions, each a list of turns (turn 0 = task, later turns =
    user corrections/statements, sent via --resume). Default: sc["s1"] as one session. For the
    `claudemd` arm every turn after the first also says to save the rule to CLAUDE.md."""
    for turns in sc.get("teach") or [sc["s1"]]:
        sid = None
        for i, turn in enumerate(turns):
            prompt = turn + (" Save this rule to CLAUDE.md." if config == "claudemd" and i > 0 else "")
            ev = claude(repo, prompt, model, config, resume=sid)
            if i == 0:
                sid = metrics.metrics(ev, sc["trap_regex"], sc.get("trap_on", "cmd_path"))["session_id"]


def wait_for_capture_queue(repo: Path, timeout_s: float = 240) -> int:
    """Block until the background model-capture worker has drained the queue; returns items left."""
    import time as _t
    db = repo / ".memcode" / "memory.db"
    deadline = _t.time() + timeout_s
    left = 0
    while _t.time() < deadline:
        if not db.exists():
            return 0
        con = sqlite3.connect(db)
        try:
            left = con.execute("SELECT COUNT(*) FROM capture_queue WHERE status IN ('pending','working')").fetchone()[0]
        except sqlite3.OperationalError:
            left = 0
        finally:
            con.close()
        if not left:
            return 0
        _t.sleep(2)
    return left


def run_unit(args: tuple) -> dict:
    sc, config, model = args
    repo = make_repo(sc)
    if "target" in sc:                       # budget-pressure / salience scenario: memory is seeded, not taught
        from bench.live import pressure, salience1_candidates
        if config in PLUGIN:
            (salience1_candidates if "kind" in sc else pressure).seed_store(repo, sc)
        elif config == "claudemd_full":
            pressure.write_claudemd(repo, sc)
        later = [metrics.metrics(claude(fresh_with_memory(sc, repo, config), sc["later"], model, config),
                                 sc["trap_regex"], sc.get("trap_on", "cmd_path"), sc.get("trap_path"))
                 for _ in (2, 3)]
        return {"scenario": sc["name"], "tuned_on": sc.get("tuned_on", False), "config": config,
                "stored": memcode_memories(repo) if config in PLUGIN else None, "builtin_written": None, "later": later}
    teach(repo, sc, model, config)
    if config == "memcode_model":
        wait_for_capture_queue(repo)
    stored = memcode_memories(repo) if config in PLUGIN else None
    builtin = builtin_memory_written(repo) if config != "nomem" else None
    later = [metrics.metrics(claude(fresh_with_memory(sc, repo, config), sc["later"], model, config),
                             sc["trap_regex"], sc.get("trap_on", "cmd_path")) for _ in (2, 3)]
    return {"scenario": sc["name"], "tuned_on": sc["tuned_on"], "config": config,
            "stored": stored, "builtin_written": builtin, "later": later}


def table(results: list[dict], title: str, pick) -> str:
    out = [f"### {title}", "", "| config | runs | repeated-mistake rate | explore calls | cost USD | memory written in session 1 |",
           "|---|---|---|---|---|---|"]
    for cfg in CONFIGS:
        rs = [r for r in results if r["config"] == cfg and pick(r)]
        runs = [m for r in rs for m in r["later"]]
        if not runs:
            continue
        s = metrics.summarize(runs)
        if cfg in PLUGIN:
            wrote = f"{sum(1 for r in rs if (r['stored'] or 0) > 0)}/{len(rs)}"
        elif cfg in ("builtin", "claudemd"):
            wrote = f"{sum(1 for r in rs if r['builtin_written'])}/{len(rs)}"
        else:
            wrote = "n/a"
        out.append(f"| {cfg} | {s['runs']} | {s['trap_rate']:.2f} | {s['explore_calls']:.1f} | {s['cost_usd']:.3f} | {wrote} |")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--scenarios", default="", help="comma-separated scenario names (default: all)")
    ap.add_argument("--set", default="dev", choices=("dev", "heldout", "heldout2", "heldout3", "heldout4", "pressure1", "pressure2", "salience1", "salience2"), help="scenario set")
    ap.add_argument("--configs", default="", help="comma-separated configs (default: all but memcode_legacy)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=str(HERE / "results" / "raw.json"))
    a = ap.parse_args()
    pool = SCENARIOS
    if a.set == "heldout":
        from bench.live.heldout import HELDOUT
        pool = HELDOUT
    elif a.set == "pressure2":
        from bench.live.pressure2 import PRESSURE2
        pool = PRESSURE2
    elif a.set == "salience2":
        from bench.live.salience2_candidates import CANDIDATES as S2   # becomes a frozen set after the pilots
        pool = S2
    elif a.set == "salience1":
        from bench.live.salience1 import SALIENCE1
        pool = SALIENCE1
    elif a.set == "pressure1":
        from bench.live.pressure1 import PRESSURE1
        pool = PRESSURE1
    elif a.set == "heldout4":
        from bench.live.heldout4 import HELDOUT4
        pool = HELDOUT4
    elif a.set == "heldout3":
        from bench.live.heldout3 import HELDOUT3
        pool = HELDOUT3
    elif a.set == "heldout2":
        from bench.live.heldout2 import HELDOUT2
        pool = HELDOUT2
    chosen = [s for s in pool if not a.scenarios or s["name"] in a.scenarios.split(",")]
    cfgs = a.configs.split(",") if a.configs else [c for c in CONFIGS if c not in ("memcode_legacy", "memcode_model")]
    units = [(sc, cfg, a.model) for sc in chosen for cfg in cfgs for _ in range(a.repeats)]
    if a.dry_run:
        print(json.dumps({"scenarios": [s["name"] for s in chosen], "configs": cfgs, "repeats": a.repeats,
                          "units": len(units), "claude_calls": sum(0 if "target" in sc else sum(len(t) for t in (sc.get("teach") or [sc["s1"]]))
                                              for sc, _, _ in units) + len(units) * 2}, indent=1))
        return
    with cf.ThreadPoolExecutor(a.workers) as ex:
        results = list(ex.map(run_unit, units))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(results, indent=1))
    print(table(results, "All scenarios", lambda r: True))
    print()
    print(table(results, "Untuned scenarios only (not used while fixing triggers)", lambda r: not r["tuned_on"]))
    print("\nTiny N, one model: directional only, not statistically significant.")


if __name__ == "__main__":
    main()
