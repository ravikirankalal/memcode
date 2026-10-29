# Plan

Keep this file current: update it whenever the direction or the next steps change. What exists today is in
[`STATE.md`](STATE.md); how the code is laid out is in [`docs/architecture.md`](docs/architecture.md).

## Vision

A memory agent that runs alongside the coding agent and assists it in a timely manner. The coding agent does the work;
the memory agent takes care of memory, end to end:

- **Extract**: notice what is worth remembering, as it happens: your rules and decisions, how to build, test and release
  here, pitfalls hit and how they were fixed, how the environment behaves, design decisions and their reasons.
- **Store**: keep that memory true: one store per repository, no repeats, outdated items updated or retired, notes tied
  to the code they describe, every change logged.
- **Trigger**: hand the coding agent the right memory at the right moment: before it makes a mistake it has made before,
  not only at session start.

Principles: the user's words are the only source of rules and decisions; every memory carries evidence; the memory
agent never edits code or talks to the user; a failure in memcode never blocks the coding agent; it uses the user's own
`claude` login and stays within a small per-session budget.

## Roadmap

| Phase | Role | Duty | Status |
|---|---|---|---|
| 1 | Scribe: a running conversation beside the session; reads each turn (including the code read and written), collects and rates candidates of every kind, keeps the best, builds the project profile | Extract | Done (0.9–0.14); stabilizing |
| 2 | Guardian: watches the coding agent's actions as they happen and steps in before a known mistake | Trigger | Next |
| 3 | Auditor: checks stored notes against the code and the log, retires what is no longer true | Store | Planned |
| 4 | Librarian: merges near-duplicates, keeps the store small and well organized | Store | Planned |
| 5 | Briefer: a task-specific briefing when a new task starts, instead of a fixed start block | Trigger | Planned |

## Released: flat memory graph (0.15.0)

One kind of memory instead of rules, notes, facts and decisions. Each memory has its text, where it came from, a
`from_user` flag (quoted from the user's words: delivered as an instruction; everything else as information), an
optional topic (workflow, stack, component, domain, ...: display and search only), an importance, a key for memories
updated in place (what were facts; decision subjects), an optional expiry (what were decisions), a local vector and
links to related memories. Embeddings are local and stdlib (hashed TF-IDF over words, identifiers and paths); the
graph's links come from shared files and folders, close vectors, and the memory agent, which proposes them.

1. Schema and migration (from_user, topic, importance, key, expires_at, stats; memory_links, memory_vectors).
2. One rule concept: every "is this a rule" check becomes from_user.
3. Facts become keyed memories; the facts table is migrated and dropped.
4. embed.py (vectors) and graph.py (links).
5. One delivery: From you, then Memory ranked by importance and connections, then the map; per-prompt recall by
   vector search plus one hop on the graph; first contact with a folder brings its memories and their neighbours.
6. The memory agent's output is flat: add / update / retire a memory, with from_user, topic, importance, links, expiry.
7. CLI, MCP, status bar, docs, a live check.

## Released: inference kinds as a running list (0.15.0)

`memcode/kinds.py` is the list of what the memory agent looks for; the prompt, the output topics and the profile
floor are built from it. Added: infra, deployment, branching, location (important docs and scripts), reference
(important links), and an `unusual` flag for whatever differs from the usual way for this kind of project.

Candidates to add next (one line each in kinds.py, then a live check): ownership (CODEOWNERS, who reviews what),
feature flags (where they live, how they are toggled), configuration and secrets (where settings come from, which env
vars matter, never the values), API contracts (public endpoints, versioning, generated clients), data model (key
tables and schema migrations), local setup (what a fresh machine needs), monitoring and alerting (what pages whom),
performance budgets, test data and fixtures, release cadence.

## Released: recall beyond the prompt (0.16.0)

Per-prompt recall also reads the recent conversation; memories about a command or an edit come back right after it;
the memory agent flags memories for the coding agent's next step (`recall`), delivered with the reason; a start-block
memory may come back once when it becomes clearly relevant.

## On the branch, not released: easier installation (0.17.0)

Hooks, MCP and the worker never import from the user's repository; Python 3.9 is enough (checked, with one clear
message when older); `memcode doctor` and session-start notices (welcome once, a missing `claude` CLI, errors
logged); recall on by default; the first session reads the repository once for the project profile.

Still open for installation:
- **A public marketplace listing**, so people install without adding this repository first. Needs a submission to
  that marketplace's maintainers. The entry, from `.claude-plugin/marketplace.json`: name `memcode`, source
  `github: ravikirankalal/memcode`, category productivity, description "A memory agent beside Claude Code: it
  extracts what is worth remembering, keeps it true, and delivers it when it matters." (and `memcode-status`, source
  `./mods/memcode-status` in this repository).
- **Windows**: the hook commands no longer use shell-only syntax (`python3 "${CLAUDE_PLUGIN_ROOT}/bin/memcode" hook
  X`), but `python3` is often `python` or `py` there, and nothing has been run on Windows yet.

## Next steps

1. **Guardian, first slice**: at `PreToolUse` for Bash, match the command against facts and pitfalls (for example
   `pytest` in a repo whose tests only run through `make check`) and add a one-line reminder before it runs. Recall
   after the action (0.16) comes one step late for a command that should not run at all.
2. **A small recall check that ships with the repo**: the benchmarks were removed in 0.12; a short, offline-replayable
   check of the memory agent (a fixed log, its expected memories, the model call mocked or recorded) so prompt changes
   can be judged without a paid run.
3. **Auditor, first slice**: when a note's file changes, ask the memory agent whether the note still holds (update or
   retire) instead of only marking it stale.
4. Near-duplicate merging (Librarian) once the store grows enough to need it.

## Open questions

- How much should the Guardian interrupt? A reminder next to the tool call, or a held call like the first-write hold?
- Per-checkout repo maps, so two sessions on different branches never flip a note between fresh and stale.
- Whether per-prompt recall (`retrieval`) should be on by default.
