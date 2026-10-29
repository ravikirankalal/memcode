"""What memcode put into the coding agent's context, shown to the user too (the hook's systemMessage).

additionalContext reaches only the agent; Claude Code shows a hook's systemMessage in the conversation. Each
injection gets a short copy: one line saying when and how much, then one clipped line per memory (the map and the
untrusted-data framing are left out). Off with `memcode config show-injections off` (MEMCODE_SHOW_INJECTIONS=0).

Surfaces that draw no hook message (the mobile and web apps) see a memory in the agent's reply instead: each injected
block ends with MENTION, asking the agent to name, in one "memcode:" line, a memory its answer relied on. Off with
`memcode config mention-memories off` (MEMCODE_MENTION=0).
"""
from __future__ import annotations

import os

from . import config, pinned

WIDTH = 140
MAX_LINES = 25
WHEN = {"start": "at session start", "prompt": "for this prompt", "tool": "after this tool call"}
# memcode's own words to the coding agent, after the block (outside the untrusted wrapper): the agent's reply is the one
# thing every surface shows (the mobile and web apps draw no hook message), so a memory that mattered is named there
MENTION = ("memcode: when your answer or your next step relies on one of the memories above, say so first, in one short "
           "markdown quote line starting with \"> memcode:\" (for example: > memcode: tests run with `make check` here). "
           "Do not mention memories you did not use.")
# the terminal draws a hook's systemMessage in dim grey and keeps ANSI colours (markdown is shown literally): a bold
# cyan header, a cyan bar down the left so the copy reads as one block, the user's own words in magenta
CYAN, BOLD_CYAN, MAGENTA, RESET = "\x1b[36m", "\x1b[1;36m", "\x1b[35m", "\x1b[0m"
BAR = "│ "


def colored() -> bool:
    """ANSI colours unless NO_COLOR is set (https://no-color.org) or MEMCODE_COLOR=0."""
    return not os.environ.get("NO_COLOR") and os.environ.get("MEMCODE_COLOR", "1").lower() not in ("0", "false", "off")


def enabled(root) -> bool:
    return config.switch(root, "MEMCODE_SHOW_INJECTIONS", "show_injections", True)


def mention_enabled(root) -> bool:
    return config.switch(root, "MEMCODE_MENTION", "mention_memories", True)


def render(text: str, when: str, color: bool = False) -> str:
    """The user's copy of an injected block ('' when it holds no memory); color: ANSI colours for the terminal."""
    lines, yours, other, in_map = [], 0, 0, False
    section = ""
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            in_map = line.startswith("## Map")
            section = "yours" if line.startswith(("## From you", pinned.RULES_HEADER)) else "other"
            continue
        if in_map or not line.startswith("- "):
            continue
        if section == "yours":
            yours += 1
            body = "from you: " + line[2:]
        else:
            other += 1
            body = line[2:]
        body = body if len(body) <= WIDTH else body[: WIDTH - 1] + "…"
        if color:
            body = (MAGENTA + body + RESET) if section == "yours" else body
            lines.append(CYAN + BAR + RESET + body)
        else:
            lines.append("  " + body)
    if not lines:
        return ""
    counts = ", ".join(p for p in (f"{yours} from you" if yours else "",
                                   f"{other} memor{'y' if other == 1 else 'ies'}" if other else "") if p)
    head = f"memcode → agent context {WHEN.get(when, when)}: {counts}"
    more = [f"  (+{len(lines) - MAX_LINES} more)"] if len(lines) > MAX_LINES else []
    if color:
        head = BOLD_CYAN + head + RESET
        more = [CYAN + BAR + RESET + m.strip() for m in more]
    return "\n".join([head] + lines[:MAX_LINES] + more)
