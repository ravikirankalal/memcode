# memcode

Memory for coding agents: when you correct the agent, it remembers the rule in the next session.
A Claude Code plugin. Local-first, stdlib-only Python.

> **Status: early.** On frozen held-out benchmarks (one model, Haiku, small N), captured rules are followed as reliably as
> a hand-maintained `CLAUDE.md`, and per-prompt retrieval keeps context cost flat as the store grows; rules stated in
> plain descriptive language are still missed unless opt-in model capture is on. Read
> [`bench/live/RESULTS.md`](bench/live/RESULTS.md) before relying on it.

## Install

You need **Claude Code** and **`python3`** 3.11 or newer (tested on 3.11, 3.12 and 3.13; no packages to install) on macOS or Linux.
Native Windows is untested.

In Claude Code, run:

```text
/plugin marketplace add ravikirankalal/memcode
/plugin install memcode@memcode
```

Restart Claude Code. That's it: memcode starts working in every repo you open. Memory is stored per repository in
`<repo>/.memcode/`, which memcode keeps out of git (it adds itself to `.git/info/exclude`). Nothing leaves your
machine unless you turn on the optional model capture.

Recommended: also turn on per-prompt retrieval (each prompt then gets the memories relevant to it) by running
`/memcode:cli config retrieval on` in Claude Code.

Update later with `/plugin marketplace update memcode` then `/plugin update memcode@memcode`; uninstall with
`/plugin uninstall memcode@memcode`. To try a checkout instead: `claude --plugin-dir /path/to/memcode`.
Codex CLI or Gemini CLI: see [Other agents](docs/guide.md#other-agents-codex-cli-and-gemini-cli).

## What it does

1. **Captures** a memory when something observable happens: you correct the agent ("No, always use X"), a revert of its
   edit, a failing command that later passes, a retried command, or a dependency/config change.
2. **Injects** at session start (and after compaction): your stated rules as *project rules*, then a compact repo map and
   recorded notes under a hard token cap. Agent-derived notes are labelled as untrusted data.
3. **Expires** memories tied to code that changed (staleness), and re-anchors them across renames.
4. **Shares** what you choose with your team: `memcode share ID` writes it to `.memcode-team.jsonl`, which you commit
   and review like any change; teammates' agents pick it up after the merge. Nothing is shared automatically.

Nothing is sent anywhere: no network access, no extra model calls.

## Try it

In a repo, tell the agent something it could not infer: *"No - in this repo tests go in `checks/`, never `tests/`."*
Start a new session and look at the injected rules, or ask the agent where tests go.

Inspect and control what is stored, from inside Claude Code:

```text
/memcode:status                  what is stored, per-session counters
/memcode:list                    memories (add --all to include stale ones)
/memcode:facts                   facts: build/test/run commands, environment limits, fragile areas
/memcode:why 3                   why memory #3 ranks where it does
/memcode:forget 3                delete memory #3
/memcode:cli                     every other command: show, add, team, share, fact set, config, export...
```

From a terminal, the same CLI is `bin/memcode` in the plugin directory. A shell alias that always points at the
installed version:

```bash
alias memcode='python3 "$(ls -d ~/.claude/plugins/cache/memcode/memcode/*/ | sort -V | tail -1)bin/memcode"'
memcode list          # run inside a repo
```

The agent also gets four MCP tools: `memory_search`, `memory_add`, `memory_pinned`, `memory_facts`, and can run
`memcode` directly (the plugin's `bin/` is on its PATH).

## Docs

- [`docs/guide.md`](docs/guide.md): how it works, what is stored, privacy, troubleshooting, uninstalling
- [`bench/live/RESULTS.md`](bench/live/RESULTS.md): benchmark runs, including the negative ones
- [Learnings](https://claude.ai/code/artifact/b7422ec1-b0ee-4e73-993f-aec9d242d87b): what works, what failed and why, method and engineering lessons, open questions (kept up to date)
- [`docs/decisions/`](docs/decisions): design decisions (e.g. why not Serena)

## Development

```text
python3 -m unittest discover -s tests          # unit tests (offline)
python3 bench/live/run.py --dry-run            # live benchmark plan (real runs cost money)
claude plugin validate . --strict              # validate the manifests
```

Layout: `memcode/` (store, triggers, redact, tree, salience, pinned, hook_cli, mcp_server, cli), `hooks/hooks.json`,
`.claude-plugin/` (plugin and marketplace manifests), `bench/` (offline and live benchmarks).
Salience scoring is computed and logged but **not** used for ranking; that stays gated on the benchmark.

Companion tools: [Serena](https://github.com/oraios/serena) works well beside memcode with its own memory feature
disabled (one memory store); we do not depend on it. See `docs/decisions/0001-serena-not-integrated.md`.

## License

MIT
