"""Live Gate 1 benchmark: nomem vs builtin vs memcode across sessions, on throwaway repos.

Runs real headless `claude -p` sessions (costs money). NOT run in CI.
Safety: NO permission bypass. Only the tools in ALLOWED are pre-approved, each run is
confined to a fresh temp repo (cwd), with --max-turns and a timeout.

Configs
  nomem    CLAUDE_CODE_DISABLE_AUTO_MEMORY=1, no plugin     (floor)
  builtin  Claude Code's own memory (default), no plugin    (the incumbent; Gate 1 baseline)
  claudemd like builtin, but the correction turn also says 'Save this rule to CLAUDE.md.' (a fair incumbent)
  memcode  plugin loaded on top of default built-in memory  (what a real user would run)
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
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from bench.live import metrics  # noqa: E402

ALLOWED = ("Read Edit Write Bash(pytest:*) Bash(python3:*) Bash(ls:*) Bash(find:*) Bash(grep:*) "
           "Bash(cat:*) Bash(./qa:*) Bash(mv:*) Bash(git mv:*) Bash(mkdir:*) "
           "Bash(git add:*) Bash(git commit:*) Bash(git status:*) Bash(git diff:*) Bash(git log:*)")
CONFIGS = ("nomem", "builtin", "claudemd", "memcode", "memcode_legacy")
PLUGIN = ("memcode", "memcode_legacy")

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
    env = dict(os.environ)
    if config == "nomem":
        env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    if config == "memcode_legacy":
        env["MEMCODE_FRAMING"] = "legacy"
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
    if config in ("builtin", "claudemd", "memcode", "memcode_legacy"):
        if (src / "CLAUDE.md").exists():
            shutil.copy(src / "CLAUDE.md", dst / "CLAUDE.md")
        a = automem_dir(src)
        if a.exists():
            b = automem_dir(dst)
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(a, b, dirs_exist_ok=True)
    return dst


def run_unit(args: tuple) -> dict:
    sc, config, model = args
    repo = make_repo(sc)
    ev = claude(repo, sc["s1"][0], model, config)
    sid = metrics.metrics(ev, sc["trap_regex"], sc.get("trap_on", "cmd_path"))["session_id"]
    fix = sc["s1"][1] + (" Save this rule to CLAUDE.md." if config == "claudemd" else "")
    claude(repo, sc["s1"][1] if config != "claudemd" else fix, model, config, resume=sid)
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
    ap.add_argument("--set", default="dev", choices=("dev", "heldout", "heldout2"), help="scenario set")
    ap.add_argument("--configs", default="", help="comma-separated configs (default: all but memcode_legacy)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=str(HERE / "results" / "raw.json"))
    a = ap.parse_args()
    pool = SCENARIOS
    if a.set == "heldout":
        from bench.live.heldout import HELDOUT
        pool = HELDOUT
    elif a.set == "heldout2":
        from bench.live.heldout2 import HELDOUT2
        pool = HELDOUT2
    chosen = [s for s in pool if not a.scenarios or s["name"] in a.scenarios.split(",")]
    cfgs = a.configs.split(",") if a.configs else [c for c in CONFIGS if c != "memcode_legacy"]
    units = [(sc, cfg, a.model) for sc in chosen for cfg in cfgs for _ in range(a.repeats)]
    if a.dry_run:
        print(json.dumps({"scenarios": [s["name"] for s in chosen], "configs": cfgs, "repeats": a.repeats,
                          "units": len(units), "claude_calls": len(units) * 4}, indent=1))
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
