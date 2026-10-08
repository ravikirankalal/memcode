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

### Opt-in model capture

Pattern triggers miss rules stated in plain descriptive language ("we indent with tabs"). With
`python3 -m memcode config model-capture on` (or `MEMCODE_MODEL_CAPTURE=1`), a prompt the patterns did not capture, sent
after the agent has acted, that is not a question and is 12-1500 characters long, is queued; a detached background worker
asks a model (via your `claude` login; `MEMCODE_CAPTURE_MODEL`, default `claude-opus-5-5`) whether it states a standing
convention, and stores it as a rule if so. The prompt is never delayed. **Off by default**: it sends the (redacted) prompt
text to the model and costs one call per classified prompt (about $0.02 on Opus 5.5; less on Haiku). The worker's model
call runs with no tools, no settings or plugins (so memcode cannot recurse), and no saved session.

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
| `python3 -m memcode` cannot import | Set `PYTHONPATH` to the plugin directory (the clone, or the installed plugin cache) or run from a checkout. |
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
