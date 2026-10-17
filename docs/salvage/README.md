# Salvaged work from the stopped hierarchical-memory agents (2026-10-17)

The multi-agent build of hierarchical memory was stopped by the user before it finished. Kept here so nothing is lost:

| file | what | state |
|---|---|---|
| `PLAN.md` | the design: flags, schema, ownership split | final |
| `BULLETIN.md` | the agents' shared log: decisions, interfaces, the "first touch" decision | final |
| `scope-hierarchy.patch` | `memcode/scope.py` + edits to triggers/retrieval/pinned/cli (MEMCODE_HIER) | unfinished, no own tests; existing suite passes |
| `consolidation-budget-labels.patch` | `memcode/consolidate.py`, `budget.py`, `labels.py` + salience/mcp_server edits | unfinished, no own tests; existing suite passes |

Both patches apply on top of commit b9c7754 (the shared schema, already merged): `git apply docs/salvage/<name>.patch`.
They are NOT applied to the plugin on purpose: untested, and labels would run at every session start.

Benchmark work from the testing agents was merged directly (it only adds files): `bench/live/hier1_candidates.py`,
`bench/consolidation_eval.py`, `bench/live/consol1_candidates.py`, `bench/precision/`, `bench/scorecard.py`, and the
unvalidated `bench/live/e2e1_*.py` / `e2e_run.py` (stopped mid-pilot).
