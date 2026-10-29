---
description: "memcode: run any memcode command (help, show, add, edit, history, fact, config, export...)"
argument-hint: "<command> [args]"
allowed-tools: Bash(python3:*)
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/bin/memcode" $ARGUMENTS`

Show the output above to the user exactly as printed, in a code block. Do not run other commands unless the user asks.
