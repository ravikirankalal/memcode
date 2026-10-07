# memcode

Memory for a coding agent: it stops repeating mistakes in a codebase it has seen before.
Phase 1 MVP of the plan ("Coding Agent Memory: Product Analysis"), as a Claude Code plugin. Stdlib-only Python 3.

| Piece | File |
|---|---|
| SQLite store (paths = tree spine, memories, shadow salience log) | `memcode/store.py` |
| Five triggers: correction, revert, fail_to_fix, retry, dep_change (state rebuilt from the events table per hook process) | `memcode/triggers.py` |
| Secret redaction before storage | `memcode/redact.py` |
| Repo scan, git-diff refresh, rename re-anchoring, staleness | `memcode/tree.py` |
| Salience (surprise/friction/fragility/confidence), logged in shadow mode only | `memcode/salience.py` |
| Pinned map + conventions + memories under a hard token cap | `memcode/pinned.py` |
| Hooks (SessionStart, UserPromptSubmit, PostToolUse, PreCompact) | `hooks/hooks.json`, `memcode/hook_cli.py` |
| MCP tools `memory_search`, `memory_add`, `memory_pinned` | `memcode/mcp_server.py` |
| Offline replay benchmark | `bench/` |

Data lives in `<repo>/.memcode/memory.db` (local-first; memcode adds `.memcode/` to the repo's `.git/info/exclude` and writes `.memcode/.gitignore`).

Test: `python3 -m unittest discover -s tests`. Benchmark: `python3 bench/run.py`
(a simulated agent: a harness smoke test, not evidence; the real benchmark with live agent runs is Phase 2).

Known limits: only the last 200 events per session inform trigger state; memories without a content hash never go stale;
pinned ordering uses retrieval counts, so regenerate only at session start/compaction to keep the prompt-cache prefix stable.

Companion tools: [Serena](https://github.com/oraios/serena) (symbol-level navigation/editing) works well beside memcode
with Serena's own memory feature disabled, so the agent has one memory store. We deliberately do not depend on it; see
`docs/decisions/0001-serena-not-integrated.md`.
