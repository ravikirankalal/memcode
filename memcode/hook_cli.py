"""Claude Code hook entrypoint: `python3 -m memcode.hook_cli <Event>` (hooks/hooks.json).

Reads the hook JSON from stdin, turns it into an engine call, and prints any context as
{"hookSpecificOutput": {"hookEventName", "additionalContext"}} (session start and per-prompt retrieval).
PreToolUse (scope hierarchy, on unless MEMCODE_HIER=0) may refuse a first write into a scope with unseen rules (engine.before_write).
Pre-compaction events only refresh the tree. Never raises: a memory failure must not break the agent; failures are
appended to .memcode/error.log.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

from . import store

# Claude Code event -> engine action
EVENTS = {"SessionStart": "start", "PreCompact": "prepare", "UserPromptSubmit": "prompt",
          "PostToolUse": "tool", "PostToolUseFailure": "tool_failure"}
_EXIT_RE = re.compile(r"Exit code (-?\d+)")


def _text(v) -> str:
    return v if isinstance(v, str) else ("" if v is None else str(v))


def tool_event(d: dict, failed: bool) -> dict:
    """A PostToolUse / PostToolUseFailure payload -> the engine's normalized tool event:
    {"kind": "tool_result", "session", "tool", "input", "command", "file_path", "exit_code", "output"}."""
    resp = d.get("tool_response")
    if not isinstance(resp, dict):
        resp = {"output": _text(resp)}
    inp = d.get("tool_input") or {}
    if not isinstance(inp, dict):
        inp = {"command": _text(inp)}
    code = resp.get("exit_code", resp.get("returnCode"))
    out = _text(resp.get("stdout", resp.get("output", "")))
    err = _text(resp.get("stderr"))
    if failed:
        # PostToolUseFailure: {"error": "Exit code 1\n<stderr>", "is_interrupt": bool}
        msg = _text(d.get("error") or resp.get("error"))
        m = _EXIT_RE.search(msg)
        code = int(m.group(1)) if m else (130 if d.get("is_interrupt") else 1)
        out, err = msg, ""
    elif code is None:
        code = 130 if resp.get("interrupted") else 0   # PostToolUse only fires on success
    output = (out + ("\n" + err if err else "")).strip()
    return {"kind": "tool_result", "session": d.get("session_id", "unknown"), "tool": d.get("tool_name", ""),
            "input": inp, "command": inp.get("command"), "file_path": inp.get("file_path"), "exit_code": code,
            "output": output}


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


def _start_memory_agent(con, root: str, session: str) -> None:
    try:
        from . import agent
        if agent.enabled(root):
            agent.start_session(con, session)
            agent.spawn_worker(root)               # sends the opening briefing in the background
    except Exception as e:  # noqa: BLE001  never break the agent
        _log_error(root, e)


def main(argv: list[str]) -> int:
    if os.environ.get("MEMCODE_DISABLE"):          # set by memcode's own model calls: never recurse
        return 0
    name = argv[1] if len(argv) > 1 else ""
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
    if name == "Stop":                             # only the memory agent listens; off: no store
        try:
            from . import agent
            if not (d.get("transcript_path") and agent.enabled(root)):
                return 0
        except Exception:  # noqa: BLE001  never break the agent
            return 0
    try:
        con = store.connect(root)
        try:
            from . import engine
            session = d.get("session_id", "unknown")
            if name == "Stop":                     # queue the log; the memory agent's worker reads it
                from . import agent
                agent.enqueue(con, session, str(d["transcript_path"]))
                agent.spawn_worker(root)
                return 0
            if name == "PreToolUse":
                reason = engine.before_write(con, root, session, d.get("tool_name", ""), d.get("tool_input") or {})
                if reason:
                    print(json.dumps({"hookSpecificOutput": {"hookEventName": name, "permissionDecision": "deny",
                                                             "permissionDecisionReason": reason}}))
                return 0
            action = EVENTS.get(name, "none")
            out, notice = "", []
            if action == "prompt":
                out = engine.prompt(con, root, session, _text(d.get("prompt")))
            elif action in ("tool", "tool_failure"):
                out = engine.tool_result(con, root, tool_event(d, failed=(action == "tool_failure")))
            elif action in ("start", "prepare"):
                out = engine.session_start(con, root, session, prepare_only=(action == "prepare"))
                if action == "start":                  # the coding agent (re)starts: so does its memory agent
                    _start_memory_agent(con, root, session)
                    from . import doctor
                    notice = doctor.at_start(con, root)    # for the user: a welcome, or what is broken
            res = {}
            if out:
                res["hookSpecificOutput"] = {"hookEventName": name, "additionalContext": out}
            if notice:
                res["systemMessage"] = "\n".join(notice)
            if res:
                print(json.dumps(res))
        finally:
            con.close()
    except Exception as e:  # never break the agent
        print(f"memcode: {e}", file=sys.stderr)
        _log_error(root, e)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
