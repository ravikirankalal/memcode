"""Agent-neutral core: what memcode does at each point of an agent session (Phase 4: scale out).

Adapters (hook_cli.py for Claude Code, and others) translate their agent's hook payloads into these calls and the
returned context into their agent's output format. Tool events use one normalized shape:
  {"kind": "tool_result", "session", "tool", "input": dict, "command": str|None, "file_path": str|None,
   "exit_code": int, "output": str}
"""
from __future__ import annotations

import time

from . import store


def session_start(con, root: str, session: str, prepare_only: bool = False) -> str:
    """Refresh the repo map and team file, score finished sessions, render the pinned block and record what was shown.
    prepare_only (PreCompact): refresh only, render nothing."""
    from . import team, tree
    if not prepare_only:
        team.sync(con, root)                       # reviewed team memory from .memcode-team.jsonl
    tree.refresh_from_git_diff(con, root)          # renames / plain mv re-anchor
    tree.scan_repo(con, root)
    tree.mark_stale(con, root)
    if prepare_only:
        return ""
    from . import facts, outcomes, pinned, salience
    outcomes.score_finished_sessions(con, root, current_session=session)
    _safely(con, lambda: (facts.scan_repo(con, root), facts.infer(con)))
    text = pinned.render_pinned(con, root)
    rules, notes = pinned.count_injected(text)
    store.bump(con, session, "rules_injected", rules)
    store.bump(con, session, "notes_injected", notes)
    now = time.time()
    con.executemany("INSERT INTO injections(session,memory_id,ts) VALUES(?,?,?)",
                    [(session, i, now) for i in pinned.shown_ids(con, text)])
    con.commit()
    salience.log_all(con)                          # shadow log
    store.prune_salience_log(con)
    return text


# Turns the agent harness injects as "user" prompts (subagent reports, background-task notices, reminders). They are
# not the user's words: in real logs they were over half the prompt stream and carry words like "never" and "don't".
HARNESS_PREFIXES = ("<agent-message", "<task-notification", "<system-reminder", "<local-command-stdout",
                    "[SYSTEM NOTIFICATION")


def is_harness(text: str) -> bool:
    return (text or "").lstrip().startswith(HARNESS_PREFIXES)


def prompt(con, root: str, session: str, text: str) -> str:
    """Capture rules stated in the prompt; return per-prompt retrieval context ('' if off or nothing relevant).
    Harness-injected turns are ignored entirely: no capture, no retrieval."""
    if is_harness(text):
        return ""
    from .triggers import TriggerEngine
    ev = {"kind": "prompt", "session": session, "prompt": text}
    ids = TriggerEngine(con, root).handle_batch([ev])
    ctx = ""
    from . import retrieval
    if retrieval.enabled(root):
        ctx = retrieval.for_prompt(con, root, session, text)
    if not any(ids):
        from . import model_capture                # opt-in: let a model judge what the patterns missed
        if model_capture.enabled(root) and model_capture.should_queue(con, session, text):
            model_capture.enqueue(con, session, text)
            model_capture.spawn_worker(root)
    return ctx


def tool_result(con, root: str, ev: dict) -> None:
    """Feed one finished tool call (normalized shape above) to the triggers and the facts table."""
    from . import facts
    from .triggers import TriggerEngine
    TriggerEngine(con, root).handle_batch([dict(ev, kind="tool_use"), dict(ev, kind="tool_result")])
    _safely(con, lambda: facts.observe(con, root, ev))


def _safely(con, fn) -> None:
    """Facts are an extra: a failure there is rolled back and reported, and never blocks capture or the block."""
    try:
        fn()
    except Exception as e:                    # noqa: BLE001
        con.rollback()
        import sys
        print(f"memcode facts: {e}", file=sys.stderr)
