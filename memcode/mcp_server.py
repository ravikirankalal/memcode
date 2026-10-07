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


def call_tool(root: str, name: str, args: dict) -> str:
    con = store.connect(root)
    if name == "memory_search":
        q = args.get("query", "").lower().split()
        rows = [r for r in store.list_memories(con)
                if all(w in (r["text"] + " " + r["anchor_path"]).lower() for w in q)]
        rows = rows[: int(args.get("limit", 10))]
        for r in rows:  # record retrievals for reinforce-on-success
            con.execute("INSERT INTO retrievals(session,memory_id,ts) VALUES('mcp',?,strftime('%s','now'))", (r["id"],))
        con.commit()
        return "\n".join(f"#{r['id']} [{r['trigger']}] {r['anchor_path'] or '/'}: {r['text']}"
                         for r in rows) or "no matches"
    if name == "memory_add":
        path = args.get("path", "")
        f = os.path.join(root, path) if path else None
        h = store.sha1(open(f, "rb").read()) if f and os.path.isfile(f) else None
        mid = store.add_memory(con, "manual", redact(args["text"]), path, h,
                               {"source": "mcp"}, confidence=0.6)
        return f"stored memory #{mid}"
    if name == "memory_pinned":
        from . import pinned
        return pinned.render_pinned(con, root)
    raise ValueError(f"unknown tool {name}")


def handle(root: str, msg: dict) -> dict | None:
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:  # notification
        return None
    try:
        if method == "initialize":
            res = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                   "serverInfo": {"name": "memcode", "version": "0.1.0"}}
        elif method == "tools/list":
            res = {"tools": TOOLS}
        elif method == "tools/call":
            p = msg["params"]
            res = {"content": [{"type": "text", "text": call_tool(root, p["name"], p.get("arguments", {}))}]}
        elif method == "ping":
            res = {}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}
    except Exception as e:
        return {"jsonrpc": "2.0", "id": mid, "result": {"isError": True,
                "content": [{"type": "text", "text": str(e)}]}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def main() -> None:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        out = handle(root, json.loads(line))
        if out:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
