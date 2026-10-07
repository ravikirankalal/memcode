"""Minimal stdio MCP server (JSON-RPC 2.0, newline-delimited), stdlib only.

Tools: memory_search, memory_add, memory_pinned.
"""
from __future__ import annotations

import json
import os
import sys

from . import store
from .redact import redact

TOOLS = [
    {"name": "memory_search", "description": "Search stored coding memories by keyword.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"},
                     "limit": {"type": "integer"}}, "required": ["query"]}},
    {"name": "memory_add", "description": "Manually record a memory anchored to a repo path.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"},
                     "path": {"type": "string"}}, "required": ["text"]}},
    {"name": "memory_pinned", "description": "Return the current pinned repo map and notes.",
     "inputSchema": {"type": "object", "properties": {}}},
]


MAX_HASH_BYTES = 10 * 1024 * 1024
MAX_TEXT = 2000
SUPPORTED_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]


def safe_rel(root: str, path: str) -> str:
    """Normalize a user-supplied path to a repo-relative posix path; reject anything that
    resolves (symlinks included) outside the repo root."""
    if not isinstance(path, str):
        raise ValueError("path must be a string")
    path = path.strip()
    if not path or path == ".":
        return ""
    if "\0" in path:
        raise ValueError("invalid path")
    base = os.path.realpath(root)
    target = os.path.realpath(os.path.join(base, path))
    try:
        rel = os.path.relpath(target, base)
    except ValueError:
        raise ValueError("path outside repository") from None
    if rel == ".":
        return ""
    if rel == ".." or rel.startswith(".." + os.sep) or os.path.isabs(rel):
        raise ValueError("path outside repository")
    return rel.replace(os.sep, "/")


def _bounded_int(v, default: int, lo: int, hi: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def call_tool(root: str, name: str, args: dict) -> str:
    if not isinstance(args, dict):
        raise ValueError("arguments must be an object")
    con = store.connect(root)
    try:
        return _call_tool(con, root, name, args)
    finally:
        con.close()


def _call_tool(con, root: str, name: str, args: dict) -> str:
    if name == "memory_search":
        q = str(args.get("query", "")).lower().split()
        rows = [r for r in store.list_memories(con)
                if all(w in (r["text"] + " " + r["anchor_path"]).lower() for w in q)]
        rows = rows[: _bounded_int(args.get("limit"), 10, 1, 50)]
        for r in rows:  # record retrievals for reinforce-on-success
            con.execute("INSERT INTO retrievals(session,memory_id,ts) VALUES('mcp',?,strftime('%s','now'))", (r["id"],))
        con.commit()
        return "\n".join(f"#{r['id']} [{r['trigger']}] {r['anchor_path'] or '/'}: {r['text']}"
                         for r in rows) or "no matches"
    if name == "memory_add":
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text is required")
        rel = safe_rel(root, args.get("path", "") or "")
        f = os.path.join(os.path.realpath(root), rel) if rel else None
        h = None
        if f and os.path.isfile(f) and os.path.getsize(f) <= MAX_HASH_BYTES:
            with open(f, "rb") as fh:
                h = store.sha1(fh.read())
        mid = store.add_memory(con, "manual", redact(text.strip())[:MAX_TEXT], redact(rel), h,
                               {"source": "mcp"}, confidence=0.6)
        return f"stored memory #{mid}"
    if name == "memory_pinned":
        from . import pinned
        return pinned.render_pinned(con, root)
    raise ValueError(f"unknown tool {name}")


def _err(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def handle(root: str, msg) -> dict | None:
    if not isinstance(msg, dict):
        return _err(None, -32600, "invalid request")
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:  # notification
        return None
    params = msg.get("params")
    if not isinstance(params, dict):
        params = {}
    try:
        if method == "initialize":
            want = params.get("protocolVersion")
            ver = want if want in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
            res = {"protocolVersion": ver, "capabilities": {"tools": {}},
                   "serverInfo": {"name": "memcode", "version": "0.1.0"}}
        elif method == "tools/list":
            res = {"tools": TOOLS}
        elif method == "tools/call":
            res = {"content": [{"type": "text", "text": call_tool(
                root, params["name"], params.get("arguments") or {})}]}
        elif method == "ping":
            res = {}
        else:
            return _err(mid, -32601, "method not found")
    except Exception as e:
        return {"jsonrpc": "2.0", "id": mid, "result": {"isError": True,
                "content": [{"type": "text", "text": str(e) or type(e).__name__}]}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def handle_line(root: str, line: str):
    """One input line -> response object (or list for a JSON-RPC batch) or None. Never raises."""
    try:
        msg = json.loads(line)
    except ValueError:
        return _err(None, -32700, "parse error")
    if isinstance(msg, list):
        if not msg:
            return _err(None, -32600, "invalid request")
        outs = [o for o in (handle(root, m) for m in msg) if o]
        return outs or None
    return handle(root, msg)


def main() -> None:
    root = store.resolve_root()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        out = handle_line(root, line)
        if out:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
