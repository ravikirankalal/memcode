"""Reading the session log: Claude Code's transcript JSONL condensed to [user] / [agent] / [ran] / [wrote] lines, cut
into pieces of at most MAX_CHARS for the model."""
from __future__ import annotations

import json

from ..redact import redact

MAX_CHARS = 24_000           # condensed text sent per model call; a longer backlog goes in chunks, oldest first


def _blocks(msg) -> list:
    c = (msg or {}).get("content")
    return c if isinstance(c, list) else ([{"type": "text", "text": c}] if isinstance(c, str) else [])

def condense(lines: list[str]) -> str:
    """Transcript JSONL lines -> compact text: [user] / [agent] / [ran] / [wrote] lines. Harness-injected user turns
    (task notifications, reminders) and hook context are left out; tool output keeps only its tail."""
    return redact("\n".join(text for _, text in _entries(lines)))

def _entries(lines: list[str]) -> list[tuple[int, str]]:
    """condense() as (index of the line after the one that produced it, text) pairs, for chunking."""
    from ..engine import is_harness
    out: list[tuple[int, str]] = []
    pending_cmd: dict[str, str] = {}
    for i, raw in enumerate(lines, 1):
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(e, dict) or e.get("isMeta") or e.get("type") not in ("user", "assistant"):
            continue
        if e.get("isCompactSummary"):   # a summary of earlier turns, written as a user turn: not the user's words
            continue
        for b in _blocks(e.get("message")):
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if e["type"] == "user" and t == "text":
                text = str(b.get("text", "")).strip()
                if text and not is_harness(text) and not text.startswith(("<command-", "<local-command")):
                    out.append((i, "[user] " + " ".join(text.split())[:1500]))
            elif e["type"] == "assistant" and t == "text":
                text = " ".join(str(b.get("text", "")).split())
                if text:
                    out.append((i, "[agent] " + text[:800]))
            elif t == "tool_use":
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                name = b.get("name", "")
                if name == "Bash" and inp.get("command"):
                    pending_cmd[b.get("id", "")] = " ".join(str(inp["command"]).split())[:300]
                elif name in ("Write", "Edit", "MultiEdit", "NotebookEdit") and inp.get("file_path"):
                    out.append((i, f"[wrote] {inp['file_path']}"))
            elif t == "tool_result" and b.get("tool_use_id") in pending_cmd:
                cmd = pending_cmd.pop(b["tool_use_id"])
                c = b.get("content")
                text = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c if isinstance(x, dict)) \
                    if isinstance(c, list) else ""
                tail = " ".join(text.split())[-300:]
                out.append((i, f"[ran] `{cmd}` -> {'failed' if b.get('is_error') else 'ok'}" + (f" | {tail}" if tail else "")))
    return out

def chunks(lines: list[str]) -> list[tuple[int, str]]:
    """The condensed lines cut into pieces of at most MAX_CHARS, oldest first: (lines consumed, condensed text).
    The last piece consumes every line, so a turn whose tool result has not arrived yet is not rescanned forever."""
    out, cur, size = [], [], 0
    for end, text in _entries(lines):
        if cur and size + len(text) + 1 > MAX_CHARS:
            out.append((cur[-1][0], redact("\n".join(t for _, t in cur))))
            cur, size = [], 0
        cur.append((end, text[:MAX_CHARS]))
        size += len(cur[-1][1]) + 1
    if cur:
        out.append((len(lines), redact("\n".join(t for _, t in cur))))
    return out
