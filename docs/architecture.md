# Architecture: a memory agent beside the coding agent

memcode is a memory agent that runs alongside the coding agent (Claude Code). The coding agent
does the work. The memory agent decides what to remember, keeps that memory true, and hands the right piece of it to
the coding agent at the moment it matters. It never edits code and never talks to the user.

It has three duties. Every module belongs to one of them, or to the plumbing they share.

## The memory model

One kind of memory. Each is a short statement with where it came from (a correction, a revert, the memory agent, a
command measured, added by hand), a `from_user` flag (the user's own words: delivered as an instruction; everything
else is delivered as information), an optional topic (workflow, pitfall, design, decision, stack, component, ...), an
importance, an optional key (memories updated in place: what used to be facts, such as a command's pass/fail
counts), an optional expiry (decisions about ongoing work), a scope, a local vector and links to related memories.
Together the memories form a graph: links come from shared files, close vectors and the memory agent.

## 1. Extract: notice what is worth remembering

| Module | What it does | Cost and timing |
|---|---|---|
| `triggers.py` | Pattern triggers on hook events: a user correction, a fail-then-fix, a revert, retried commands, dependency changes. | Instant, free, every event |
| `facts.py` | Keyed memories measured from what the agent runs and the repo declares: test, build and lint commands with pass/fail counts, missing tools, languages. | Instant, free, every command |
| `agent/` | The model-backed memory agent, a running conversation per coding session (`agent/conversation.py`): opened with a full briefing when the coding agent starts, then resumed after each turn with the new part of the session log and what changed in the memory. It collects candidates of every topic (what the user wants, workflows, pitfalls, environment, design, decisions, the project profile), rates them, and proposes add, update and retire operations, each with `from_user`, a topic and links to related memories. | A detached worker, about $0.004 per piece of log on Haiku (less when the conversation is cached), per-session budget |

## 2. Store: keep memory correct

| Module | What it does |
|---|---|
| `store.py` | The SQLite store, shared by every checkout of a repository, and root resolution. |
| `agent/curate.py` | Applies the agent's operations after the checks in `agent/checks.py`: evidence quoted from the log, `from_user` memories and decisions only from the user's words, no requests for now, no repeats. Logs every change (`memcode history`); handles decisions' subjects and expiry; records the agent's links. |
| `embed.py` | Local embeddings, stdlib only: hashed TF-IDF vectors over words, identifier parts and paths, kept per memory and rebuilt when its text changes; `search`. |
| `feedback.py` | Whether the coding agent used each memory shown next to the work (a `memcode:` line in its reply); verdicts go to the memory agent; never-used memories stop being recalled. |
| `graph.py` | The memory graph: `same_file` and `similar` links rebuilt for new or changed memories, the agent's links kept; `neighbours`, `degree`. |
| `tree.py`, `symbols.py` | The repository map; staleness by file or Python symbol hash; re-anchoring on renames. |
| `scope.py` | Where a memory applies: repo, folder, file or symbol. |
| `salience.py`, `outcomes.py` | How costly a memory was to learn (a restated rule, a recurring failure), used to give such memories extra slots in per-prompt recall; outcomes record verified successes and repeats. |

## 3. Trigger: deliver memory at the right moment

| Moment | Module | What the coding agent gets |
|---|---|---|
| Session start | `engine.session_start` → `pinned.py` | What you said (as instructions), then one ranked list of memories (importance, connections, recalls, recency) and the map (as data) |
| Each prompt | `engine.prompt` → `retrieval.py` | The few memories closest to this request and the recent conversation (embedding cosine plus path boosts), and their strongest neighbours in the graph |
| After a command or an edit | `engine.tool_result` → `retrieval.for_action` | The memories closely related to what was just run or changed |
| Next prompt or tool call after a turn | `agent/curate.queue_recall` → `retrieval.flagged` | What the memory agent flagged for the next step, with its reason |
| First read of a folder | `engine.touch` → `scope.py` | That folder's memories and their neighbours |
| First write into a folder | `engine.before_write` → `scope.py` | The write is held once, with the folder's unseen rules as the reason |
| Any time | `mcp_server.py` | `memory_search`, `memory_add`, `memory_pinned`, `memory_facts` tools |
| Status bar | `activity.py` → `mods/memcode-status` | What was saved, recalled, held or scanned, and any problem |

## Plumbing

`hook_cli.py` turns Claude Code's hook payloads into engine calls. `config.py` owns `.memcode/config.json` and the
on/off switches. `cli.py` is the user-facing command (`/memcode:*`, `bin/memcode`).

The plan and the current state are in [`PLAN.md`](../PLAN.md) and [`STATE.md`](../STATE.md).
