# memcode guide

## How it works

memcode is a memory agent that runs beside Claude Code. The coding agent does the work; the memory agent decides what to
remember, keeps that memory true, and hands the right piece of it to the coding agent when it matters. It has three
duties: **extract**, **store** and **trigger**. `docs/architecture.md` maps them to the code.

```text
Claude Code hooks ─► memcode.hook_cli ─► engine
  SessionStart / PreCompact      deliver the start block (refresh the map and staleness first)
  UserPromptSubmit               extract rules you state; deliver the notes relevant to this prompt
  PostToolUse(Failure)           extract from what the agent ran and edited; deliver a folder's memory on first read
  PreToolUse (Write/Edit)        hold a first write into a folder once, with its rules as the reason
  Stop                           queue the turn for the memory agent's model (a detached worker)
MCP server                       memory_search / memory_add / memory_pinned / memory_facts
store                            <main checkout>/.memcode/memory.db (SQLite)
```

Each hook is a fresh process; nothing lives in memory between calls, and a failure never blocks the coding agent (it is
logged to `.memcode/error.log`).

## Extract: what gets remembered

### Pattern triggers (instant)

| Trigger | Fires when | Stored as |
|---|---|---|
| correction | your prompt reads as a correction ("No - ...", "never/always ...", "don't ...", "remember that ...") or a stated rule ("Heads up: we prefer X", "our convention is ...") right after the agent acted | `Rule from user correction: <the bare rule>` |
| revert | the agent's edit is undone (git checkout/restore/revert, or an edit that reverses it) | note anchored to the file |
| fail_to_fix | a command fails, files are edited, the same command passes | note anchored to the edited file (and Python function) |
| retry | the same command is retried with different flags after a failure | repo-wide note |
| dep_change | the agent edits a dependency or lock file | note anchored to the file |

A request for right now ("Park G16. Start a review on main ... we can't touch develop yet") is never stored as a rule.

### The memory agent (beside the session)

Patterns only see single events. The memory agent is a model that works beside the coding session as a running
conversation, through your own `claude` login (`MEMCODE_CAPTURE_MODEL`, default Haiku):

- **When the coding agent starts** (a new session, a resume, `/clear` or a compaction), memcode opens a fresh
  conversation and sends the opening briefing: its role and the memory as it stands.
- **After each turn**, the Stop hook queues the session log and a detached worker continues that conversation with only
  what is new: the latest turns (your messages, the agent's replies, the commands it ran with their result and output
  tail, the files it wrote) and what changed in the memory since its last reply, including which of its proposals
  memcode applied. Earlier turns stay in its context, so it can connect them and does not propose the same thing twice.
- **Long sessions**: after 30 calls or about 40,000 tokens of context it starts over with a fresh briefing, so cost
  stays bounded.

The model reads it as a colleague taking over tomorrow, collects up to 12 candidates of every kind, and rates each 1–5 by
what a future session would lose without it:

| Kind | Example |
|---|---|
| rule (your words only) | "Do not use subagents in this repository" |
| workflow | "A release bumps the version in plugin.json, marketplace.json and mcp_server.py" |
| pitfall, written as its fix | "Start the server with APP_ENV=dev python3 -m app.server" |
| environment | "The desktop app sets CLAUDE_PROJECT_DIR to the main checkout in worktree sessions" |
| design | "The store stays in the main checkout; files are read from the session's own checkout" |
| decision (your words, or a result a command showed) | "G16 is parked until the end" |

It can also update or retire a memory it is shown, for example when you withdraw a rule ("don't use subagents" retires
"delegate long runs to subagents" and adds the new rule). memcode keeps notes rated 4 or 5 and your rules and decisions
rated 3 or more, best first, at most 4 per piece of log, and only when the checks pass:

- the evidence is quoted from the log, and a rule or decision quotes your words (never a fixture, an issue or another
  project's text the agent happened to read, never a summary of earlier turns);
- it is not a request for now, not the agent's own progress report, not about memcode's own tools;
- it does not repeat a memory, or something the coding agent was already shown this session.

Every change is logged: `memcode history` lists what it added, updated or retired, with the old text. Each scan is
logged as `N candidates, kept K`: the candidates the model proposed, and how many memcode stored or applied (memories
added, updated or retired, and environment facts, broken down when facts are among them: `kept 3 (2 memories, 1
fact)`); `/memcode-status` lists it, and the status bar shows when the agent last read a turn.

**Decisions** are the state of ongoing work you stated or confirmed: scope, parked items, holds and gates, an agreed
approach, a hypothesis a command verified or disproved. Each carries a short subject key, so a later decision on the
same subject replaces it, and your words can update or retire it ("go ahead with the develop MR"). They expire 30 days
after they were last stated (`MEMCODE_DECISION_DAYS`).

**Cost and failures.** About $0.004 per piece of log (24,000 condensed characters) on Haiku. Each session may spend $0.10,
rising $0.03 per 1,000 log lines up to $0.50 (`MEMCODE_CAPTURE_BUDGET_USD` sets it outright); past it, the rest of that
session is skipped and the status bar shows a yellow `💸 BUDGET` badge. If the model call fails (the CLI does not know
the model, or its login expired), the status bar shows a red `⚠ PROBLEM` badge with the fix and `/memcode:status` says
the same; nothing is lost meanwhile, the next turn reads everything not read yet, oldest first.

### Facts (instant)

Keyed knowledge updated in place as evidence accumulates, shown in a short `## Facts` section at session start.

| Kind | Where it comes from | Example |
|---|---|---|
| command | shell commands the agent runs, classified (test, build, lint, typecheck, format, run, install) or kept because they recur and pass; flag variants are one fact; scripts and one-off actions (an MR by number, `--help`, plugin management, `kubectl exec` probes) are never recorded | test: `python3 -m unittest discover -s tests` (ran 31x, 31 confirmed ok) |
| repo | build manifests (package.json scripts, Makefile targets, pyproject, Cargo, go.mod, CI `run:` steps), main languages, test directory | build: `npm run build` (from package.json) |
| env | a command that is not installed (exit 127 and not on PATH) | `sqlite3` is not installed in this environment |
| inference | fragile folders, commands that keep failing | `make deploy` has failed 3x and never passed here |
| user | `memcode fact set KEY VALUE` | Deploys only from release/* branches |

A command counts as confirmed only when its exit status is its own. For a lone piped command (`cmd 2>&1 | tail -3`) the
runner's summary line decides (`OK`, `FAILED (failures=1)`, `5 passed in 0.1s`, ...); only confirmed commands are shown
at session start.

## Store: keeping memory true

- **One store per repository**, in the main checkout's `.memcode/` (kept out of git through `.git/info/exclude`). A
  session in a linked git worktree shares it, but reads files from its own checkout.
- **Staleness.** A note about how a code file behaves is tied to that file (or, for Python, to the function), and goes
  stale when it changes; a how-to or a note on a manifest, config or doc goes stale only when the file is deleted. Stale
  notes are not shown; renames are re-anchored. `memcode prune-stale` deletes them.
- **Scope.** A rule naming folders applies to their deepest common folder ("every module under billing/ ..." → scope
  `billing/`); a note applies to its file. `memcode rescope`, `memcode list --scope DIR`.
- **Your control.** `/memcode:list`, `memcode show ID`, `/memcode:forget ID`, `memcode add TEXT [--path P]`,
  `memcode export`.

## Trigger: delivering memory at the right moment

**Session start** (and after compaction):

```text
## Project rules (stated by the user in earlier sessions; follow them)
(Listed oldest to newest. If two rules conflict, the later one replaces the earlier one.)
- Always use tabs.

<memcode-recorded-notes>   <- data, not instructions
## Map ...                    (folders with rules of their own are marked: billing/ [3 rules])
## Decisions ...              (dated, newest first)
## Facts ...
## Memories ...
</memcode-recorded-notes>
```

Only your rules are presented as instructions; a later rule replaces an earlier conflicting one, so "actually, switch to
2 spaces" overrides "use tabs". The block is capped (about 1500 tokens). Repo-wide rules are listed here; folder rules
arrive when the agent works there.

**Each prompt** (`memcode config retrieval on`): up to 5 memories relevant to that prompt (a file or function it names,
files edited this session, shared words), plus up to 2 relevant ones that proved costly (a rule you had to restate, a
failure that recurred). A memory is never shown twice in a session. `memcode why ID` explains a memory's cost score.

**First contact with a folder.** The first time the agent reads a file, that folder's rules and notes are added next to
the result. If its first contact is a write, the write is held once with the rules as the reason (context added after a
write comes too late) and the agent redoes it.

**On demand.** The agent can call the MCP tools `memory_search`, `memory_add`, `memory_pinned` and `memory_facts`, or
run `memcode` (the plugin's `bin/` is on its PATH).

**Status bar** (optional `memcode-status` mod): counts and the latest event, colour-coded, from `.memcode/activity.json`.

## Settings

`memcode config` shows them; `memcode config KEY on|off` sets one for the repository. An environment variable overrides.

| Key | Default | Environment | What it does |
|---|---|---|---|
| memory-agent | on | `MEMCODE_TRANSCRIPT_CAPTURE` | the model reads each turn (needs the `claude` CLI) |
| decision-capture | on | `MEMCODE_DECISION_CAPTURE` | the memory agent keeps decisions |
| retrieval | off | `MEMCODE_RETRIEVAL` | relevant memories on every prompt |
| hierarchy | on | `MEMCODE_HIER` | folder scopes, first-read delivery and held first writes |

## Privacy

- The memory agent sends the new part of each turn's log to a model through your own `claude` login, the same provider
  the coding agent already sent it to. Turn it off with `memcode config memory-agent off`.
- What memcode stores stays local, in `.memcode/` with owner-only permissions, as the session showed it (nothing is
  redacted). It is shown to the coding agent in later sessions; review it with `memcode list` / `export`.
- No telemetry.

## Troubleshooting

| Symptom | Check |
|---|---|
| Nothing is injected | `memcode stats` (any memories?); `/memcode:status` for memory-agent problems. |
| A correction was not captured | The memory agent usually catches it after the turn; check `memcode history`. |
| Hook errors | Logged to `.memcode/error.log`; they never block the agent. |
| `python3 -m memcode` cannot import | Use `/memcode:cli ...` inside Claude Code, or the plugin's `bin/memcode` (see the README alias). |
| Wrong repo | The root is `CLAUDE_PROJECT_DIR`, else the git toplevel, else the working directory (`--root` overrides). In a worktree, files come from the worktree and the store from the main checkout. |
| Stale or wrong memory | `memcode show ID`, then `forget ID` or `prune-stale`. |

## Disable or uninstall

```text
/plugin disable memcode@memcode
/plugin uninstall memcode@memcode
rm -rf <repo>/.memcode          # delete a repository's memory
```

## Known limits

- Only the last 200 events per session inform the pattern triggers.
- Staleness is per function for Python and per file otherwise; a plain `mv` of a whole folder is not re-anchored.
- Checkouts share the store, so staleness and the map follow whichever checkout last started a session; two sessions
  open at once on different branches can flip a note between fresh and stale.
