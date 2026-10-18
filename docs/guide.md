# memcode guide

## How it works

```text
hooks (SessionStart, UserPromptSubmit, PostToolUse, PostToolUseFailure)
   -> memcode.hook_cli -> TriggerEngine -> SQLite (.memcode/memory.db)
SessionStart (also fires after compaction)
   -> scan repo, re-anchor renames, mark stale -> pinned block injected as additional context
MCP server: memory_search / memory_add / memory_pinned
```

Each hook is a fresh process. Trigger state is rebuilt from the last 400 recorded events per session (pruned after
30 days), so nothing lives in memory between hook calls.

### Triggers

| Trigger | Fires when | Stored as |
|---|---|---|
| correction | your prompt reads as a correction ("No - ...", "never/always ...", "don't ...", "remember that ...") or a stated team rule ("Heads up: we prefer X", "our convention is ...", needs a normative word) right after the agent acted (or, after a text-only exchange, an explicit rule such as "never/always <verb>" or "remember that") | `Rule from user correction: <the bare rule>`, repo-wide |
| revert | the agent's edit is undone (git checkout/restore/revert, or an edit that reverses it) | note anchored to the file |
| fail_to_fix | a command fails, files are edited, the same command passes | note anchored to the edited file (and the edited Python function) |
| retry | the same command is retried with different flags after a failure | repo-wide note |
| dep_change | the agent edits a dependency or lock file | note anchored to the file |

### What the agent sees

```text
## Project rules (stated by the user in earlier sessions; follow them)
(Listed oldest to newest. If two rules conflict, the later one replaces the earlier one.)
- Always use tabs.

<memcode-recorded-notes>   <- untrusted data: repo map and agent-derived notes
## Map ...
## Memories ...
</memcode-recorded-notes>
```

Rules are listed oldest to newest and the agent is told a later rule replaces an earlier conflicting one, so
"actually, switch to 2 spaces" overrides "use tabs" without any topic matching. Only `correction` memories become rules, because they are written from your own prompts. Everything else is data the
agent may use but is told not to obey. Total size is capped (default 1500 tokens, approximated as chars/4).

### Shadow-mode salience

At every session start memcode logs four scores per memory (surprise, friction, fragility, confidence; kept for the last 30
samples) and records which memories were shown. They are **never used for ranking**; `python3 -m memcode salience` shows
them. The data exists so a later phase can test whether salience beats recency/frequency before it is allowed to rank anything.

### Reinforcement (shadow mode)

A memory's confidence changes only from evidence, never from being shown. Sessions are scored at the next session
start once they have been quiet for 30 minutes:

| Memory | Confidence up | Confidence down | No change |
|---|---|---|---|
| anchored to a file/function | shown, then the agent edited that file, then a test command passed | the same mistake recurred on that anchor (new fail_to_fix/revert there) | anchor not touched, or touched without a passing test |
| your rule (repo-wide) | never (relevance cannot be verified) | you had to state the same rule again | otherwise |

Confidence is not used for ranking yet; `python3 -m memcode salience` shows ok/bad counts and `show ID` lists outcomes.

### Opt-in per-prompt retrieval

The pinned block is built at session start, before the task is known, and is capped. With
`python3 -m memcode config retrieval on` (or `MEMCODE_RETRIEVAL=1`) every prompt also gets up to 5 stored memories relevant
to *that* prompt (under ~600 tokens), as additional context. Relevance is deterministic: a file or function named in the
prompt, a file the agent edited earlier in the session, and IDF-weighted word overlap (at least two shared terms;
identifiers are split, so `parse_items` and "parse items" match). Unrelated prompts get nothing; a memory is never shown
twice in a session; stale memories are skipped. Rules are framed as rules, other notes as untrusted data.

Ranking (since 0.3.0) is *split*: the 5 most relevant memories are always shown, plus up to 2 extra relevant memories
that proved costly to learn: the user had to restate them, or the same failure recurred (recent evidence counts more;
14-day half-life). It won Gate 2b (`bench/live/RESULTS.md`, Run 11). `python3 -m memcode why ID` shows a memory's salience
and the evidence behind it. `MEMCODE_RANK=relevance` restores relevance-only ranking; `MEMCODE_RANK=salience` (relevance x
salience, also orders the pinned notes and tags fragile folders in the map) is kept for experiments.
`python3 -m memcode sessions` counts what was injected.

### Opt-in model capture

Pattern triggers miss rules stated in plain descriptive language ("we indent with tabs"). With
`python3 -m memcode config model-capture on` (or `MEMCODE_MODEL_CAPTURE=1`), a prompt the patterns did not capture, sent
after the agent has acted, that is not a question and is 12-1500 characters long, is queued; a detached background worker
asks a model (via your `claude` login; `MEMCODE_CAPTURE_MODEL`, default `claude-opus-5-5`) whether it states a standing
convention, and stores it as a rule if so. The prompt is never delayed. **Off by default**: it sends the (redacted) prompt
text to the model and costs one call per classified prompt (about $0.02 on Opus 5.5; less on Haiku). The worker's model
call runs with no tools, no settings or plugins (so memcode cannot recurse), and no saved session.

### Hierarchical memory

- **Scope hierarchy** (on by default since 0.8.0; `memcode config hierarchy off` or `MEMCODE_HIER=0` turns it off).
  It passed two live gates (bench/live/RESULTS.md, Runs 14 and 15; on the untuned set mistakes fell from 24/54 to
  0/53 with retrieval off and from 18/54 to 1/54 with retrieval on). A rule naming directories applies to their deepest
  common directory ("every module under billing/ ...": scope `billing/`); notes apply to their file or symbol. Retrieval
  only considers repo-wide memories and those on the path to the files in play, nearest scope first. The session-start
  block keeps repo-wide rules and marks map folders that hold scoped ones (`billing/ [3 rules]`); the first time the
  agent reads a file, that file's scoped rules are injected once. If its first contact is a write, that write is refused
  once with the rules as the reason (context added after a write would come too late) and the agent redoes it. Rules
  arrive this way whether or not per-prompt retrieval is on. `memcode rescope`, `memcode list --scope DIR`.

Still opt-in, each until its own gate passes:

- **Consolidation** (`MEMCODE_CONSOLIDATE=1`). At session start, 3 or more agent notes that say the same thing (same
  trigger and anchor, text equal after numbers, paths and command flags are normalized) are grouped under one *lesson*
  ("4 similar fail_to_fix notes on api/x.py: ..."), which is shown instead of them. User rules and team memories are
  never grouped. `memcode consolidate [--dry-run|--undo]`.
- **Storage budget** (`MEMCODE_STORE_BUDGET=N`). At session start, evicts down to N memories: stale notes first, then
  consolidated notes (their lesson keeps counting them), then retry / dependency notes, then other agent notes by
  lowest salience. User rules, team memories and lessons are never evicted. `memcode budget N [--dry-run]`.

Every memory also gets topic **labels** (testing, build, style, naming, git, deps, security, env, perf, api, data, docs,
ci) for filtering only: `memcode list --label testing`, `memory_search(label=...)`, `memcode label ID +perf -style`.
Labels never change ranking or injected text.

### Transcript capture (on by default since 0.9.0)

Pattern triggers miss rules you state only as description ("every public function here starts with qx_") and
things the agent finds out on its own ("the checks only run through tools/ci/verify.sh"). After each finished turn,
memcode queues the session transcript; a detached worker sends the part not scanned yet, condensed and redacted, to a
model through your `claude` login (`MEMCODE_CAPTURE_MODEL`, default Haiku, about $0.001 per turn) and keeps an item
only if its quoted evidence is in the transcript. Rules come only from your own words; everything else is a note;
limits of the agent's environment become env facts; items that contradict or weaken your rules, repeat a memory, or
talk about the agent's own memory are dropped. On the untuned tc2 set (bench/live/RESULTS.md, Run 17) mistakes fell
from 25/30 to 3/30 with 22/22 stored memories correct; the first attempt (Run 16) failed its gate and led to the
current safeguards.

It sends transcript text to the model. Turn it off per repo with `python3 -m memcode config transcript-capture off`, or
everywhere with `MEMCODE_TRANSCRIPT_CAPTURE=0`; it is off wherever the `claude` CLI is not installed. What it stored is
listed by `/memcode:list` (trigger `transcript`, or rules with source `transcript` in `memcode show ID`).

### Facts

Besides memories (one event each), memcode keeps **facts**: keyed knowledge that is updated in place as evidence
accumulates, and shown in a short `## Facts` section at session start.

| kind | where it comes from | example |
|---|---|---|
| command | shell commands the agent runs, split into simple commands and classified (test, build, lint, typecheck, format, run, install), or kept because they recur | test: `python3 -m unittest discover -s tests` (ran 31x, 31 confirmed ok) |
| repo | build manifests read at session start (package.json scripts, Makefile targets, pyproject, Cargo, go.mod, CI `run:` steps), main languages, test directory; refreshed when the file changes | build: `npm run build` (from package.json) |
| env | limitations seen here: a command not installed (exit 127 and not on PATH) | `sqlite3` is not installed in this environment |
| inference | aggregated: fragile folders, commands that keep failing | `make deploy` has failed 3x and never passed here |
| user | `memcode fact set KEY VALUE` | Deploys only from release/* branches |

A command only counts as confirmed when its exit status is really its own: not followed by `|| fallback`, not one
of several commands in a failing line. Agents usually pipe output (`python3 -m unittest 2>&1 | tail -3`), which hides
the exit status; for a lone piped command the runner's summary line decides instead (`OK`, `FAILED (failures=1)`,
`5 passed in 0.1s`, `test result: ok.`, `All checks passed!`, ...). A failure summary counts through any filter; a
pass only through end-keeping ones (`tail`, `cat`, `tee`), since `head` or `grep` may have cut a failure off. Without
a summary line the run stays "not confirmed". Commands run after `cd` to a place outside the repo, inline scripts
(`python3 -c`, heredocs), probes (`--version`, `--help`) and commands with shell variables are not recorded. Nothing
from command output is stored.

```
python3 -m memcode facts                 # all facts, and what the session-start block shows
python3 -m memcode facts --backfill      # first run: build facts from the existing event log
python3 -m memcode fact set deploy "Deploys only from release/* branches"
python3 -m memcode fact rm deploy
```

The agent can also ask with the MCP tool `memory_facts` (optionally filtered by role, e.g. `test`).

### Team memory

Your local store (`.memcode/`) is never committed. To give teammates a memory, share it:

```
python3 -m memcode team            # what is shared, imported, stale, and worth sharing
python3 -m memcode share 12 15     # copy memories #12 and #15 into .memcode-team.jsonl
git add .memcode-team.jsonl && git commit -m "Share billing rules with the team"
```

`.memcode-team.jsonl` holds one memory per line, so a PR diff shows exactly which rules and notes are being shared,
and your team reviews them like any other change. After the PR merges, each teammate's next session imports the file
(no server; git is the sync). Deleting a line and merging removes it from everyone's agent; `memcode unshare ID`
does that for you. Shared memories behave like local ones: rules appear as rules, notes as untrusted data, and a note
goes stale for a teammate whose copy of its file differs.

Trust: the file is repo content, as trusted as CLAUDE.md, which is why sharing always goes through review. On import,
memcode skips malformed lines, accepts only known memory kinds, confines paths to the repo, redacts secrets and caps
the file at 500 memories. Session ids and other provenance never leave your machine. `MEMCODE_TEAM=0` disables the import.

### Other agents: Codex CLI and Gemini CLI

memcode's core is agent-neutral; small adapters translate each agent's hook payloads. Print the config for your
agent and paste it where the comment says:

```
/path/to/memcode/bin/memcode setup codex     # TOML for ~/.codex/config.toml (hooks + MCP server)
/path/to/memcode/bin/memcode setup gemini    # JSON to merge into .gemini/settings.json
```

| | Claude Code | Codex CLI | Gemini CLI |
|---|---|---|---|
| Rules and notes at session start | yes | yes | yes |
| Corrections captured from prompts | yes | yes | yes |
| Per-prompt retrieval | yes | yes | yes (appended to the turn) |
| Fail-to-fix and retry memories | yes | **no**: Codex sends shell output without an exit code | when the output states the exit code |
| MCP tools | yes | yes | yes |

The store is shared: the same `.memcode/` serves every agent you use in a repo. Formats were checked against Codex's
source and Gemini's hook reference (2026-10-16); hooks APIs change, so report breakage.

**Agents without hooks** (or to see the block in a plain file): `memcode sync-rules` writes the same block into
`AGENTS.md`, between `<!-- memcode:start -->` and `<!-- memcode:end -->` markers; text outside them is never touched.
Re-run it to refresh. If `AGENTS.md` is committed, the block is shared when you commit it, and the command says so.
Memcode never writes `AGENTS.override.md`: Codex reads that file *instead of* `AGENTS.md`, which would hide your
team's instructions. Cursor is not supported yet: its hook docs could not be verified, and users report that its
hooks cannot inject context.

## What is stored, and privacy

- **Memories**: short redacted summaries, never raw tool output.
- **Events table**: redacted hook events, each field capped at 500 characters, pruned to 400 per session / 30 days.
- **Redaction** runs before anything is written: cloud and API keys, tokens, JWTs, private keys, `password=`-style
  assignments, `curl -u`, URLs with credentials. It is pattern-based; it cannot catch every secret, so
  review with `python3 -m memcode list` / `export` if you work with sensitive repos.
- Everything is local: no network calls, no telemetry. Files are created with owner-only permissions.
- A user rule is taken from your prompt as written. If you paste untrusted text containing something that reads as a
  correction, it can become a rule; use `forget` to remove it.

## Troubleshooting

| Symptom | Check |
|---|---|
| Nothing is injected | `python3 -m memcode stats` (any memories?). Rules come only from correction-style prompts that follow an agent action. |
| A correction was not captured | Phrase it as a rule ("No - always X", "never Y"); see the trigger table. |
| Hook errors | Failures never block the agent; they are logged to `<repo>/.memcode/error.log`. |
| `python3 -m memcode` cannot import | Use `/memcode:cli ...` inside Claude Code, or the plugin's `bin/memcode` (see the README alias); `python3 -m memcode` only works from a checkout or with `PYTHONPATH` set to the plugin directory. |
| Wrong repo | The root is `CLAUDE_PROJECT_DIR`, else the git toplevel, else the working directory. Use `--root`. |
| Stale or wrong memory | `python3 -m memcode show ID`, then `forget ID` or `prune-stale`. |

## Disable or uninstall

```text
/plugin disable memcode@memcode
/plugin uninstall memcode@memcode
rm -rf <repo>/.memcode          # delete a repository's memory
```

## Known limits

- Only the last 400 events per session inform trigger state.
- Staleness is per symbol for Python (`file.py::function`, hashed on the AST, so comments and formatting do not
  count) and falls back to the whole file for other languages or files that do not parse.
- Plain `mv` of a whole directory is not re-anchored.
- The benefit over a hand-written `CLAUDE.md` is unproven; see the benchmark results.
