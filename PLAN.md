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

## Next steps

1. **Guardian, first slice**: at `PreToolUse` for Bash, match the command against facts and pitfalls (for example
   `pytest` in a repo whose tests only run through `make check`) and add a one-line reminder before it runs. Today the
   only timely trigger is the held first write into a folder.
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
