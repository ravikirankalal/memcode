# Architecture: a memory agent beside the coding agent

memcode is a memory agent that runs alongside a coding agent (Claude Code, Codex CLI, Gemini CLI). The coding agent
does the work. The memory agent decides what to remember, keeps that memory true, and hands the right piece of it to
the coding agent at the moment it matters. It never edits code and never talks to the user.

It has three duties. Every module belongs to one of them, or to the plumbing they share.

## 1. Extract: notice what is worth remembering

| Module | What it does | Cost and timing |
|---|---|---|
| `triggers.py` | Pattern triggers on hook events: a user correction, a fail-then-fix, a revert, retried commands, dependency changes. | Instant, free, every event |
| `facts.py` | Keyed facts from what the agent runs and the repo declares: test, build and lint commands with pass/fail counts, missing tools, languages. | Instant, free, every command |
| `agent/` | The model-backed memory agent. After each turn it reads the new part of the session log, collects candidates of every kind (rules, workflows, pitfalls, environment, design, decisions), rates them, and proposes add, update and retire operations. | A detached worker, about $0.004 per piece of log on Haiku, per-session budget |

## 2. Store: keep memory correct

| Module | What it does |
|---|---|
| `store.py` | The SQLite store, shared by every checkout of a repository, and root resolution. |
| `agent/curate.py` | Applies the agent's operations after the checks in `agent/checks.py`: evidence quoted from the log, rules and decisions only from the user's words, no requests for now, no repeats. Logs every change (`memcode history`); handles decisions' subjects and expiry. |
| `tree.py`, `symbols.py` | The repository map; staleness by file or Python symbol hash; re-anchoring on renames. |
| `scope.py` | Where a memory applies: repo, folder, file or symbol. |
| `consolidate.py`, `budget.py`, `labels.py` | Optional maintenance: group redundant notes, cap the store size, topic labels for filtering (`maintenance.py` runs them at session start). |
| `salience.py`, `outcomes.py` | How costly a memory was to learn (used by the default "split" ranking); outcome tracking (shadow). |

## 3. Trigger: deliver memory at the right moment

| Moment | Module | What the coding agent gets |
|---|---|---|
| Session start | `engine.session_start` → `pinned.py` | Your rules (as instructions), then the map, decisions, facts and notes (as data) |
| Each prompt | `engine.prompt` → `retrieval.py` | The few notes most relevant to this request |
| First read of a folder | `engine.touch` → `scope.py` | That folder's rules and notes |
| First write into a folder | `engine.before_write` → `scope.py` | The write is held once, with the folder's unseen rules as the reason |
| Any time | `mcp_server.py` | `memory_search`, `memory_add`, `memory_pinned`, `memory_facts` tools |
| Status bar | `activity.py` → `mods/memcode-status` | What was saved, recalled, held or scanned, and any problem |

## Plumbing

`hook_cli.py` and `adapters.py` turn each agent's hook payloads into engine calls. `config.py` owns
`.memcode/config.json` and the on/off switches. `cli.py`, `export_rules.py` and `setup.py` are the user-facing
commands and the wiring for other agents. `redact.py` masks secrets before anything is stored.

Benchmark-only switches (`MEMCODE_FRAMING=legacy`, `MEMCODE_RANK=salience`, `MEMCODE_CONSOLIDATE`) stay so past
results in `bench/live/RESULTS.md` can be rerun; they are not part of the product.

## Cleanup plan (2026-10-20)

1. `config.py`: one module for `.memcode/config.json` and the env-over-config-over-default switches, replacing the
   copies in model capture, retrieval, scope and the scanner.
2. Retire `model_capture.py`: the memory agent reads every user turn in context, which supersedes classifying single
   prompts. Remove the module, its hook queue, CLI switch, table use, tests and benchmark arm.
3. Split `transcript_capture.py` (786 lines) into the `memcode/agent/` package: `transcript.py` (reading the session
   log), `model.py` (role prompt, schema, briefing, model call), `checks.py` (evidence and safety checks),
   `curate.py` (applying operations, decisions, expiry), `worker.py` (queue, budget, worker, health). Call it the
   memory agent everywhere users see it: `memcode config memory-agent on|off` (`transcript-capture` and
   `MEMCODE_TRANSCRIPT_CAPTURE` keep working).
4. Clear names: `triggers.one_off` becomes `now_request` (a request for now), `facts.one_off` becomes
   `one_off_command`; drop the unused `pinned.approx_tokens`.
5. `engine.py` documented as the delivery side; module docstrings point at this page.
6. Tests and benchmarks follow the moves; the full suite and the mod tests pass after every step, and each step is
   its own commit.
