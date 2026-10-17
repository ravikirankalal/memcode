"""Hook entrypoint for Claude Code, Codex CLI and Gemini CLI:
`python3 -m memcode.hook_cli <Event> [claude|codex|gemini]` (agent defaults to claude).

Reads the hook JSON from stdin, translates it with adapters.normalize, runs the engine, and prints any context as
{"hookSpecificOutput": {"hookEventName", "additionalContext"}} (session start and per-prompt retrieval).
PreToolUse (MEMCODE_HIER only) may refuse a first write into a scope with unseen rules (engine.before_write).
Pre-compaction events only refresh the tree. Never raises: a memory failure must not break the agent; failures are
appended to .memcode/error.log.
"""
from __future__ import annotations

import json
import os
import sys
import time

from . import store


def _log_error(root: str, e: BaseException) -> None:
    try:
        d = os.path.join(root, ".memcode")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "error.log")
        if os.path.exists(p) and os.path.getsize(p) > 100_000:
            os.remove(p)
        with open(p, "a") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {type(e).__name__}: {e}\n")
    except OSError:
        pass


def main(argv: list[str]) -> int:
    if os.environ.get("MEMCODE_DISABLE"):          # set by memcode's own model calls: never recurse
        return 0
    name = argv[1] if len(argv) > 1 else ""
    agent = argv[2] if len(argv) > 2 else "claude"
    try:
        d = json.load(sys.stdin)
        if not isinstance(d, dict):
            d = {}
    except Exception:
        d = {}
    if str(d.get("tool_name", "")).lower() in ("read", "read_file", "notebookread") \
            and os.environ.get("MEMCODE_HIER") != "1":
        return 0                                   # reads only matter for MEMCODE_HIER's first touch: stay cheap
    if name == "PreToolUse" and os.environ.get("MEMCODE_HIER") != "1":
        return 0                                   # only MEMCODE_HIER refuses a first write (engine.before_write)
    root = store.resolve_root(d.get("cwd"))
    try:
        con = store.connect(root)
        try:
            from . import adapters, engine
            session = d.get("session_id", "unknown")
            if name == "PreToolUse":
                reason = engine.before_write(con, root, session, d.get("tool_name", ""), d.get("tool_input") or {})
                if reason:
                    print(json.dumps({"hookSpecificOutput": {"hookEventName": name, "permissionDecision": "deny",
                                                             "permissionDecisionReason": reason}}))
                return 0
            action, data = adapters.normalize(agent, name, d)
            out = ""
            if action == "prompt":
                out = engine.prompt(con, root, session, data)
            elif action == "tool":
                out = "\n\n".join(t for t in (engine.tool_result(con, root, ev) for ev in data) if t)
            elif action in ("start", "prepare"):
                out = engine.session_start(con, root, session, prepare_only=(action == "prepare"))
            if out:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": name, "additionalContext": out}}))
        finally:
            con.close()
    except Exception as e:  # never break the agent
        print(f"memcode: {e}", file=sys.stderr)
        _log_error(root, e)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
