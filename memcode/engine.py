"""The memory agent at each moment of the coding agent's session (docs/architecture.md).

  session_start   deliver: what you said, then one ranked list of memories, then the map; refresh staleness first
  prompt          extract rules you state (pattern triggers); deliver the memories relevant to this request
  tool_result     extract from what the agent ran and edited (triggers, facts); deliver a folder's memory on first read
  before_write    deliver: hold a first write into a folder once, with its unseen rules as the reason
  (Stop hook)     extract: the model-backed memory agent reads the turn (agent/, queued by hook_cli)

Adapters (hook_cli.py for Claude Code, and others) translate their agent's hook payloads into these calls and the
returned context into their agent's output format. Tool events use one normalized shape:
  {"kind": "tool_result", "session", "tool", "input": dict, "command": str|None, "file_path": str|None,
   "exit_code": int, "output": str}
"""
from __future__ import annotations

import os
import time

from . import store


def session_start(con, root: str, session: str, prepare_only: bool = False) -> str:
    """Refresh the repo map, score finished sessions, render the pinned block and record what was shown.
    prepare_only (PreCompact): refresh only, render nothing."""
    from . import tree
    tree.refresh_from_git_diff(con, root)          # renames / plain mv re-anchor
    tree.scan_repo(con, root)
    tree.mark_stale(con, root)
    if prepare_only:
        return ""
    from . import facts, outcomes, pinned
    outcomes.score_finished_sessions(con, root, current_session=session)
    _safely(con, lambda: (facts.scan_repo(con, root), facts.infer(con)))
    from . import scope
    _safely(con, lambda: scope.rescope_new(con, root))    # where each new or re-anchored memory applies
    from . import graph
    _safely(con, lambda: graph.update(con))               # vectors and links of new or changed memories
    text = pinned.render_pinned(con, root)
    rules, notes = pinned.count_injected(text)
    store.bump(con, session, "rules_injected", rules)
    store.bump(con, session, "notes_injected", notes)
    now = time.time()
    con.executemany("INSERT INTO injections(session,memory_id,ts) VALUES(?,?,?)",
                    [(session, i, now) for i in pinned.shown_ids(con, text)])
    con.commit()
    from . import activity
    activity.note(con, "start", f"{rules} from you, {notes} memor{'y' if notes == 1 else 'ies'} at session start",
                  rules + notes)
    store.prune_orphans(con)
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
    stated = [i for i in ids if i]
    if stated:                                     # the user's own words are in context: never echo them back
        now = time.time()
        con.executemany("INSERT INTO injections(session,memory_id,ts,source) VALUES(?,?,?,'stated')",
                        [(session, i, now) for i in stated])
        con.commit()
    from . import retrieval
    parts = [retrieval.flagged(con, session)]                 # what the memory agent flagged after the last turn
    if retrieval.enabled(root):
        parts.append(retrieval.for_prompt(con, root, session, text))
    return "\n\n".join(p for p in parts if p)


def tool_result(con, root: str, ev: dict) -> str:
    """Feed one finished tool call (normalized shape above) to the triggers and the facts table. Returns context to
    inject next to the tool result: the scoped memories of a path touched for the first time (MEMCODE_HIER), what
    the memory agent flagged, and (retrieval on) the memories closely related to the command or edit just made.
    Reads only feed that first touch: they never reach the triggers, whose correction logic counts agent actions."""
    if str(ev.get("tool", "")).lower() not in READ_TOOLS:
        from . import facts
        from .triggers import TriggerEngine
        TriggerEngine(con, root).handle_batch([dict(ev, kind="tool_use"), dict(ev, kind="tool_result")])
        _safely(con, lambda: facts.observe(con, root, ev))
    from . import retrieval
    session = ev.get("session", "unknown")
    parts = [touch(con, root, ev), retrieval.flagged(con, session)]
    if str(ev.get("tool", "")).lower() not in READ_TOOLS and retrieval.enabled(root):
        parts.append(retrieval.for_action(con, root, session, ev))   # memories about the command or edit just made
    return "\n\n".join(p for p in parts if p)


WRITE_TOOLS = ("write", "edit", "multiedit", "notebookedit")
DENY_PREFIX = ("memcode: this file falls under project rules you have not seen yet, so this write was not made. "
               "Redo it following them:\n\n")


def before_write(con, root: str, session: str, tool: str, tool_input: dict) -> str:
    """MEMCODE_HIER: the reason to refuse the FIRST write into a scope whose user rules this session has not shown
    ('' = allow). A PostToolUse injection would arrive after a new file's content is already written, and PreToolUse
    context cannot change a tool call that is already composed, so the write is refused once with the rules as the
    reason; the agent redoes it. Rules are then recorded as shown (source 'touch'): later writes pass."""
    if str(tool).lower() not in WRITE_TOOLS or not isinstance(tool_input, dict):
        return ""
    from . import scope
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not path or not scope.has_unseen_rules(con, session, str(path), root):
        return ""
    text, ids = scope.rules_for_path(con, session, str(path), root)
    if not text:
        return ""
    from . import activity
    activity.note(con, "held", f"first write to {os.path.relpath(str(path), root) if os.path.isabs(str(path)) else path} "
                  f"held: {len(ids)} folder memor{'y' if len(ids) == 1 else 'ies'} shown first{activity.first(con, ids)}",
                  len(ids))
    return DENY_PREFIX + text


READ_TOOLS = ("read", "read_file", "notebookread")


def touch(con, root: str, ev: dict) -> str:
    """MEMCODE_HIER: first read or edit of a path in this session -> its directory/file-scoped memories, once."""
    from . import scope
    if not scope.hier_enabled():
        return ""
    inp = ev.get("input") if isinstance(ev.get("input"), dict) else {}
    path = ev.get("file_path") or inp.get("file_path") or inp.get("absolute_path") or inp.get("notebook_path")
    if not path:
        return ""
    text, ids = scope.rules_for_path(con, ev.get("session", "unknown"), str(path), root)
    if text:
        from . import activity
        rel = os.path.relpath(str(path), root) if os.path.isabs(str(path)) else str(path)
        activity.note(con, "touch", f"{len(ids)} memor{'y' if len(ids) == 1 else 'ies'} for {rel}{activity.first(con, ids)}",
                      len(ids))
    return text


def _safely(con, fn) -> None:
    """Extras (facts, scopes, the graph): a failure there is rolled back and reported, and never blocks capture or the block."""
    try:
        fn()
    except Exception as e:                    # noqa: BLE001
        con.rollback()
        import sys
        print(f"memcode: {e}", file=sys.stderr)
