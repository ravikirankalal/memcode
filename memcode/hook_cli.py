"""Hook entrypoint for Claude Code, Codex CLI and Gemini CLI:
`python3 -m memcode.hook_cli <Event> [claude|codex|gemini]` (agent defaults to claude).

Reads the hook JSON from stdin, translates it with adapters.normalize, runs the engine, and prints any context as
{"hookSpecificOutput": {"hookEventName", "additionalContext"}} (session start and per-prompt retrieval).
PreToolUse (scope hierarchy, on unless MEMCODE_HIER=0) may refuse a first write into a scope with unseen rules (engine.before_write).
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
        d = str(store.memdir(root))
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
    hier_only = name == "PreToolUse" or str(d.get("tool_name", "")).lower() in ("read", "read_file", "notebookread")
    if hier_only and os.environ.get("MEMCODE_HIER", "").lower() in ("0", "false", "off"):
        return 0                                   # reads and PreToolUse only serve the scope hierarchy: stay cheap
    root = store.resolve_root(d.get("cwd"))
    try:
        from . import scope
        scope.apply_config(root)                   # `memcode config hierarchy off`
        if hier_only and not scope.hier_enabled():
            return 0
    except Exception:  # noqa: BLE001  never break the agent
        pass
    if name == "Stop":                             # only transcript capture listens; off (the default): no store
        try:
            from . import transcript_capture
            if not (d.get("transcript_path") and transcript_capture.enabled(root)):
                return 0
        except Exception:  # noqa: BLE001  never break the agent
            return 0
    try:
        con = store.connect(root)
        try:
            from . import adapters, engine
            session = d.get("session_id", "unknown")
            if name == "Stop":                     # opt-in transcript capture: queue it, a detached worker scans
                from . import transcript_capture
                transcript_capture.enqueue(con, session, str(d["transcript_path"]))
                transcript_capture.spawn_worker(root)
                return 0
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
