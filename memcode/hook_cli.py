"""Claude Code hook entrypoint: `python3 -m memcode.hook_cli <SessionStart|UserPromptSubmit|PostToolUse|PreCompact>`.

Reads the hook JSON from stdin, feeds trigger events to the engine, and for
SessionStart/PreCompact prints the pinned block as additionalContext.
Never raises: a memory failure must not break the agent.
"""
from __future__ import annotations

import json
import os
import sys

from . import store


def _event(name: str, d: dict) -> dict | None:
    session = d.get("session_id", "unknown")
    if name == "UserPromptSubmit":
        return {"kind": "prompt", "session": session, "prompt": d.get("prompt", "")}
    if name == "PostToolUse":
        resp = d.get("tool_response") or {}
        if not isinstance(resp, dict):
            resp = {"output": str(resp)}
        inp = d.get("tool_input") or {}
        return {"kind": "tool_result", "session": session, "tool": d.get("tool_name", ""),
                "input": inp, "command": inp.get("command"), "file_path": inp.get("file_path"),
                "exit_code": resp.get("exit_code", resp.get("returnCode")),
                "output": resp.get("stdout", resp.get("output", "")) or ""}
    return None


def main(argv: list[str]) -> int:
    name = argv[1] if len(argv) > 1 else ""
    try:
        d = json.load(sys.stdin)
    except Exception:
        d = {}
    root = d.get("cwd") or os.getcwd()
    try:
        con = store.connect(root)
        ev = _event(name, d)
        if ev:
            from .triggers import TriggerEngine
            if ev["kind"] == "tool_result":
                # PostToolUse is the only tool hook: replay it as use then result
                use = dict(ev, kind="tool_use")
                TriggerEngine(con, root).handle(use)
            TriggerEngine(con, root).handle(ev)
        if name in ("SessionStart", "PreCompact"):
            from . import tree, pinned
            tree.scan_repo(con, root)
            tree.mark_stale(con, root)
            text = pinned.render_pinned(con, root)
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": name if name == "SessionStart" else "SessionStart",
                "additionalContext": text}}))
    except Exception as e:  # never break the agent
        print(f"memcode: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
