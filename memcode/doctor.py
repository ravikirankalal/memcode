"""Is memcode working here? `memcode doctor` runs every check; session start runs the cheap ones and tells the user.

Session start shows a message to the user (the hook's systemMessage, not the coding agent's context) when:
  * this is the first session in the repository: a one-time welcome, with the status mod's install command;
  * the store's SQLite has no JSON functions (the flat memory model needs them);
  * the memory agent is on but the `claude` CLI is not on PATH;
  * memcode logged errors since the last session start (.memcode/error.log).
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys

from . import config, store

WELCOME = ("memcode is on for this repository: it remembers what you say and what the agent learns, and hands it back "
           "when it matters. Memory lives in .memcode/ (kept out of git); /memcode:status shows what it holds, "
           "/memcode:cli doctor checks the setup. For a status line above the prompt: "
           "/plugin install memcode-status@memcode")


def _error_log(root) -> str:
    return os.path.join(str(store.memdir(root)), "error.log")


def _json_ok() -> bool:
    try:
        return sqlite3.connect(":memory:").execute("SELECT json_valid('{}')").fetchone()[0] == 1
    except sqlite3.Error:
        return False


def _agent_wanted(root) -> bool:
    """The memory-agent switch itself: agent.enabled() also reads as off when the claude CLI is missing."""
    return config.switch(root, "MEMCODE_TRANSCRIPT_CAPTURE", "transcript_capture", True)


def _new_errors(root) -> tuple[int, str]:
    """Errors logged since the last time they were reported: (how many, the newest line). Marks them reported."""
    p = _error_log(root)
    try:
        size = os.path.getsize(p)
    except OSError:
        return 0, ""
    seen = config.read(root).get("errors_seen", 0)
    seen = seen if isinstance(seen, int) and seen <= size else 0       # the log was rotated: read it all
    if size == seen:
        return 0, ""
    with open(p, errors="replace") as fh:
        fh.seek(seen)
        lines = [l.strip() for l in fh.read().splitlines() if l.strip()]
    config.write(root, errors_seen=size)
    return len(lines), (lines[-1] if lines else "")


def at_start(con, root) -> list[str]:
    """Messages for the user at session start (empty when all is well). Never raises."""
    out = []
    try:
        cfg = config.read(root)
        if not cfg.get("welcomed"):
            out.append(WELCOME)
            config.write(root, welcomed=True)
        if not _json_ok():
            out.append("memcode: this Python's SQLite has no JSON functions, so memories cannot be stored; use a "
                       "python3 built with a newer SQLite (3.38+, or JSON1 enabled).")
        if _agent_wanted(root) and not shutil.which("claude"):
            out.append("memcode: the memory agent is on but the `claude` CLI is not on PATH for hooks, so nothing is "
                       "learned from the conversation; add it to PATH, or turn the agent off with "
                       "/memcode:cli config memory-agent off.")
        n, last = _new_errors(root)
        if n:
            out.append(f"memcode logged {n} error{'s' * (n != 1)} since the last session (newest: {last[:200]}); "
                       f"details in {_error_log(root)}, or run /memcode:cli doctor.")
    except Exception:  # noqa: BLE001  the checks must never break the session
        pass
    return out


def checks(con, root) -> list[tuple[str, str, str]]:
    """Every check: [(ok | warn | fail, what, detail)]."""
    from . import agent, retrieval
    res = []
    v = sys.version_info
    res.append(("ok", "python", f"{sys.executable} {v.major}.{v.minor}.{v.micro}"))
    res.append(("ok", "sqlite", f"{sqlite3.sqlite_version} with JSON") if _json_ok() else
               ("fail", "sqlite", f"{sqlite3.sqlite_version} without JSON functions: memories cannot be stored"))
    d = str(store.memdir(root))
    res.append(("ok", "store", d) if os.access(d, os.W_OK) else ("fail", "store", f"{d} is not writable"))
    if _agent_wanted(root):
        cli = shutil.which("claude")
        res.append(("ok", "memory agent", f"on, claude CLI at {cli}") if cli else
                   ("fail", "memory agent", "on, but the `claude` CLI is not on PATH: nothing is learned from the "
                    "conversation (or turn it off: memcode config memory-agent off)"))
        h = agent.health(con)
        if h:
            res.append(("warn", "memory agent", h))
    else:
        res.append(("warn", "memory agent", "off: memcode learns only from pattern triggers (memcode config "
                    "memory-agent on)"))
    res.append(("ok", "recall", "on: per prompt and after each command or edit") if retrieval.enabled(root) else
               ("warn", "recall", "off: memories arrive only at session start and first touch (memcode config "
                "retrieval on)"))
    row = con.execute("SELECT MAX(ts) FROM injections WHERE source='pinned'").fetchone()
    res.append(("ok", "hooks", "the session-start hook has delivered memory here") if row and row[0] else
               ("warn", "hooks", "no session start recorded in this repository yet: if Claude Code was restarted "
                "after installing, check /plugin that memcode is enabled"))
    try:
        size = os.path.getsize(_error_log(root))
        with open(_error_log(root), errors="replace") as fh:
            last = [l.strip() for l in fh.read().splitlines() if l.strip()][-1:]
        res.append(("warn", "errors", f"{_error_log(root)} ({size} bytes); newest: {last[0][:200] if last else ''}"))
    except OSError:
        res.append(("ok", "errors", "none logged"))
    return res
