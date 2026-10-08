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


def edit_content(events: list[dict], with_kind: bool = False) -> list:
    """Text the agent wrote via Write/Edit/MultiEdit (for content-based traps). With with_kind,
    items are (text, is_snippet, path): Edit/MultiEdit write a fragment, Write writes a whole file."""
    out = []
    for e in events:
        if e.get("type") != "assistant":
            continue
        for b in (e.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in ("Write", "Edit", "MultiEdit"):
                i = b.get("input") or {}
                text = (str(i.get("content") or i.get("new_string") or "")
                        + " ".join(str(x.get("new_string", "")) for x in i.get("edits", []) if isinstance(x, dict)))
                path = str(i.get("file_path") or "")
                out.append((text, b.get("name") != "Write", path) if with_kind else text)
    return out


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


def metrics(events: list[dict], trap_regex: str, trap_on: str = "cmd_path", trap_path: str | None = None) -> dict:
    """trap_on: cmd_path (commands + written paths) | content (written text).
    trap_path: for content traps, only judge files whose path matches this regex (e.g. r"(^|/)billing/")."""
    bash = bash_calls(events)
    trap = re.compile(trap_regex, re.S)   # commands may be multi-line (heredocs)
    if trap_on == "content":
        # Start-of-file clauses (\A...) can only judge a whole file (Write), never an Edit fragment:
        # neutralise them for fragments so "fragment lacks the header" is not scored as a mistake.
        frag = re.compile(trap_regex.replace(r"\A", r"(?!)"), re.S)
        items = edit_content(events, with_kind=True)
        if trap_path:
            items = [it for it in items if re.search(trap_path, it[2])]
        cmds = [t for t, snip, _ in items if (frag if snip else trap).search(t)]
        hit = bool(cmds)
    else:
        cmds = bash + edit_paths(events)
        hit = any(trap.search(c) for c in cmds)
    final = next((e for e in reversed(events) if e.get("type") == "result"), {})
    return {
        "trap_hit": hit,
        "evidence": next((c[:160] for c in cmds if trap_on == "content" or trap.search(c)), None),
        "explore_calls": sum(1 for c in bash if EXPLORE_RE.match(c)),
        "bash_calls": len(bash),
        "cost_usd": final.get("total_cost_usd", 0.0),
        "session_id": final.get("session_id"),
    }


def summarize(runs: list[dict]) -> dict:
    n = len(runs) or 1
    return {"runs": len(runs), "trap_rate": sum(r["trap_hit"] for r in runs) / n,
            "explore_calls": sum(r["explore_calls"] for r in runs) / n,
            "cost_usd": sum(r["cost_usd"] for r in runs)}
