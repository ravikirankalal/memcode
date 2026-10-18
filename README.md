# memcode

Memory for coding agents: when you correct the agent, it remembers the rule in the next session.
A Claude Code plugin. Stdlib-only Python; the store is local (see "What leaves your machine" below).

> **Status: early.** On frozen held-out benchmarks (one model, Haiku, small N), captured rules are followed as reliably as
> a hand-maintained `CLAUDE.md`, and per-prompt retrieval keeps context cost flat as the store grows; rules stated in
> plain descriptive language are caught by the transcript scanner (on by default since 0.9.0). Read
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
5. **Scopes** memories to where they apply (since 0.8.0): a rule about `billing/` reaches the agent when it works in
   `billing/`, instead of crowding every session. On a crowded store this took live benchmark mistakes from 24/54 to
   0/53 (bench/live/RESULTS.md, Run 15). `memcode config hierarchy off` (or `MEMCODE_HIER=0`) restores flat memory.
6. **Scans each finished turn** (since 0.9.0) for things the triggers miss: rules you state only as description ("every
   public function here starts with qx_") and pitfalls the agent discovers ("the checks only run through
   tools/ci/verify.sh"). Each item needs quoted evidence from the transcript; only your own words become rules. On an
   untuned benchmark this cut mistakes from 25/30 to 3/30, with every stored memory correct (Run 17).
7. **Keeps facts** about the repo: the test/build/lint commands that actually work here (confirmed from exit codes, or
   from the runner's summary line when the agent pipes output), missing tools, fragile folders.

Experimental, opt-in (see [docs/guide.md](docs/guide.md)): consolidation of repeated notes into lessons
(`MEMCODE_CONSOLIDATE=1`), a storage budget (`MEMCODE_STORE_BUDGET=N`), and topic labels for filtering.

In a simulated developer week (bench/live/RESULTS.md, Run 13) memcode cut convention mistakes from 19/24 to 5/24
without any effort from the user.

**What leaves your machine.** One thing, on by default since 0.9.0: after each turn, memcode's transcript scanner sends
a condensed, redacted summary of that turn (your messages, the agent's replies, commands with their result and output
tail, files written) to a model through your own `claude` login, to find conventions and pitfalls the triggers miss
(Haiku by default, about $0.001 per turn). Everything else stays local in `.memcode/`. Turn the scanner off with
`memcode config transcript-capture off` (per repo) or `MEMCODE_TRANSCRIPT_CAPTURE=0`; it is also off wherever the
`claude` CLI is not installed. Review what it saved with `/memcode:list` and remove anything with `/memcode:forget`.

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

### Status above the prompt (optional mod)

`memcode-status` adds a line above Claude Code's prompt showing what memcode holds and what it just did:

```text
memcode 37 memories · 12 rules · 9 facts  │ + rule: Always use tabs for indentation in this repo. 5s ago
```

It updates whenever a memory is saved (`+`), recalled for a prompt (`↻`), injected when the agent opens a file (`→`),
or when a first write is held for a folder's rules (`⏸`); after ten quiet minutes it shows the counts only. Install it
from the same marketplace:

```text
/plugin install memcode-status@memcode
```

It reads `.memcode/activity.json`, which memcode keeps up to date (the last 20 events and the counts).

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
