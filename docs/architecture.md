# Architecture: a memory agent beside the coding agent

memcode is a memory agent that runs alongside the coding agent (Claude Code). The coding agent
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
| `salience.py`, `outcomes.py` | How costly a memory was to learn (a restated rule, a recurring failure), used to give such memories extra slots in per-prompt recall; outcomes record verified successes and repeats. |

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

`hook_cli.py` turns Claude Code's hook payloads into engine calls. `config.py` owns `.memcode/config.json` and the
on/off switches. `cli.py` is the user-facing command (`/memcode:*`, `bin/memcode`).

The plan and the current state are in [`PLAN.md`](../PLAN.md) and [`STATE.md`](../STATE.md).
