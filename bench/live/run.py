"""Live Gate 1 benchmark: no plugin vs memcode plugin across sessions, on throwaway repos.

Runs real headless `claude -p` sessions (costs money). NOT run in CI.
Safety: NO permission bypass. Only the tools in ALLOWED are pre-approved, each run is
confined to a fresh temp repo (cwd), with --max-turns and a timeout.

  python3 bench/live/run.py --repeats 1 --model haiku --dry-run   # print plan only
  python3 bench/live/run.py --repeats 2 --model haiku
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from bench.live import metrics  # noqa: E402

ALLOWED = "Read Edit Write Bash(pytest:*) Bash(python3:*) Bash(ls:*) Bash(find:*) Bash(grep:*) Bash(cat:*) Bash(./qa:*) Bash(mv:*) Bash(git mv:*) Bash(mkdir:*)"

BASE = {"app.py": "def add(a, b):\n    return a + b\n",
        "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
        "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"}

# Traps exist only in the user's correction: a competent agent cannot infer them from the repo.
SCENARIOS = [
    {"name": "tests_in_checks", "files": dict(BASE), "trap_regex": r"(^|/)tests/",
     "s1": ["Add a test for add() in app.py.",
            "No - in this repo tests go in checks/, never tests/. Move it there and remember that."],
     "later": "Add a test for add() that checks negative numbers."},
    {"name": "run_via_qa", "files": dict(BASE, **{"test_app.py": "from app import add\n\ndef test_add(three):\n    assert add(1, 2) == three\n"}),
     "trap_regex": r"pytest", "chmod": ["qa"],
     "s1": ["Run the tests and report the result.",
            "No - never call pytest directly here; always run ./qa. Remember that."],
     "later": "Run the tests and report the result."},
]


def claude(cwd: Path, prompt: str, model: str, plugin: bool, resume: str | None = None) -> list[dict]:
    cmd = ["claude", "-p", prompt, "--model", model, "--output-format", "stream-json", "--verbose",
           "--max-turns", "8", "--allowedTools", ALLOWED]
    if plugin:
        cmd += ["--plugin-dir", str(ROOT)]
    if resume:
        cmd += ["--resume", resume]
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)
    return metrics.parse_stream(p.stdout)


def make_repo(sc: dict) -> Path:
    d = Path(tempfile.mkdtemp(prefix="memcode-live-"))
    for n, c in sc["files"].items():
        (d / n).write_text(c)
    for n in sc.get("chmod", ["qa"]):
        (d / n).chmod(0o755)
    for c in (["init", "-q"], ["add", "."], ["-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "i"]):
        subprocess.run(["git", *c], cwd=d, check=True)
    return d


def count_memories(repo: Path) -> int:
    db = repo / ".memcode" / "memory.db"
    if not db.exists():
        return -1
    import sqlite3
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    finally:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.dry_run:
        print(json.dumps({"scenarios": [s["name"] for s in SCENARIOS], "configs": ["none", "memcode"],
                          "repeats": a.repeats, "claude_calls": len(SCENARIOS) * 2 * a.repeats * 4}, indent=1))
        return
    table = {}
    mem_counts: list[int] = []
    for plugin in (False, True):
        runs = []
        for sc in SCENARIOS:
            for _ in range(a.repeats):
                repo = make_repo(sc)
                ev = claude(repo, sc["s1"][0], a.model, plugin)
                sid = metrics.metrics(ev, sc["trap_regex"])["session_id"]
                claude(repo, sc["s1"][1], a.model, plugin, resume=sid)
                if plugin:
                    stored = count_memories(repo)
                    mem_counts.append(stored)
                for _s in (2, 3):
                    runs.append(metrics.metrics(claude(repo, sc["later"], a.model, plugin), sc["trap_regex"]))
        table["memcode" if plugin else "none"] = metrics.summarize(runs)
    print("| config | runs | repeated-mistake rate | explore calls | cost USD |\n|---|---|---|---|---|")
    for k, v in table.items():
        print(f"| {k} | {v['runs']} | {v['trap_rate']:.2f} | {v['explore_calls']:.1f} | {v['cost_usd']:.3f} |")
    print(f"\nmemories stored after session 1 (memcode runs): {mem_counts}")
    print("\nTiny N, one model: directional only, not statistically significant.")


if __name__ == "__main__":
    main()
