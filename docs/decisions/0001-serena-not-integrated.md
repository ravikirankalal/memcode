# 0001: Do not integrate Serena (revisit only for symbol-level anchors)

Status: decided, 2026-10-07. Sources: [Serena README](https://github.com/oraios/serena), [Serena memories doc](https://github.com/oraios/serena/blob/main/docs/02-usage/045_memories.md). Serena's tools page was unreachable from the research environment, so its tool list is from the README only.

## Decision
Serena is not a dependency or integration target. It is a possible companion the user installs separately.

## What we learned
- Serena is an MCP toolkit for symbol-level retrieval and editing (find symbol, references, replace symbol body, rename) over language servers, 40+ languages. Its memory is hand-written Markdown in `.serena/memories/`: no event capture, anchoring, staleness, salience or token budget.
- Overlap with memcode is near zero. Its only fit is `tree.py`: symbol-level anchors instead of file hashes.
- Costs of integrating: the app is GPL-3.0-or-later (SolidLSP alone is MIT); it needs `uv` and Python 3.13; language servers may download at runtime; cold start is too slow for short-lived hooks. All of this breaks the stdlib-only, local-first design. Two memory stores would also confuse the agent.

## If symbol-level staleness proves valuable later
Prototype function-level hashes in `tree.py` using stdlib `ast` (Python) or `git diff` hunk headers, behind an optional extra. No Serena dependency.

## Companion use
Serena beside memcode works with Serena's memory feature disabled: Serena for navigation and edits, memcode for captured lessons.
