---
description: "memcode: list stored memories (add --all for stale ones)"
argument-hint: "[--all]"
allowed-tools: Bash(python3:*)
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/bin/memcode" list $ARGUMENTS`

Show the output above to the user exactly as printed, in a code block. Do not run other commands unless the user asks.
