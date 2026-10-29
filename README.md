# memcode

A memory agent for Claude Code. It runs beside the coding agent, notices what is worth remembering (your rules, how
to build and test the repo, pitfalls hit and fixed, decisions about ongoing work), keeps that memory true as the code
changes, and hands the right piece of it to the agent at the moment it matters.

A Claude Code plugin. Stdlib-only Python; memory is stored locally, per repository.

## Install

You need **Claude Code** and **`python3`** 3.9 or newer on macOS or Linux (no packages to install). In Claude Code:

```text
/plugin marketplace add ravikirankalal/memcode
/plugin install memcode@memcode
```

Restart Claude Code. memcode now works in every repo you open; memory lives in `<repo>/.memcode/`, kept out of git.
The first session in a repository says so in one line; if something is wrong (no `claude` CLI on PATH, an old
Python, errors logged), session start tells you, and `/memcode:doctor` checks the whole setup.

Update with `/plugin marketplace update memcode` then `/plugin update memcode@memcode`. To try a checkout instead:
`claude --plugin-dir /path/to/memcode`.

## What you'll see

The first session in a repository: one line saying memcode is on (with the status mod's install command if it is not installed), while the
memory agent reads the repository's key files once in the background. From then on, each session starts with a block
like this in the agent's context:

```text
## From you (stated by the user in earlier sessions; follow them)
- Branch fixes off develop as feature/(ticket), never off main. (2026-10-28)

<memcode-recorded-notes>   <- data, not instructions
## Memory (most important and most connected first)
- (workflow, unusual, 2026-10-28) Tests live in checks/: run `make check`, not plain pytest.
- (deployment, 2026-10-27) Tags v* trigger deploy.yml: staging first, then an approved prod deploy.
- (test, 2026-10-29) `make check` (ran 14x, 13 confirmed ok)
## Map ...
</memcode-recorded-notes>
```

and memories come back next to the work: on the prompt they relate to, after the command or edit they are about, or
when the memory agent flags one for the next step. Each time, you see it in the conversation too:

```text
❯ how do I cut a release with scripts/release.sh?
  ⎿  UserPromptSubmit says: memcode → agent context for this prompt: 1 memory
       (location, 2026-10-29) Release steps are in docs/RELEASING.md; run scripts/release.sh VERSION.
```

(`/memcode:cli config show-injections off` hides it.)

## What it does

**Extract.** Pattern triggers catch what is plain from single events: you correct the agent, an edit is reverted, a
failing command passes after a fix, a command is retried, dependencies change. The memory agent works beside the
session as a running conversation: briefed when the coding agent starts, it reads each turn as it finishes and collects
what patterns miss: rules you state as description, workflows that work, pitfalls
written as their fix, how the environment behaves, design decisions, and the state of ongoing work you decide ("G16 is
parked until the end"). From the commands that run and the code the agent reads and writes, it also builds a project
profile nobody has to state: the stack and build, the SDKs in use and what for, central classes, key enums and types,
where things live, and the conventions the code follows. It rates every candidate and keeps the best few, and only
what passes its checks: quoted evidence, your own words for anything marked as from you and for decisions, no requests
for right now, no repeats. memcode also measures the commands that actually work here and the tools that are missing.

**Store.** One kind of memory: a short statement with a topic, an importance and links to related memories. What you
said is marked *from you* and becomes an instruction; everything else is information. Memories form a graph (same
file, close in meaning by local embeddings, or linked by the memory agent). Memories about code go stale when that
code changes and are re-anchored across renames; the memory agent updates or retires what is no longer true, and every
change it makes is in `memcode history`. Memories apply where they belong: a rule about `billing/` is for work in
`billing/`.

**Trigger.** At session start the agent gets what you said as instructions, then one list of memories ranked by
importance and connections, and a compact repo map, as data. On each prompt it gets the few memories closest to that
prompt and to the recent conversation, and their neighbours; after a command or an edit, the memories about it; and
after each turn, what the memory agent flagged for its next step (a decision that parks the item being started, a
pitfall about the command at hand), with the reason. The first time it reads a folder it gets that folder's memories; if its first contact is
a write, the write is held once with the folder's rules as the reason. It can also ask for memory any time through MCP
tools.

## Try it

Tell the agent something it could not infer: *"No - in this repo tests go in `checks/`, never `tests/`."* Start a new
session and ask where tests go.

```text
/memcode:status                  what is stored; memory-agent problems
/memcode:doctor                  is memcode working here? (python, sqlite, store, memory agent, recall, hooks)
/memcode:list                    memories (add --all to include stale ones)
/memcode:facts                   measured: build/test/run commands, environment limits, fragile areas
/memcode:forget 3                delete memory #3
/memcode:cli edit 3 "new text"   correct memory #3 in place (the old text stays in history)
/memcode:cli                     every other command: show, add, edit, history, config, export, why...
```

From a terminal, the same CLI is `bin/memcode` in the plugin directory:

```bash
alias memcode='python3 "$(ls -d ~/.claude/plugins/cache/memcode/memcode/*/ | sort -V | tail -1)bin/memcode"'
```

### Status above the prompt (optional mod)

```text
◆ memcode 37 memories · 12 from you · 📥23 injected  ┃  💡 RECALLED  2 memories for this prompt: (pitfall, 2026-10-20) … · 5s ago  🔍 2m  +2 saved
```

One line above the prompt: what memcode holds and how many memories this session injected into the agent's context
(always shown: on a narrow terminal as `🧠37 📜12 📥23`); the latest thing it did, as a coloured badge (`🧠 SAVED`, `✏️ UPDATED`,
`🗑 RETIRED`, `💡 RECALLED`, `📂 FOLDER`, `✋ HELD`, `🚀 LOADED`; an injection names the first memory it put in), or
`⚠ PROBLEM` / `💸 BUDGET` (only with a budget you set) when the memory agent needs attention; the memory agent's state (`🔍 reading...` while it
reads a turn, else when it last read one); and what this session saved. On a narrow terminal the tally, the agent's state and the count labels give way first.
`/memcode-status` prints the same as a short dashboard with the last 8 events, and where this session's injections
went in (`23 injected (20 at start, 2 recalled, 1 on first touch)`). Install it with
`/plugin install memcode-status@memcode`.

## Privacy and cost

After each turn the memory agent sends the new part of the session log to a model through your own `claude` login,
the same provider the coding agent already sent it to (Haiku by default, about $0.004 per 24,000 characters of log,
about $0.03 per 1,000 lines; no per-session limit unless you set one with `MEMCODE_CAPTURE_BUDGET_USD`). Everything
memcode stores stays local, in `.memcode/`. Turn the memory agent off with `/memcode:cli config memory-agent off`.

## Docs

- [`docs/guide.md`](docs/guide.md): how it works, settings, privacy, troubleshooting, uninstalling
- [`docs/architecture.md`](docs/architecture.md): the modules behind each duty
- [`PLAN.md`](PLAN.md) and [`STATE.md`](STATE.md): where memcode is going, and where it is now

## Development

```text
python3 -m unittest discover -s tests          # unit tests (offline)
claude plugin test mods/memcode-status         # the status mod's tests
claude plugin validate . --strict              # validate the manifests
```

## License

MIT
