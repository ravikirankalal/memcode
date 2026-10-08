# memcode

Memory for coding agents: when you correct the agent, it remembers the rule in the next session.
A Claude Code plugin. Local-first, stdlib-only Python.

> **Status: early.** Capture works in real sessions. Whether it beats a plain `CLAUDE.md` is **not yet shown**: the first
> frozen held-out benchmark said no; a fix and a second held-out run are in progress. Read
> [`bench/live/RESULTS.md`](bench/live/RESULTS.md) before relying on it.

## Install

Requires Claude Code and `python3` on your PATH (tested on Python 3.13; no third-party packages).

```text
/plugin marketplace add ravikirankalal/memcode
/plugin install memcode@memcode
```

Restart Claude Code. Memory is stored per repository in `<repo>/.memcode/memory.db`; memcode adds `.memcode/`
to the repo's `.git/info/exclude`, so it is never committed.

To try it from a checkout instead: `claude --plugin-dir /path/to/memcode`.

## What it does

1. **Captures** a memory when something observable happens: you correct the agent ("No, always use X"), a revert of its
   edit, a failing command that later passes, a retried command, or a dependency/config change.
2. **Injects** at session start (and after compaction): your stated rules as *project rules*, then a compact repo map and
   recorded notes under a hard token cap. Agent-derived notes are labelled as untrusted data.
3. **Expires** memories tied to code that changed (staleness), and re-anchors them across renames.

Nothing is sent anywhere: no network access, no extra model calls.

## Try it

In a repo, tell the agent something it could not infer: *"No - in this repo tests go in `checks/`, never `tests/`."*
Start a new session and look at the injected rules, or ask the agent where tests go.

Inspect and control what is stored:

```text
python3 -m memcode list            # memories (add --all to include stale)
python3 -m memcode show 3          # one memory with provenance
python3 -m memcode forget 3        # delete it
python3 -m memcode add "Deploys run from release/ branches" --path .github
python3 -m memcode stats           # counts by trigger, stale, retrievals
python3 -m memcode export mem.json
python3 -m memcode prune-stale
```

(run from your repo, with `PYTHONPATH` pointing at the plugin directory if you installed it as a plugin; see the guide).

The agent also gets three MCP tools: `memory_search`, `memory_add`, `memory_pinned`.

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
