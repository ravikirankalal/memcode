# State

Keep this file current: update it with every change that lands (what changed, the version, what is pending). The plan
is in [`PLAN.md`](PLAN.md).

_Last updated: 2026-10-20._

## Versions

| | Released | On the branch, not released |
|---|---|---|
| memcode | 0.12.1 (2026-10-20, PR #46) | none |
| memcode-status (mod) | 0.3.0 (2026-10-20, PR #46) | none |

## What works

| Duty | Feature | Since | Notes |
|---|---|---|---|
| Extract | Pattern triggers: correction, revert, fail-to-fix, retry, dependency change | 0.1 | instant; requests for now are never rules (#33) |
| Extract | Memory agent: reads each turn, candidates of every kind rated 1–5, best kept | 0.9 (ranking 0.11) | Haiku through the user's `claude` login; per-session budget $0.10–0.50 |
| Extract | Decisions about ongoing work, with subject keys, dated, expire after 30 days | 0.11 | never the agent's own progress (0.11.1) |
| Extract | Facts: confirmed commands, repo manifests, missing tools, fragile folders | 0.5 | scripts and one-off commands are not recorded (#36) |
| Store | One store per repository, shared by worktrees; files read from the session's checkout | 0.10.4 | #32, #37, #39 |
| Store | Staleness per file or Python function; how-tos stay shown across edits | 0.10.4 | |
| Store | Scopes (repo, folder, file, symbol); every agent change in `memcode history` | 0.8 / 0.9 | |
| Trigger | Start block: rules as instructions; map, decisions, facts, notes as data | 0.1 (decisions 0.11) | ~1500-token cap |
| Trigger | Per-prompt recall with promotions for costly memories | 0.3 | off by default (`config retrieval on`) |
| Trigger | First read of a folder adds its rules; first write is held once | 0.8 | |
| Trigger | MCP tools: memory_search, memory_add, memory_pinned, memory_facts | 0.1 | |
| Trigger | Status bar mod: counts, latest event, problems, the memory agent's state, this session's tally | mod 0.2 (layout 0.3) | `/memcode-status` dashboard |

## Latest release (memcode 0.12.1, memcode-status 0.3.0)

- Status bar: compact counts; routine scans ("kept 0") never take the headline; the memory agent's state on the right
  (`🔍 reading...` while it reads a turn, else when it last read one); this session's tally (`+2 saved`); on a narrow
  terminal the tally, the agent's state and the count labels give way so the headline keeps room.
- `/memcode-status` is a short dashboard: counts, problems, the agent's state, this session's tally, the last 8 events;
  diagnostics only when the bar cannot draw.
- memcode: the activity feed carries `busy: {agent: <since>}` while the worker reads (activity.busy).
- Tests: 219 Python, 13 mod.

## Previous release (0.12.0)

- The memory agent is the `memcode/agent/` package (transcript, model, checks, curate, worker, db); started as
  `python3 -m memcode.agent`.
- `config.py` owns the switches; `memcode config` is one table (memory-agent, decision-capture, retrieval, hierarchy).
- Removed: model capture; Codex/Gemini support (adapters, setup, sync-rules); store maintenance (consolidation, storage
  budget, labels); the benchmarks (`bench/`); experiment-only code (salience shadow log, legacy framing, salience
  ordering and map zoom, relevance-only ranking, `reinforce`); `docs/salvage`, `docs/decisions`.
- No redaction anywhere: the memory agent sends the log as is (the same provider already has it), and memcode stores
  what the session showed (local only). `redact.py` is gone.
- Old stores are cleaned on upgrade: the `capture_queue` and `salience_log` tables are dropped.

## Last measurements

- Memory agent recall on this repo's 10k-line development session (19 things a careful reader would keep): 3/19 before
  the 0.11 ranking prompt, 13–16/19 after; run in order as in real use it ended with 47 deduplicated memories (49 added,
  3 updated, 2 retired), about $0.17–0.20 for the whole session. The script that measured this (`bench/scanner_recall.py`)
  was removed with the benchmarks; it is in git history before 0.12.
- Earlier live gates (rules followed, scopes, the memory agent's first version) are recorded in the git history of
  `bench/live/RESULTS.md`.

## Known gaps

- The only timely trigger during work is the held first write; everything else arrives at session start, per prompt or
  on first read (Guardian is the next phase).
- No shipped way to measure the memory agent after prompt changes (PLAN, next step 2).
- Checkouts share the store, so staleness and the map follow whichever checkout last started a session.
- Pattern triggers see only the last 200 events per session.

## How to verify and release

```text
python3 -m unittest discover -s tests          # 219 tests, offline
claude plugin test mods/memcode-status         # 13 mod tests
claude plugin validate .claude-plugin/plugin.json --strict
```

Release: bump the version in `.claude-plugin/plugin.json`, the memcode entry of `.claude-plugin/marketplace.json` and
`memcode/mcp_server.py` (serverInfo); for the mod, `mods/memcode-status/.claude-plugin/plugin.json` and its
marketplace entry. Merge to master, then `claude plugin marketplace update memcode` and
`claude plugin update memcode@memcode --scope project` (and `memcode-status@memcode`), and restart Claude Code.
