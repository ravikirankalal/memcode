"""Runner for the realistic multi-session benchmark e2e1 (a week on the `shelf` project). Costs money; NOT run in CI.

  python3 bench/live/e2e_run.py --dry-run
  python3 bench/live/e2e_run.py --pilot nomem --repeats 3            # later sessions only, no memory
  python3 bench/live/e2e_run.py --pilot oracle --repeats 2           # later sessions, rules+facts in the prompt
  python3 bench/live/e2e_run.py --arms nomem,builtin,claudemd,memcode --repeats 3 --plugin-ref <git ref>

Arms (same definitions as bench/live/run.py; every arm strips inherited MEMCODE_* variables):
  nomem     CLAUDE_CODE_DISABLE_AUTO_MEMORY=1, no plugin
  builtin   Claude Code default memory, no plugin
  claudemd  like builtin, and every turn that states a convention also says "Save this rule to CLAUDE.md."
  memcode   plugin on top of default memory, default config plus MEMCODE_RETRIEVAL=1

Repo state (the design choice, see e2e1.py): every session, teaching or measured, starts from the CANONICAL repo of
that day (starter + the merged code of earlier days, identical for all arms) plus ONLY the memory the arm carried
from the previous session (.memcode / CLAUDE.md / auto-memory dir, via run.fresh_with_memory). Measured later
sessions all start from the memory as it stood after the last teaching session. Conventions are judged on the
final content of the exact NEW files the task asks for, plus CHANGES.md; execution facts from the transcript.

Safety: no permission bypass; only ALLOWED tools are pre-approved; each session is confined to a fresh temp repo,
with --max-turns and a timeout.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from bench.live import metrics, run  # noqa: E402
from bench.live import e2e1_project as P  # noqa: E402

ALLOWED = ("Read Edit Write Glob Grep "
           "Bash(python3:*) Bash(python:*) Bash(pytest:*) Bash(make:*) Bash(tox:*) Bash(shelf:*) "
           "Bash(ls:*) Bash(find:*) Bash(grep:*) Bash(cat:*) Bash(head:*) Bash(tail:*) Bash(wc:*) "
           "Bash(mkdir:*) Bash(mv:*) Bash(cp:*) Bash(touch:*) "
           "Bash(git status:*) Bash(git diff:*) Bash(git log:*) Bash(git show:*) Bash(git add:*) Bash(git commit:*)")
ARMS = ("nomem", "builtin", "claudemd", "memcode")
MAX_TURNS = 40
TIMEOUT_S = 900
RAW_DIR: Path | None = None          # set by main(): raw stream-json of every turn, gzipped, for audits


def load_spec(name: str) -> dict:
    if name == "candidates":
        from bench.live import e2e1_candidates as S
    else:
        from bench.live import e2e1 as S
    return {"conventions": S.CONVENTIONS, "facts": S.FACTS, "teach": S.TEACH, "later": S.LATER,
            "judge": S.JUDGE, "oracle": S.ORACLE, "keys": S.KEYS}


def env_for(arm: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("MEMCODE_")}
    env["MEMCODE_HIER"] = "0"            # e2e1 was frozen against 0.7.0 behaviour (hierarchy off)
    if arm in ("nomem", "oracle"):
        env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    if arm == "memcode":
        env["MEMCODE_RETRIEVAL"] = "1"
    return env


def claude(cwd: Path, prompt: str, model: str, arm: str, plugin_dir: Path, resume: str | None = None) -> tuple[list, float]:
    """One headless turn. Same safety and env rules as run.claude, with a larger turn budget for realistic tasks."""
    cmd = ["claude", "-p", prompt, "--model", model, "--output-format", "stream-json", "--verbose",
           "--max-turns", str(MAX_TURNS), "--allowedTools", ALLOWED]
    if arm == "memcode":
        cmd += ["--plugin-dir", str(plugin_dir)]
    cmd += ["--resume", resume] if resume else ["--session-id", str(uuid.uuid4())]
    t0 = time.perf_counter()
    waited = 0
    while True:
        try:
            p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT_S, env=env_for(arm))
            out = p.stdout
        except subprocess.TimeoutExpired as e:
            out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        if not _rate_limited(out) or waited >= LIMIT_WAIT_S:
            break
        # a usage limit answers instantly at $0 and would be scored as an agent that did nothing: wait, then retry
        pause = min(900, 60 * 2 ** min(4, waited // 600))
        print(f"[e2e] usage limit ({arm}); retrying in {pause}s", file=sys.stderr, flush=True)
        time.sleep(pause)
        waited += pause
        t0 = time.perf_counter()
    if RAW_DIR:
        import gzip
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        with gzip.open(RAW_DIR / f"{arm}-{cwd.name}-{uuid.uuid4().hex[:8]}.jsonl.gz", "wt") as fh:
            fh.write(out)
    return metrics.parse_stream(out), time.perf_counter() - t0


LIMIT_WAIT_S = run.LIMIT_WAIT_S


def _rate_limited(out: str) -> bool:
    return run.rate_limited(metrics.parse_stream(out))


# ---------------------------------------------------------------- transcript metrics

def _blocks(events: list, etype: str):
    for e in events:
        if e.get("type") != etype:
            continue
        c = (e.get("message") or {}).get("content")
        for b in c if isinstance(c, list) else []:
            if isinstance(b, dict):
                yield e, b


def bash_runs(events: list) -> list[dict]:
    """[{cmd, error, exit, output}] for every Bash call, in order (main agent and subagents)."""
    res = {}
    for _, b in _blocks(events, "user"):
        if b.get("type") == "tool_result":
            v = b.get("content")
            text = v if isinstance(v, str) else " ".join(x.get("text", "") for x in v or [] if isinstance(x, dict))
            res[b.get("tool_use_id")] = (bool(b.get("is_error")), text or "")
    out = []
    for _, b in _blocks(events, "assistant"):
        if b.get("type") == "tool_use" and b.get("name") == "Bash":
            err, text = res.get(b.get("id"), (None, ""))
            m = re.match(r"\s*Exit code (\d+)", text)
            code = int(m.group(1)) if m else (None if err is None else (1 if err else 0))
            out.append({"cmd": (b.get("input") or {}).get("command", ""), "error": err, "exit": code,
                        "output": text[:400]})
    return out


def injected(events: list) -> dict:
    """memcode's hook output in this session: SessionStart block and per-prompt retrieval."""
    start, prompt = [], []
    for e in events:
        if e.get("type") == "system" and e.get("subtype") == "hook_response":
            try:
                ctx = json.loads(e.get("output") or "{}").get("hookSpecificOutput", {}).get("additionalContext", "")
            except ValueError:
                ctx = ""
            if ctx:
                (start if "SessionStart" in (e.get("hook_name") or "") else prompt).append(ctx)
    s, p = "\n".join(start), "\n".join(prompt)
    return {"start_text": s, "prompt_text": p, "start_tokens": len(s) // 4, "prompt_tokens": len(p) // 4}


def session_metrics(events: list, wall: float) -> dict:
    final = next((e for e in reversed(events) if e.get("type") == "result"), {})
    tools = [b.get("name") for _, b in _blocks(events, "assistant") if b.get("type") == "tool_use"]
    mu = final.get("modelUsage") or {}
    tok = {k: sum(int(v.get(k) or 0) for v in mu.values())
           for k in ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")}
    bash = bash_runs(events)
    return {"session_id": final.get("session_id"), "ok": bool(final) and not final.get("is_error"),
            "subtype": final.get("subtype"), "num_turns": final.get("num_turns"),
            "cost_usd": final.get("total_cost_usd", 0.0), "duration_ms": final.get("duration_ms"), "wall_s": round(wall, 1),
            "tool_calls": len(tools), "tools": {t: tools.count(t) for t in sorted(set(tools))},
            "bash_calls": len(bash), "bash_failed": sum(1 for r in bash if r["exit"] not in (0, None)),
            "permission_denials": len(final.get("permission_denials") or []),
            "bash_log": [f"{r['cmd'][:140]} -> {r['exit']}" for r in bash],
            "tokens": tok, "tokens_total": sum(tok.values()), "models": sorted(mu),
            "error": str(final.get("result", ""))[:300] if final.get("is_error") or not final else ""}


_ASSIGN = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+")


def segments(cmd: str) -> list[str]:
    """Simple commands of a shell line: split on ; && || | and newlines, `cd x` dropped, VAR=val prefixes dropped."""
    out = []
    for seg in re.split(r"&&|\|\||;|\||\n", cmd):
        seg = _ASSIGN.sub("", seg.strip().lstrip("("))
        seg = re.sub(r"^(?:timeout\s+\S+|time|nohup)\s+", "", seg)
        if seg and not re.match(r"^cd(?:\s|$)", seg):
            out.append(seg)
    return out


def _any_seg(cmd: str, rx: str) -> bool:
    return any(re.search(rx, sg) for sg in segments(cmd))


def exec_facts(events: list, judge: dict) -> dict:
    """E1 (how to run the checks) and E2 (how to run the CLI) from the transcript; P1 (lint run)."""
    j1, j2 = judge["E1"], judge["E2"]
    bash = bash_runs(events)
    tests = [r for r in bash if _any_seg(r["cmd"], j1["test_cmd"])]
    wrong = [r for r in tests if _any_seg(r["cmd"], j1["wrong"]) or re.search(j1["no_tests"], r["output"])
             or r["exit"] in (5, 127)]
    first_pass = next((i for i, r in enumerate(tests) if r["exit"] == 0 and r not in wrong), None)
    idx_all = [i for i, r in enumerate(bash) if r in tests]
    calls_before_pass = idx_all[first_pass] if first_pass is not None else None
    cli = [r for r in bash if _any_seg(r["cmd"], j2["wrong"])]
    lint = [r for r in bash if "P1" in judge and _any_seg(r["cmd"], judge["P1"]["lint_cmd"])]
    return {"E1_mistake": bool(wrong), "E1_wrong_test_cmds": len(wrong), "E1_test_cmds": len(tests),
            "E1_first_test_cmd": tests[0]["cmd"][:160] if tests else None,
            "E1_test_cmds_before_pass": first_pass, "E1_bash_before_pass": calls_before_pass,
            "E1_ran_tests": bool(tests), "E2_mistake": bool(cli), "E2_wrong_cli_cmds": len(cli),
            "P1_mistake": not lint, "lint_cmds": len(lint),
            "evidence_E": [r["cmd"][:160] + f"  -> exit {r['exit']}" for r in wrong + cli][:6]}


# ---------------------------------------------------------------- final-state judging

def _added_lines(before: str, after: str) -> list[str]:
    old = set(before.splitlines())
    return [ln for ln in after.splitlines() if ln not in old]


def _unreleased_bullets(text: str, section: str) -> int:
    if section not in text:
        return 0
    body = text.split(section, 1)[1]
    body = re.split(r"\n## ", body, maxsplit=1)[0]
    return sum(1 for ln in body.splitlines() if ln.strip().startswith(("-", "*")))


def judge_files(later: dict, repo: Path, start_files: dict, judge: dict) -> dict:
    """Conventions C1-C4 on the final state of the exact files this task asks for. None = not applicable/absent."""
    out = {"incomplete": [], "evidence_C": {}}
    read = lambda rel: (repo / rel).read_text(errors="replace") if (repo / rel).is_file() else None  # noqa: E731
    if not later["applies"]:
        return out
    news = {rel: read(rel) for rel in later["new_py"]}
    out["incomplete"] = [rel for rel, t in news.items() if t is None]
    present = {rel: t for rel, t in news.items() if t is not None}
    line = judge["C1"]["first_line"]
    bad = [rel for rel, t in present.items() if (t.splitlines() or [""])[0].strip() != line]
    out["C1_mistake"] = bool(bad) if present else None
    if bad:
        out["evidence_C"]["C1"] = {rel: (present[rel].splitlines() or [""])[0][:80] for rel in bad}
    mod = present.get(later["module"])
    added = [ln for rel in later.get("also_judge", []) for ln in _added_lines(start_files.get(rel, ""), read(rel) or "")]
    c2_text = "\n".join(([mod] if mod else []) + added)
    m2 = re.search(judge["C2"]["regex"], c2_text)
    out["C2_mistake"] = bool(m2) if mod is not None else None
    out["C2_complied"] = bool(re.search(judge["C2"]["comply"], c2_text))
    if m2:
        out["evidence_C"]["C2"] = c2_text[max(0, m2.start() - 60): m2.end() + 60]
    before = _unreleased_bullets(start_files.get("CHANGES.md", ""), judge["C3"]["section"])
    after = _unreleased_bullets(read("CHANGES.md") or "", judge["C3"]["section"])
    out["C3_mistake"] = after <= before
    m4 = re.search(judge["C4"]["regex"], mod or "")
    out["C4_mistake"] = bool(m4) if mod is not None else None
    if m4:
        out["evidence_C"]["C4"] = mod[max(0, m4.start() - 60): m4.end() + 60]
    vers = {}
    for rel, rx in judge["P2"]["files"].items():
        b, a = re.search(rx, start_files.get(rel, "")), re.search(rx, read(rel) or "")
        vers[rel] = (b.group(1) if b else None, a.group(1) if a else None)
    vt = lambda v: tuple(int(x) for x in v.split(".")) if v else ()  # noqa: E731
    bumped = all(a and b and vt(a) > vt(b) for b, a in vers.values())
    same = len({a for _, a in vers.values()}) == 1
    out["P2_mistake"] = not (bumped and same)
    out["versions"] = vers
    subj = new_commit_subjects(repo)
    out["new_commits"] = subj
    out["P3_mistake"] = not subj or any(not x.startswith(judge["P3"]["prefix"]) for x in subj)
    out["checks_pass_end"] = checks_pass(repo)
    return out


def new_commit_subjects(repo: Path) -> list[str]:
    """Subjects of commits made after make_repo's single initial commit."""
    p = subprocess.run(["git", "log", "--format=%s", "--reverse"], cwd=repo, capture_output=True, text=True)
    return p.stdout.splitlines()[1:] if p.returncode == 0 else []


def checks_pass(repo: Path) -> bool:
    try:
        p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "checks", "-p", "check_*.py", "-t", "."],
                           cwd=repo, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return False
    return p.returncode == 0


def relevance(inj: dict, applies: list, keys: dict) -> dict:
    """Memory lines memcode injected, labelled relevant (mention an applicable lesson) or not."""
    def lines(text):
        return [ln.strip() for ln in text.splitlines() if ln.strip().startswith("- ")]
    def rel(ln):
        return any(re.search(keys[k], ln) for k in applies)
    s, p = lines(inj["start_text"]), lines(inj["prompt_text"])
    return {"start_lines": len(s), "start_irrelevant": sum(1 for ln in s if not rel(ln)),
            "prompt_lines": len(p), "prompt_irrelevant": sum(1 for ln in p if not rel(ln))}


# ---------------------------------------------------------------- memory snapshots

def memory_snapshot(repo: Path, arm: str) -> dict:
    snap = {}
    if (repo / "CLAUDE.md").is_file():
        snap["claude_md"] = (repo / "CLAUDE.md").read_text()[:4000]
    a = run.automem_dir(repo)
    if a.exists():
        snap["automem"] = {str(f.relative_to(a)): f.read_text(errors="replace")[:2000] for f in a.rglob("*") if f.is_file()}
    db = repo / ".memcode" / "memory.db"
    if db.exists():
        con = sqlite3.connect(db)
        try:
            snap["memories"] = [f"#{r[0]} ({r[1]}) {r[2]}" + (f" [{r[3]}]" if r[3] else "")
                                for r in con.execute("SELECT id, trigger, text, anchor_path FROM memories ORDER BY id")]
            try:
                snap["facts"] = [f"{r[0]} = {r[1]} (runs {r[2]}, ok {r[3]}, fail {r[4]})"
                                 for r in con.execute("SELECT key, value, runs, ok, fail FROM facts ORDER BY key")]
            except sqlite3.OperationalError:
                snap["facts"] = None             # plugin version without facts
        finally:
            con.close()
    return snap


# ---------------------------------------------------------------- units

def _repo_for(day: int, prev: Path | None, arm: str) -> tuple[Path, dict]:
    files = P.files_for_day(day)
    sc = {"files": files}
    return (run.make_repo(sc) if prev is None else run.fresh_with_memory(sc, prev, arm)), files


def run_later(later: dict, prev: Path | None, arm: str, model: str, spec: dict, plugin_dir: Path) -> dict:
    repo, files = _repo_for(later["day"], prev, arm)
    prompt = later["prompt"] + (" " + spec["oracle"] if arm == "oracle" else "")
    ev, wall = claude(repo, prompt, model, arm, plugin_dir)
    m = session_metrics(ev, wall)
    m.update(name=later["name"], day=later["day"], applies=later["applies"])
    m.update(exec_facts(ev, spec["judge"]))
    m.update(judge_files(later, repo, files, spec["judge"]))
    inj = injected(ev)
    m["injected"] = {"start_tokens": inj["start_tokens"], "prompt_tokens": inj["prompt_tokens"],
                     **relevance(inj, later["applies"], spec["keys"]),
                     "start_text": inj["start_text"][:6000], "prompt_text": inj["prompt_text"][:3000]}
    m["claude_md_chars"] = len((repo / "CLAUDE.md").read_text()) if (repo / "CLAUDE.md").is_file() else 0
    m["edits"] = sum(m["tools"].get(t, 0) for t in ("Write", "Edit", "MultiEdit"))
    if not later["applies"]:
        m["new_commits"] = new_commit_subjects(repo)
        for k in ("P1_mistake",):          # lint/test lessons do not apply to a question
            m.pop(k, None)
    return m


def run_unit(args: tuple) -> dict:
    arm, rep, model, spec, plugin_dir, later_names = args
    rec = {"arm": arm, "rep": rep, "model": model, "teach": [], "later": []}
    prev = None
    if arm != "oracle_only":
        for sess in spec["teach"]:
            repo, _ = _repo_for(sess["day"], prev, arm)
            sid, turns = None, []
            for i, t in enumerate(sess["turns"]):
                prompt = t["text"] + (" Save this rule to CLAUDE.md." if arm == "claudemd" and t.get("rule") else "")
                ev, wall = claude(repo, prompt, model, arm, plugin_dir, resume=sid)
                m = session_metrics(ev, wall)
                if i == 0:
                    sid = m["session_id"]
                    m.update(exec_facts(ev, spec["judge"]))
                    m["injected_start_tokens"] = injected(ev)["start_tokens"]
                turns.append(m)
            rec["teach"].append({"day": sess["day"], "turns": turns,
                                 "stored": run.memcode_memories(repo) if arm == "memcode" else None})
            prev = repo
        rec["memory_after_teaching"] = memory_snapshot(prev, arm)
    for later in spec["later"]:
        if later_names and later["name"] not in later_names:
            continue
        rec["later"].append(run_later(later, prev, arm, model, spec, plugin_dir))
    return rec


def pilot_unit(args: tuple) -> dict:
    arm, rep, model, spec, plugin_dir, later_names = args
    return {"arm": arm, "rep": rep, "model": model, "teach": [],
            "later": [run_later(l, None, arm, model, spec, plugin_dir) for l in spec["later"]
                      if not later_names or l["name"] in later_names]}


def snapshot_plugin(ref: str) -> tuple[Path, str]:
    """Read-only copy of the plugin at a git ref (git archive), so development cannot change the code under test."""
    sha = subprocess.run(["git", "rev-parse", ref], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    dst = Path(tempfile.gettempdir()) / f"memcode-plugin-{sha[:10]}"
    if not (dst / "memcode").is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        tar = subprocess.run(["git", "archive", "--format=tar", sha], cwd=ROOT, capture_output=True, check=True).stdout
        tf = Path(tempfile.mkstemp(suffix=".tar")[1])
        tf.write_bytes(tar)
        with tarfile.open(tf) as t:
            t.extractall(dst, filter="data")
        tf.unlink()
    return dst, sha


# ---------------------------------------------------------------- summary

LESSONS = ("C1", "C2", "C3", "C4", "P1", "P2", "P3", "E1", "E2")


def valid(r: dict) -> bool:
    """A simulated week counts only if every session in it ran: a refused teaching turn means memory was never
    taught, a refused later session means nothing was measured."""
    return all(t.get("ok") for s in r["teach"] for t in s["turns"]) and all(m.get("ok") for m in r["later"])


def summarize(results: list[dict]) -> str:
    from bench.scorecard import wilson
    dropped = [f"{r['arm']}#{r['rep']}" for r in results if not valid(r)]
    results = [r for r in results if valid(r)]
    arms = list(dict.fromkeys(r["arm"] for r in results))
    names = list(dict.fromkeys(m["name"] for r in results for m in r["later"]))
    L = ["| session | arm | n | " + " | ".join(LESSONS) + " | lesson mistakes | checks pass | tool calls | bash failed | "
         "tokens (k) | cost $ | wall s | memcode inj. tok (start+prompt) | irrelevant prompt lines |",
         "|" + "---|" * (len(LESSONS) + 12)]
    for name in names:
        for arm in arms:
            ms = [m for r in results if r["arm"] == arm for m in r["later"] if m["name"] == name]
            if not ms:
                continue
            n = len(ms)
            cells, tot_k, tot_n = [], 0, 0
            for les in LESSONS:
                vals = [m.get(f"{les}_mistake") for m in ms if les in m["applies"]]
                vals = [v for v in vals if v is not None]
                if not vals:
                    cells.append("-")
                    continue
                k = sum(vals)
                tot_k, tot_n = tot_k + k, tot_n + len(vals)
                cells.append(f"{k}/{len(vals)}")
            lo, hi = wilson(tot_k, tot_n) if tot_n else (0, 0)
            avg = lambda f: sum(f(m) for m in ms) / n  # noqa: E731
            L.append(f"| {name} | {arm} | {n} | " + " | ".join(cells)
                     + (f" | {tot_k}/{tot_n} [{lo:.2f},{hi:.2f}]" if tot_n else " | -")
                     + f" | {sum(1 for m in ms if m.get('checks_pass_end'))}/{n}"
                     + f" | {avg(lambda m: m['tool_calls']):.1f} | {avg(lambda m: m['bash_failed']):.1f}"
                     + f" | {avg(lambda m: m['tokens_total']) / 1000:.0f} | {avg(lambda m: m['cost_usd']):.4f}"
                     + f" | {avg(lambda m: m['wall_s']):.0f}"
                     + f" | {avg(lambda m: m['injected']['start_tokens']):.0f}+{avg(lambda m: m['injected']['prompt_tokens']):.0f}"
                     + f" | {avg(lambda m: m['injected']['prompt_irrelevant']):.1f} |")
    week = []
    for arm in arms:
        rs = [r for r in results if r["arm"] == arm]
        tcost = sum(t["cost_usd"] for r in rs for s in r["teach"] for t in s["turns"]) / max(1, len(rs))
        lcost = sum(m["cost_usd"] for r in rs for m in r["later"]) / max(1, len(rs))
        week.append(f"- {arm}: teaching ${tcost:.3f} + later ${lcost:.3f} per week (mean of {len(rs)})")
    note = ["", f"Excluded (a session failed to run): {', '.join(dropped)}"] if dropped else []
    return "\n".join(L + ["", "Cost per simulated week:"] + week + note)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--set", default="frozen", choices=("frozen", "candidates"))
    ap.add_argument("--later", default="", help="comma-separated later-session names (default: all)")
    ap.add_argument("--pilot", choices=("nomem", "oracle"), help="later sessions only, from the canonical repo, no memory")
    ap.add_argument("--plugin-ref", default="", help="git ref of the plugin under test (default: this checkout)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--summarize", nargs="+", metavar="JSON", help="print the summary of saved result files and exit")
    a = ap.parse_args()
    if a.summarize:
        print(summarize([r for f in a.summarize for r in json.loads(Path(f).read_text())["results"]]))
        return
    spec = load_spec(a.set)
    names = [n for n in a.later.split(",") if n]
    plugin_dir, sha = (snapshot_plugin(a.plugin_ref) if a.plugin_ref else (ROOT, "worktree"))
    arms = [a.pilot] if a.pilot else a.arms.split(",")
    units = [(arm, rep, a.model, spec, plugin_dir, names) for arm in arms for rep in range(a.repeats)]
    n_later = len([l for l in spec["later"] if not names or l["name"] in names])
    calls = len(units) * (n_later + (0 if a.pilot else sum(len(s["turns"]) for s in spec["teach"])))
    if a.dry_run:
        print(json.dumps({"arms": arms, "repeats": a.repeats, "units": len(units), "claude_calls": calls,
                          "plugin": str(plugin_dir), "plugin_sha": sha, "later": names or "all"}, indent=1))
        return
    global RAW_DIR
    stamp = int(time.time())
    RAW_DIR = HERE / "results" / f"e2e1_raw_{a.pilot or 'full'}_{a.model}_{stamp}"
    with cf.ThreadPoolExecutor(a.workers) as ex:
        results = list(ex.map(pilot_unit if a.pilot else run_unit, units))
    out = Path(a.out or HERE / "results" / f"e2e1_{a.pilot or 'full'}_{a.model}_{int(time.time())}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {"plugin_sha": sha, "plugin_dir": str(plugin_dir), "model": a.model, "set": a.set,
            "spec_sha256": hashlib.sha256(json.dumps({k: spec[k] for k in ("teach", "later", "judge")},
                                                     sort_keys=True).encode()).hexdigest()}
    out.write_text(json.dumps({"meta": meta, "results": results}, indent=1))
    print(summarize(results))
    total = sum(t["cost_usd"] for r in results for s in r["teach"] for t in s["turns"]) + \
        sum(m["cost_usd"] for r in results for m in r["later"])
    print(f"\nTotal cost ${total:.2f}; raw: {out}")


if __name__ == "__main__":
    main()
