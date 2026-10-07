"""Replay benchmark harness (offline, deterministic, no LLM/network).

Usage: python3 bench/run.py [--configs none,triggers] [--scenarios DIR] [--out FILE]

SMOKE TEST, NOT EVIDENCE: the "agent" below is a deterministic stub. It avoids a
scripted mistake iff some retrieved memory text contains the mistake's key phrase,
and skips a scripted exploratory call iff a memory contains its `skip_if_memory`
phrase. Numbers only show the harness plumbing works and that a config which
stores/retrieves relevant text scores better than one that does not. They say
nothing about real agent behaviour; that needs real LLM replays.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

EXPLORE_RE = re.compile(r"^\s*(ls|find|grep|rg)\b")


def load_scenarios(d: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))]


# ---- configurations: each exposes feed(event) and memories() -> list[str] ----
class NoneConfig:
    """No memory at all."""
    def __init__(self, repo_root): pass
    def feed(self, event): pass
    def memories(self): return []


class TriggersConfig:
    """memcode.triggers.TriggerEngine writes memories to the store; all live
    (non-stale) memory texts are 'retrieved' at each later session start."""
    def __init__(self, repo_root):
        try:
            from memcode import store
            from memcode.triggers import TriggerEngine
        except ImportError as e:
            raise RuntimeError(
                "config 'triggers' needs memcode.triggers.TriggerEngine, which is "
                f"not importable yet ({e}). Run with --configs none meanwhile.") from e
        self.store = store
        self.con = store.connect(repo_root)
        self.engine = TriggerEngine(self.con, repo_root)

    def feed(self, event):
        self.engine.handle(dict(event))

    def memories(self):
        return [r["text"] for r in self.store.list_memories(self.con)]


class StubConfig:
    """Placeholder for future configs (e.g. vector retrieval, pinned map).
    Subclass or register in CONFIGS; currently behaves like `none`."""
    def __init__(self, repo_root): pass
    def feed(self, event): pass
    def memories(self): return []


CONFIGS = {"none": NoneConfig, "triggers": TriggersConfig, "stub": StubConfig}


def run_scenario(scn: dict, config_name: str) -> dict:
    with tempfile.TemporaryDirectory() as root:
        cfg = CONFIGS[config_name](root)
        events = scn["events"]
        sessions = sorted({e["session"] for e in events})
        opportunities = repeated = 0
        with_mem = [0, 0]      # [repeated, opportunities] when a relevant memory existed
        without_mem = [0, 0]
        explore = 0
        context_chars = 0
        for s in sessions:
            mems = cfg.memories() if s > sessions[0] else []
            blob = "\n".join(mems).lower()
            if s > sessions[0]:
                context_chars += len("\n".join(mems))
            for m in scn.get("mistakes", []):
                if m["session"] != s:
                    continue
                existed = m["key_phrase"].lower() in blob
                made = not existed          # stub policy
                opportunities += 1
                repeated += made
                bucket = with_mem if existed else without_mem
                bucket[0] += made
                bucket[1] += 1
            for e in events:
                if e["session"] != s:
                    continue
                if e["kind"] == "tool_use" and EXPLORE_RE.match(e["input"].get("command", "")):
                    skip = e.get("skip_if_memory")
                    if not (skip and skip.lower() in blob):
                        explore += 1
            for e in events:            # feed after decisions: memories only help later sessions
                if e["session"] == s:
                    cfg.feed(e)
        rate = lambda b: (b[0] / b[1]) if b[1] else None
        return {"scenario": scn["name"], "config": config_name,
                "opportunities": opportunities, "repeated_mistakes": repeated,
                "repeated_mistake_rate": repeated / opportunities if opportunities else 0.0,
                "rate_with_memory": rate(with_mem), "rate_without_memory": rate(without_mem),
                "exploratory_calls": explore, "context_tokens": context_chars // 4}


def aggregate(rows: list[dict]) -> dict:
    opp = sum(r["opportunities"] for r in rows)
    rep = sum(r["repeated_mistakes"] for r in rows)
    return {"opportunities": opp, "repeated_mistakes": rep,
            "repeated_mistake_rate": rep / opp if opp else 0.0,
            "exploratory_calls": sum(r["exploratory_calls"] for r in rows),
            "context_tokens": sum(r["context_tokens"] for r in rows)}


def markdown(summary: dict) -> str:
    out = ["| config | repeated-mistake rate | exploratory calls | context tokens |",
           "|---|---|---|---|"]
    for c, a in summary.items():
        out.append(f"| {c} | {a['repeated_mistakes']}/{a['opportunities']} "
                   f"({a['repeated_mistake_rate']:.2f}) | {a['exploratory_calls']} "
                   f"| {a['context_tokens']} |")
    out.append("\n_Simulated-agent smoke test, not evidence of real agent behaviour._")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="none,triggers")
    ap.add_argument("--scenarios", default=str(HERE / "scenarios"))
    ap.add_argument("--out", default=str(HERE / "results.json"))
    a = ap.parse_args(argv)
    scenarios = load_scenarios(Path(a.scenarios))
    results, summary, errors = [], {}, {}
    for c in a.configs.split(","):
        if c not in CONFIGS:
            print(f"unknown config {c!r}; known: {sorted(CONFIGS)}", file=sys.stderr)
            return 2
        try:
            rows = [run_scenario(s, c) for s in scenarios]
        except RuntimeError as e:
            errors[c] = str(e)
            print(f"ERROR [{c}]: {e}", file=sys.stderr)
            continue
        results += rows
        summary[c] = aggregate(rows)
    Path(a.out).write_text(json.dumps(
        {"disclaimer": "simulated-agent smoke test, not evidence",
         "results": results, "summary": summary, "errors": errors}, indent=2))
    print(markdown(summary))
    return 1 if errors and not summary else 0


if __name__ == "__main__":
    sys.exit(main())
