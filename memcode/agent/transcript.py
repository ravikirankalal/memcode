"""Reading the session log: Claude Code's transcript JSONL condensed to one line per event, cut into pieces of at most
MAX_CHARS for the model:

  [user] / [agent]   what was said
  [ran]              a shell command, its result and output tail
  [read]             a file the coding agent read, with its opening lines (what a class, enum or config holds)
  [edited] / [wrote] a file it changed, with the new text
"""
from __future__ import annotations

import json
import re

MAX_CHARS = 24_000           # condensed text sent per model call; a longer backlog goes in chunks, oldest first
READ_CHARS = 1500            # opening of a file the coding agent read
EDIT_CHARS = 400             # new text of an edit
WRITE_CHARS = 600            # opening of a file it wrote
_LINE_NO = re.compile(r"^\s*\d+(?:\t|→)", re.M)   # Read output numbers its lines: "    12\t..." / "  12→..."


def _blocks(msg) -> list:
    c = (msg or {}).get("content")
    return c if isinstance(c, list) else ([{"type": "text", "text": c}] if isinstance(c, str) else [])

def condense(lines: list[str]) -> str:
    """Transcript JSONL lines -> compact text: [user] / [agent] / [ran] / [wrote] lines. Harness-injected user turns
    (task notifications, reminders) and hook context are left out; tool output keeps only its tail."""
    return "\n".join(text for _, text in _entries(lines))

def _entries(lines: list[str]) -> list[tuple[int, str]]:
    """condense() as (index of the line after the one that produced it, text) pairs, for chunking."""
    from ..engine import is_harness
    out: list[tuple[int, str]] = []
    pending_cmd: dict[str, str] = {}
    pending_read: dict[str, str] = {}
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
                elif name == "Read" and inp.get("file_path"):
                    pending_read[b.get("id", "")] = str(inp["file_path"])
                elif name == "Write" and inp.get("file_path"):
                    out.append((i, f"[wrote] {inp['file_path']}" + _excerpt(inp.get("content"), WRITE_CHARS)))
                elif name in ("Edit", "MultiEdit", "NotebookEdit") and (inp.get("file_path") or inp.get("notebook_path")):
                    new = inp.get("new_string") or inp.get("new_source") or " ... ".join(
                        str(x.get("new_string", "")) for x in inp.get("edits") or [] if isinstance(x, dict))
                    out.append((i, f"[edited] {inp.get('file_path') or inp.get('notebook_path')}" + _excerpt(new, EDIT_CHARS)))
            elif t == "tool_result" and b.get("tool_use_id") in pending_read:
                path = pending_read.pop(b["tool_use_id"])
                if not b.get("is_error"):
                    out.append((i, f"[read] {path}" + _excerpt(_LINE_NO.sub("", _result_text(b)), READ_CHARS)))
            elif t == "tool_result" and b.get("tool_use_id") in pending_cmd:
                cmd = pending_cmd.pop(b["tool_use_id"])
                tail = " ".join(_result_text(b).split())[-300:]
                out.append((i, f"[ran] `{cmd}` -> {'failed' if b.get('is_error') else 'ok'}" + (f" | {tail}" if tail else "")))
    return out

def _result_text(b: dict) -> str:
    c = b.get("content")
    if isinstance(c, str):
        return c
    return " ".join(x.get("text", "") for x in c if isinstance(x, dict)) if isinstance(c, list) else ""


def _excerpt(text, n: int) -> str:
    """' | <text on one line, at most n characters>' (every condensed event is one line), or '' when empty."""
    t = " ".join(str(text or "").split())
    return f" | {t[:n]}" if t else ""


def chunks(lines: list[str]) -> list[tuple[int, str]]:
    """The condensed lines cut into pieces of at most MAX_CHARS, oldest first: (lines consumed, condensed text).
    The last piece consumes every line, so a turn whose tool result has not arrived yet is not rescanned forever."""
    out, cur, size = [], [], 0
    for end, text in _entries(lines):
        if cur and size + len(text) + 1 > MAX_CHARS:
            out.append((cur[-1][0], "\n".join(t for _, t in cur)))
            cur, size = [], 0
        cur.append((end, text[:MAX_CHARS]))
        size += len(cur[-1][1]) + 1
    if cur:
        out.append((len(lines), "\n".join(t for _, t in cur)))
    return out
