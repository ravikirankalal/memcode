---
description: "memcode: what is stored, per-session counters, and facts"
allowed-tools: Bash(python3:*)
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/bin/memcode" stats && python3 "${CLAUDE_PLUGIN_ROOT}/bin/memcode" sessions -n 5`

Show the output above to the user exactly as printed, in a code block. Do not run other commands unless the user asks.
