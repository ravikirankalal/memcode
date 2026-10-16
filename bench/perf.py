"""Runtime performance: how much latency do memcode's hooks add to an agent turn, and how does it scale?

Times the REAL hook entrypoint (a fresh `python3 -m memcode.hook_cli` subprocess per call, as the agent runs it, so
interpreter start-up is included) on synthetic git repos and seeded stores:

  files     tracked files in the repo (scan, hash, staleness)
  memories  stored memories (mix: 20% user rules, 50% anchored fail-to-fix notes, 30% retry notes; 5% of rules
            restated, so split ranking has promotion candidates)

Events timed per config (retrieval on, default split ranking):
  start_cold   first SessionStart on a fresh clone of the store (full scan + hash of every file)
  start_warm   SessionStart again (nothing changed: stat only)
  prompt       UserPromptSubmit naming a file (capture + per-prompt retrieval)
  tool_bash    PostToolUse for a shell command
  tool_edit    PostToolUse for a file edit
  mcp_search   one memory_search call through the MCP server (process start included)

  python3 bench/perf.py                       # default matrix
  python3 bench/perf.py --files 100,2000 --memories 0,1000 --reps 5
Costs no model calls. Results: bench/live/results/perf.json (git-ignored).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from memcode import store  # noqa: E402

DAY = 86400.0


def make_repo(n_files: int) -> Path:
    d = Path(tempfile.mkdtemp(prefix="memcode-perf-"))
    rnd = random.Random(n_files)
    dirs = [f"pkg{i}/mod{j}" for i in range(max(1, n_files // 200)) for j in range(4)]
    for k in range(n_files):
        p = d / dirs[k % len(dirs)] / f"file_{k}.py"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"def f{k}(x):\n    return x + {rnd.randint(0, 999)}\n" + "# padding\n" * rnd.randint(5, 60))
    for c in (["init", "-q"], ["add", "."], ["-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "i"]):
        subprocess.run(["git", *c], cwd=d, check=True)
    return d


def seed(repo: Path, n_mem: int) -> list[str]:
    files = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True, text=True).stdout.split()
    con = store.connect(repo)
    now = time.time()
    rnd = random.Random(n_mem)
    for i in range(n_mem):
        r = rnd.random()
        f = files[rnd.randrange(len(files))]
        if r < 0.2:
            mid = store.add_memory(con, "correction", f"Rule from user correction: In {f.rsplit('/', 1)[0]}/ "
                                   f"always follow convention number {i} for naming.", "", None, {}, 0.6, commit=False)
            if rnd.random() < 0.05:
                con.execute("INSERT INTO outcomes VALUES(?,?,?,?)", (f"h{i}", mid, "failure:repeated",
                                                                     now - rnd.uniform(0, 20) * DAY))
        elif r < 0.7:
            mid = store.add_memory(con, "fail_to_fix", f"`pytest -q` failed and passed after editing {f}. Fix was "
                                   f"in {f}.", f, None, {}, 0.7, commit=False)
        else:
            mid = store.add_memory(con, "retry", f"Command `make build-{i % 50}` needed multiple attempts", "",
                                   None, {}, 0.5, commit=False)
        ts = now - rnd.uniform(0, 90) * DAY
        con.execute("UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (ts, ts, mid))
    con.commit()
    con.close()
    return files


def env_for(repo: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("MEMCODE_") and k != "CLAUDE_PROJECT_DIR"}
    env.update(PYTHONPATH=str(ROOT), MEMCODE_RETRIEVAL="1")
    return env


def run_hook(repo: Path, event: str, payload: dict) -> float:
    t = time.perf_counter()
    p = subprocess.run([sys.executable, "-m", "memcode.hook_cli", event], env=env_for(repo), text=True,
                       capture_output=True, input=json.dumps(dict(payload, cwd=str(repo))))
    dt = (time.perf_counter() - t) * 1000
    if p.returncode != 0 or "memcode:" in p.stderr:
        raise RuntimeError(f"{event} failed: {p.stderr[-500:]}")
    return dt


def run_mcp(repo: Path, query: str) -> float:
    msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": "memory_search", "arguments": {"query": query}}}) + "\n"
    t = time.perf_counter()
    subprocess.run([sys.executable, "-m", "memcode.mcp_server"], env=dict(env_for(repo), CLAUDE_PROJECT_DIR=str(repo)),
                   input=msg, text=True, capture_output=True, check=True)
    return (time.perf_counter() - t) * 1000


def baseline() -> float:
    """Bare interpreter start-up, for reference: memcode's own cost is roughly (event - baseline)."""
    t = time.perf_counter()
    subprocess.run([sys.executable, "-c", "pass"], check=True)
    return (time.perf_counter() - t) * 1000


def stats(xs: list[float]) -> dict:
    xs = sorted(xs)
    return {"median_ms": round(statistics.median(xs), 1), "p95_ms": round(xs[min(len(xs) - 1, int(0.95 * len(xs)))], 1),
            "n": len(xs)}


def bench_config(n_files: int, n_mem: int, reps: int, repo_cache: dict) -> dict:
    if n_files not in repo_cache:
        repo_cache[n_files] = make_repo(n_files)
    template = repo_cache[n_files]
    out = {"files": n_files, "memories": n_mem}
    times: dict[str, list[float]] = {k: [] for k in ("start_cold", "start_warm", "prompt", "tool_bash", "tool_edit",
                                                     "mcp_search")}
    seeded = Path(tempfile.mkdtemp(prefix="memcode-perf-seed-")) / "r"
    shutil.copytree(template, seeded, symlinks=True)
    files = seed(seeded, n_mem)
    target = files[len(files) // 2]
    for i in range(reps):
        repo = Path(tempfile.mkdtemp(prefix="memcode-perf-run-")) / "r"
        shutil.copytree(seeded, repo, symlinks=True)               # fresh store state each rep
        sid = f"s{i}"
        times["start_cold"].append(run_hook(repo, "SessionStart", {"session_id": sid, "source": "startup"}))
        times["start_warm"].append(run_hook(repo, "SessionStart", {"session_id": sid + "w", "source": "resume"}))
        times["prompt"].append(run_hook(repo, "UserPromptSubmit", {
            "session_id": sid, "prompt": f"Fix the failing test in {target} and keep the naming convention"}))
        times["tool_bash"].append(run_hook(repo, "PostToolUse", {
            "session_id": sid, "tool_name": "Bash", "tool_input": {"command": "pytest -q"},
            "tool_response": {"stdout": "1 passed", "exit_code": 0}}))
        times["tool_edit"].append(run_hook(repo, "PostToolUse", {
            "session_id": sid, "tool_name": "Edit", "tool_input": {"file_path": str(repo / target),
                                                                   "old_string": "x", "new_string": "y"},
            "tool_response": {"success": True}}))
        times["mcp_search"].append(run_mcp(repo, "pytest failed"))
        shutil.rmtree(repo.parent, ignore_errors=True)
    shutil.rmtree(seeded.parent, ignore_errors=True)
    out.update({k: stats(v) for k, v in times.items()})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", default="100,2000,10000")
    ap.add_argument("--memories", default="0,300,3000,20000")
    ap.add_argument("--reps", type=int, default=7)
    ap.add_argument("--out", default=str(ROOT / "bench" / "live" / "results" / "perf.json"))
    a = ap.parse_args()
    base = stats([baseline() for _ in range(10)])
    cache: dict = {}
    rows = []
    for nf in [int(x) for x in a.files.split(",")]:
        for nm in [int(x) for x in a.memories.split(",")]:
            t = time.time()
            r = bench_config(nf, nm, a.reps, cache)
            rows.append(r)
            print(f"files={nf:6d} memories={nm:6d}  " + "  ".join(
                f"{k}={r[k]['median_ms']:.0f}/{r[k]['p95_ms']:.0f}" for k in
                ("start_cold", "start_warm", "prompt", "tool_bash", "tool_edit", "mcp_search"))
                  + f"   ({time.time() - t:.0f}s)", flush=True)
    for d in cache.values():
        shutil.rmtree(d, ignore_errors=True)
    res = {"python_startup": base, "rows": rows, "python": sys.version.split()[0],
           "note": "median/p95 ms per hook call, fresh subprocess each call"}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1))
    print(f"\npython start-up alone: {base['median_ms']} ms median. Written {a.out}")


if __name__ == "__main__":
    main()
