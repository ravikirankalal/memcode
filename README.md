# memcode

A memory agent for Claude Code. It runs beside the coding agent, notices what is worth remembering (your rules, how
to build and test the repo, pitfalls hit and fixed, decisions about ongoing work), keeps that memory true as the code
changes, and hands the right piece of it to the agent at the moment it matters.

A Claude Code plugin. Stdlib-only Python; memory is stored locally, per repository.

## Install

You need **Claude Code** and **`python3`** 3.11 or newer on macOS or Linux (no packages to install). In Claude Code:

```text
/plugin marketplace add ravikirankalal/memcode
/plugin install memcode@memcode
```

Restart Claude Code. memcode now works in every repo you open; memory lives in `<repo>/.memcode/`, kept out of git.

Recommended: per-prompt recall, so each prompt gets the memories relevant to it: `/memcode:cli config retrieval on`.

Update with `/plugin marketplace update memcode` then `/plugin update memcode@memcode`. To try a checkout instead:
`claude --plugin-dir /path/to/memcode`.

## What it does

**Extract.** Pattern triggers catch what is plain from single events: you correct the agent, an edit is reverted, a
failing command passes after a fix, a command is retried, dependencies change. The memory agent works beside the
session as a running conversation: briefed when the coding agent starts, it reads each turn as it finishes and collects
what patterns miss: rules you state as description, workflows that work, pitfalls
written as their fix, how the environment behaves, design decisions, and the state of ongoing work you decide ("G16 is
parked until the end"). It rates every candidate and keeps the best few, and only what passes its checks: quoted
evidence, your own words for rules and decisions, no requests for right now, no repeats. Facts track the commands that
actually work here and the tools that are missing.

**Store.** One store per repository, shared by its worktrees. Notes about code go stale when that code changes and are
re-anchored across renames; the memory agent updates or retires what is no longer true, and every change it makes is in
`memcode history`. Rules and notes apply where they belong: a rule about `billing/` is for work in `billing/`.

**Trigger.** At session start the agent gets your rules as instructions, then a compact repo map, decisions, facts and
notes as data. On each prompt it gets the few memories relevant to that prompt. The first time it reads a folder it gets
that folder's rules; if its first contact is a write, the write is held once with the rules as the reason. It can also
ask for memory any time through MCP tools.

## Try it

Tell the agent something it could not infer: *"No - in this repo tests go in `checks/`, never `tests/`."* Start a new
session and ask where tests go.

```text
/memcode:status                  what is stored; memory-agent problems
/memcode:list                    memories (add --all to include stale ones)
/memcode:facts                   build/test/run commands, environment limits, fragile areas
/memcode:forget 3                delete memory #3
/memcode:cli                     every other command: show, add, history, config, export, why...
```

From a terminal, the same CLI is `bin/memcode` in the plugin directory:

```bash
alias memcode='python3 "$(ls -d ~/.claude/plugins/cache/memcode/memcode/*/ | sort -V | tail -1)bin/memcode"'
```

### Status above the prompt (optional mod)

```text
◆ memcode 37 memories · 12 rules · 9 facts  ┃  🧠 SAVED  rule: Always use tabs in this repo. · 5s ago  🔍 reading..  +2 saved
```

One line above the prompt: what memcode holds; the latest thing it did, as a coloured badge (`🧠 SAVED`, `✏️ UPDATED`,
`🗑 RETIRED`, `💡 RECALLED`, `📂 FOLDER RULES`, `✋ HELD`, `🚀 LOADED`), or `⚠ PROBLEM` / `💸 BUDGET` when the memory
agent needs attention; the memory agent's state (`🔍 reading...` while it reads a turn, else when it last read one);
and what this session added. On a narrow terminal the tally, the agent's state and the count labels give way first.
`/memcode-status` prints the same as a short dashboard with the last 8 events. Install it with
`/plugin install memcode-status@memcode`.

## Privacy and cost

After each turn the memory agent sends the new part of the session log to a model through your own `claude` login,
the same provider the coding agent already sent it to (Haiku by default, about $0.004 per 24,000 characters of log, at
most $0.50 per session). Everything memcode stores stays local, in `.memcode/`. Turn the memory agent off with
`/memcode:cli config memory-agent off`.

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
