"""Parse `claude -p --output-format stream-json --verbose` transcripts into benchmark metrics. No network."""
from __future__ import annotations

import json
import re

EXPLORE_RE = re.compile(r"^\s*(ls|find|grep|rg|tree)\b")


def parse_stream(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def bash_calls(events: list[dict]) -> list[str]:
    cmds = []
    for e in events:
        if e.get("type") != "assistant":
            continue
        for b in (e.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Bash":
                cmds.append((b.get("input") or {}).get("command", ""))
    return cmds


def edit_paths(events: list[dict]) -> list[str]:
    paths = []
    for e in events:
        if e.get("type") != "assistant":
            continue
        for b in (e.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in ("Write", "Edit", "MultiEdit"):
                paths.append((b.get("input") or {}).get("file_path", ""))
    return paths


def tool_results(events: list[dict]) -> list[str]:
    res = []
    for e in events:
        if e.get("type") != "user":
            continue
        c = (e.get("message") or {}).get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    v = b.get("content")
                    res.append(v if isinstance(v, str) else json.dumps(v))
    return res


def metrics(events: list[dict], trap_regex: str) -> dict:
    cmds = bash_calls(events) + edit_paths(events)   # trap may hit a command or a written path
    trap = re.compile(trap_regex)
    final = next((e for e in reversed(events) if e.get("type") == "result"), {})
    return {
        "trap_hit": any(trap.search(c) for c in cmds),
        "explore_calls": sum(1 for c in cmds if EXPLORE_RE.match(c)),
        "bash_calls": len(cmds),
        "cost_usd": final.get("total_cost_usd", 0.0),
        "session_id": final.get("session_id"),
    }


def summarize(runs: list[dict]) -> dict:
    n = len(runs) or 1
    return {"runs": len(runs), "trap_rate": sum(r["trap_hit"] for r in runs) / n,
            "explore_calls": sum(r["explore_calls"] for r in runs) / n,
            "cost_usd": sum(r["cost_usd"] for r in runs)}
