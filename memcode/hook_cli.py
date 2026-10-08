"""Claude Code hook entrypoint:
`python3 -m memcode.hook_cli <SessionStart|UserPromptSubmit|PostToolUse|PostToolUseFailure|PreCompact>`.

Reads the hook JSON from stdin, feeds trigger events to the engine, and for SessionStart
(which also fires with source "compact" after a compaction) prints the pinned block as
additionalContext. PreCompact has no context-injection protocol, so it only does
side-effect work (refreshing the tree). Never raises: a memory failure must not break
the agent; failures are appended to .memcode/error.log.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

from . import store

_EXIT_RE = re.compile(r"Exit code (-?\d+)")


def _text(v) -> str:
    return v if isinstance(v, str) else ("" if v is None else str(v))


def _tool_event(d: dict, failed: bool) -> dict:
    session = d.get("session_id", "unknown")
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
    return {"kind": "tool_result", "session": session, "tool": d.get("tool_name", ""),
            "input": inp, "command": inp.get("command"), "file_path": inp.get("file_path"),
            "exit_code": code, "output": (out + ("\n" + err if err else "")).strip()}


def _events(name: str, d: dict) -> list[dict]:
    session = d.get("session_id", "unknown")
    if name == "UserPromptSubmit":
        return [{"kind": "prompt", "session": session, "prompt": d.get("prompt", "")}]
    if name in ("PostToolUse", "PostToolUseFailure"):
        ev = _tool_event(d, failed=(name == "PostToolUseFailure"))
        # one hook delivers both halves: replay it as tool_use then tool_result
        return [dict(ev, kind="tool_use"), ev]
    return []


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
    try:
        d = json.load(sys.stdin)
        if not isinstance(d, dict):
            d = {}
    except Exception:
        d = {}
    root = store.resolve_root(d.get("cwd"))
    try:
        con = store.connect(root)
        try:
            evs = _events(name, d)
            if evs:
                from .triggers import TriggerEngine
                ids = TriggerEngine(con, root).handle_batch(evs)   # one engine, one replay
                if name == "UserPromptSubmit":
                    from . import retrieval            # opt-in: memories relevant to THIS prompt
                    if retrieval.enabled(root):
                        ctx = retrieval.for_prompt(con, root, evs[0]["session"], evs[0]["prompt"])
                        if ctx:
                            print(json.dumps({"hookSpecificOutput": {
                                "hookEventName": "UserPromptSubmit", "additionalContext": ctx}}))
                if name == "UserPromptSubmit" and not any(ids):
                    from . import model_capture        # opt-in: let a model judge what the patterns missed
                    if model_capture.enabled(root) and model_capture.should_queue(con, evs[0]["session"], evs[0]["prompt"]):
                        model_capture.enqueue(con, evs[0]["session"], evs[0]["prompt"])
                        model_capture.spawn_worker(root)
            if name in ("SessionStart", "PreCompact"):
                from . import tree
                tree.refresh_from_git_diff(con, root)      # renames / plain mv re-anchor
                tree.scan_repo(con, root)
                tree.mark_stale(con, root)
                if name == "SessionStart":
                    from . import outcomes, pinned
                    outcomes.score_finished_sessions(con, root, current_session=d.get("session_id"))
                    text = pinned.render_pinned(con, root)
                    rules, notes = pinned.count_injected(text)
                    sid = d.get("session_id", "unknown")
                    store.bump(con, sid, "rules_injected", rules)
                    store.bump(con, sid, "notes_injected", notes)
                    now = time.time()
                    con.executemany("INSERT INTO injections(session,memory_id,ts) VALUES(?,?,?)",
                                    [(sid, i, now) for i in pinned.shown_ids(con, text)])
                    con.commit()
                    from . import salience              # shadow mode: logged, never used for ranking
                    salience.log_all(con)
                    store.prune_salience_log(con)
                    if text:
                        print(json.dumps({"hookSpecificOutput": {
                            "hookEventName": "SessionStart", "additionalContext": text}}))
        finally:
            con.close()
    except Exception as e:  # never break the agent
        print(f"memcode: {e}", file=sys.stderr)
        _log_error(root, e)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
