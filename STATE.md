# State

Keep this file current: update it with every change that lands (what changed, the version, what is pending). The plan
is in [`PLAN.md`](PLAN.md).

_Last updated: 2026-10-29._

## Versions

| | Released | On the branch, not released |
|---|---|---|
| memcode | 0.17.4 (2026-10-29, PR #60) | none |
| memcode-status (mod) | 0.5.0 (2026-10-29, PR #53) | none |

## What works

| Duty | Feature | Since | Notes |
|---|---|---|---|
| Extract | Pattern triggers: correction, revert, fail-to-fix, retry, dependency change | 0.1 | instant; requests for now are never rules (#33) |
| Extract | Memory agent: a running conversation per coding session (opened at SessionStart, resumed each turn); candidates of every kind rated 1–5, best kept | 0.9 (ranking 0.11, conversation 0.13) | Haiku through the user's `claude` login; no per-session limit since 0.17 (MEMCODE_CAPTURE_BUDGET_USD sets one); restarts after 30 calls or ~40k tokens |
| Extract | Decisions about ongoing work, with subject keys, dated, expire after 30 days | 0.11 | never the agent's own progress (0.11.1) |
| Extract | Facts: confirmed commands, repo manifests (npm, make, pyproject, Cargo, Go, Maven, Gradle), missing tools, fragile folders | 0.5 (Maven/Gradle 0.14) | scripts and one-off commands are not recorded (#36) |
| Extract | Project profile inferred by the memory agent: stack, integration, component, structure, domain, convention | 0.14 | from commands, [read] and [edited] lines; on the branch: also infra, deployment, branching, location, reference, and an unusual flag (memcode/kinds.py) |
| Store | One store per repository, shared by worktrees; files read from the session's checkout | 0.10.4 | #32, #37, #39 |
| Store | Staleness per file or Python function; how-tos stay shown across edits | 0.10.4 | |
| Store | Scopes (repo, folder, file, symbol); every agent change in `memcode history` | 0.8 / 0.9 | |
| Trigger | Start block: rules as instructions; map, decisions, facts, notes as data | 0.1 (decisions 0.11) | ~1500-token cap; on the branch: From you, then one ranked Memory list, then the map |
| Trigger | Per-prompt recall with promotions for costly memories | 0.3 | on by default since 0.17; since 0.16 also the recent conversation, after each command or edit, and what the memory agent flags |
| Trigger | First read of a folder adds its rules; first write is held once | 0.8 | |
| Trigger | MCP tools: memory_search, memory_add, memory_pinned, memory_facts | 0.1 | |
| Trigger | Status bar mod: counts, latest event, problems, the memory agent's state, this session's tally | mod 0.2 (layout 0.3) | `/memcode-status` dashboard |

## Latest release (memcode 0.17.4)

- Recall for natural questions (asked live: "How do I run the tests in this repo?" recalled nothing):
  - Each memory's vector also carries words for its topic, or a measured command's role (embed.WORDS: test -> "run
    the tests test suite testing", deployment -> "deploy release ship production", ...), at half weight (twice for a
    measured command, whose own text is mostly flags); light stemming (branching/branch, release/releasing).
  - A memory only in the start block comes back next to the work once it scores the normal 0.8 (was 2.4).
  - The recent conversation weighs 0.6 of the prompt (was 0.5): topic words dilute long memories a little.
  - Measured on a copy of this repository's store, a fresh session, 10 questions: before 2 of 7 answerable ones
    found their memory; after 6 of 7 (tests, manifests, branching, docs, subagents; release has no memory to find;
    lint just under, 0.76); the 3 unrelated questions still recall nothing. Left: "Where does memcode keep its
    database?" recalls two memories filed under memcode/, because the prompt names that folder.
- The terminal copy is coloured (Claude Code keeps ANSI colours in a hook's systemMessage and shows markdown
  literally, checked in tmux): a bold cyan header, a cyan `│` bar down the left, the user's own words in magenta;
  NO_COLOR or MEMCODE_COLOR=0 turns it off.
- The agent's `memcode:` line is a markdown quote (`> memcode: ...`), drawn as a quote block everywhere (seen live:
  `▎ memcode: release steps are in docs/RELEASING.md, ...`).
- Testing note: every Claude Code started in this cloud container inherits this session's id, so scratch tests share
  "already shown this session" state.
- Tests: 260 Python, 14 mod.

## Previous release (memcode 0.17.3)

- The mobile app shows no hook message (the systemMessage copy arrives inside the hook event, which it does not
  draw), so injections were invisible there. Now each injected block ends with memcode's own line to the agent,
  outside the untrusted wrapper (display.MENTION): when its answer or next step relies on one of the memories, say so
  in one line starting with `memcode:`; never mention one it did not use. Added in one place (hook_cli), so every
  injection carries it; the user's copy leaves it out. `memcode config mention-memories off` (MEMCODE_MENTION=0).
- Live check (Haiku, `claude -p`, this checkout as --plugin-dir, a store with a release-steps memory): "How do I cut
  a release here?" answered with `memcode: release steps come from a recorded note that says they are in
  docs/RELEASING.md.` first; "What is 17 times 23?" answered `391`, no mention.
- Tests: 259 Python, 14 mod.

## Previous release (memcode 0.17.2)

- The one-time welcome suggests `/plugin install memcode-status@memcode` only when the mod is missing: memcode reads
  enabledPlugins in the user's and the project's Claude Code settings and Claude Code's installed_plugins.json
  (installed for the user, or for this project); `memcode doctor` reports it as a `status mod` line. Seen live: the
  welcome in this repository suggested the mod although it was installed.
- Live check of 0.17.1 (a fresh Claude Code session in this repository, tmux): the welcome and the start block showed
  under `SessionStart:startup says:`; the status line read `📥22 injected`; the one-time read kept 2 ($0.0027; the
  store already had most of it). Restarting this cloud session from the app reconnects without a SessionStart.
- Tests: 259 Python, 14 mod.

## Previous release (memcode 0.17.1)

- Every injection is shown to the user in the conversation as well (display.py, the hook's systemMessage): one line
  saying when and how much (`memcode → agent context for this prompt: 1 memory`), then one clipped line per memory;
  the map and the untrusted-data framing are left out; at most 25 lines. Covers the start block, per-prompt recall,
  recall after tool calls, first touch and the memory agent's flags. `memcode config show-injections off`
  (MEMCODE_SHOW_INJECTIONS=0) hides it; the agent's context is unchanged.
- Live check (Claude Code 2.1.312 in tmux, this checkout as --plugin-dir): the start block shows under
  `SessionStart:startup says:` with the welcome; a prompt about releasing shows `UserPromptSubmit says: memcode →
  agent context for this prompt: 1 memory` and the memory, above the agent's answer. In `-p --output-format
  stream-json` the text arrives inside the hook_response event's output.
- Tests: 258 Python, 14 mod.

## Previous release (memcode 0.17.0: easier installation)

- Hooks, the MCP server and the memory agent's worker never import from the user's repository: hooks and MCP start
  through `bin/memcode` (run by path), the worker starts from the plugin directory. Before, `python3 -m` put the
  repository first on the import path: a repo with its own json.py, sqlite3.py or memcode/ broke memcode or ran its
  own code (and this repository's hooks ran its working tree).
- Python 3.9 is enough: the whole suite passes on 3.9.25 (uv); `bin/memcode` checks the version and an older
  python3 gets one message at session start instead of a traceback in error.log.
- `memcode doctor` (`/memcode:doctor`): python, sqlite JSON, the store, the memory agent and its `claude` CLI and
  health, recall, whether the hooks ran here, errors logged. Session start shows the user (systemMessage) a
  one-time welcome with the status mod's install command, a memory agent that is on but has no `claude` CLI, missing
  SQLite JSON, and errors logged since the last session (each once).
- Per-prompt recall (and recall after commands and edits) is on by default.
- Day one (agent/bootstrap.py): the first session in a repository (memory agent on) has the memory agent read the
  repository's key files once (README, docs/*.md, manifests, Makefile, Docker and compose files, CI workflows,
  CODEOWNERS, deploy/infra files; the top-level layout, the branches and the last 15 commit subjects; not CLAUDE.md
  or AGENTS.md, which Claude Code already loads), one call outside the running conversation, up to 10 memories kept.
  Live check on a fresh clone of this repository: 11 candidates, kept 8 (stdlib-only Python 3.9+, the shared store
  as unusual, releases as marketplace pushes as unusual, docs locations, layout, update commands, branching).
- Found by `memcode doctor` on this repository: this long session spent its memory-agent budget ($0.10), so 1705
  transcript lines were not scanned. So the memory agent's budget is now unlimited by default (every turn is read);
  `MEMCODE_CAPTURE_BUDGET_USD` sets a per-session limit; each model call stays capped at $0.25.
- README: a 'What you'll see' section (the first-session line, a start block, where memories come back).
- Tests: 256 Python (also on 3.9), 14 mod.

## Previous release (memcode 0.16.1)

- `memcode edit ID TEXT [--topic T]` corrects a memory in place: keeps from_user, restarts a decision's expiry,
  logs the old text (`memcode history`, op `edit`), refreshes its vector and links, writes an `updated` event.
  Measured commands are refused (rebuilt as commands run). Added after memory #10 here had to be fixed by script:
  it told the agent to run `claude plugin validate hooks/hooks.json --strict`, which can never pass (the validator
  reads any file as a plugin manifest).
- Tests: 247 Python, 14 mod.

## Previous release (memcode 0.16.0)

- Recall beyond the prompt (retrieval.py):
  - Per-prompt recall also scores against the recent conversation (the session's last 3 prompts and 12 tool calls:
    commands, files, edit text) at half weight, so a decision or fact about what the work is on comes back unnamed.
  - After a command or an edit (PostToolUse, retrieval on): up to 2 memories scoring 1.5+ about that action
    (`for_action`; measured commands are skipped, they would echo the action; the memory's content must be close too,
    cosine 0.3+, since a command naming a memory's folder is not enough: seen live, a tmux note came back for
    `claude plugin test mods/memcode-status`).
  - The memory agent gets a `recall` operation: a numbered memory that matters for the next step, with why; its
    evidence must quote the transcript; at most 3 per piece. Queued in `pending_recalls` and delivered once at the next
    prompt or tool call (`flagged`), whether or not per-prompt recall is on, as `(why now: ...)`.
  - A memory that was only in the start block may be shown once more next to the work when it scores 2.4+.
- Live check (Haiku, a store with a parked-export decision, a test pitfall and noise; a turn where the user picks
  up the export and `pytest -q` fails): both the decision ("confirm with the user before writing the CSV writer")
  and the pitfall flagged, the noise not; delivered at the next prompt; $0.0016. Before the prompt asked to check
  every decision against what is starting, only the pitfall was flagged.
- Seen in this repo while building it: the hooks import memcode from the working tree, and an action recall fired on
  a scripted module edit with the stored pitfall about splitting modules.
- Tests: 245 Python, 14 mod.

## Previous release (memcode 0.15.2, memcode-status 0.5.0)

- Injections show on the status bar. memcode's injection events (start, recalled, touch, held) carry how many
  memories went into the coding agent's context and name the first one (`2 memories for this prompt: (pitfall,
  2026-10-20) ...`; activity.first). The mod sums them for this session: `📥23 injected` on the bar, and
  `23 injected (20 at start, 2 recalled, 1 on first touch)` in `/memcode-status`; the folder badge is `📂 FOLDER`.
  The counter is part of the counts (`37 memories · 12 from you · 📥23 injected`, short `🧠37 📜12 📥23`), so it
  never gives way on a narrow terminal. Fixed: the mod took the session's start after the start had run, so the
  start block's injection (written by the SessionStart hook) was not counted; it now takes it before, minus a minute.
- Tests: 240 Python, 14 mod.

## Previous release (memcode 0.15.1)

- Every memory shown carries the date it was last stated or changed (a measured command: when it last ran): start
  block (`- (design, 2026-10-20) ...`; what you said ends with `(2026-10-18)`), per-prompt recall, first touch, the
  memory agent's briefing and delta, `memcode list`, MCP search (`pinned.day`). Tests: 239 Python, 13 mod.

## Previous release (memcode 0.15.0, memcode-status 0.4.0: flat memory graph, inference kinds)

- Step 1: memories gain `from_user`, `topic`, `importance`, `mkey`, `expires_at`, `stats`; new tables `memory_links`
  and `memory_vectors`; old rows migrate (corrections -> from_user, categories -> topic, decisions -> expiry).
- Step 2: one rule concept. Every "is this a rule" check reads `from_user` (start block, folder scopes, held writes,
  recall, salience, the memory agent, status counts). The memory agent writes origin `agent` with from_user / topic /
  importance / expires_at; decisions are `topic='decision'` with an expiry, refreshed when updated. Rule text is plain
  (the "Rule from user correction:" prefix is gone, stripped from old rows).
- Step 3: facts are keyed memories (`mkey` = the old key, origin command / repo / env / inference / manual, counters
  in `stats`), read through the `fact_rows` view; old stores move their facts table into memories and drop it. Until
  one delivery (step 5), note paths (start block notes, recall, the agent's briefing, `memcode list`) skip keyed
  memories and facts still render as `## Facts`.
- Step 4: `embed.py` (local hashed TF-IDF vectors over words, identifier parts and paths; stored per memory with the
  hash of its text, IDF applied when compared; `search`) and `graph.py` (automatic `same_file` and `similar` links
  rebuilt for new or changed memories; agent links kept; `neighbours`, `degree`). Run at session start and after the
  memory agent writes. On this repo's store: 74 memories embedded and linked in 0.01 s.
- Step 5: one delivery. The start block is `## From you` (the user's words, as instructions), then one `## Memory`
  list (data) where every other memory is `- (label) text [anchor]`: the label is its topic, `decision, <date>`, a
  fact's role, or where it came from; ranked by importance, graph connections, recalls and recency; then the map.
  Per-prompt recall scores by embedding cosine (plus the path boosts) and adds up to 2 graph neighbours of its top
  memories; first touch of a folder adds up to 3 neighbours of that folder's memories. Expired memories are never
  delivered; facts are recalled only when worth showing (facts.shown).
- Step 6: the memory agent's output is flat: op, target, from_user, topic (workflow, pitfall, environment, design,
  decision, process, stack, integration, component, structure, domain, convention), subject, importance, text,
  evidence, path, links (numbers of memories it belongs with: kept as agent links in the graph), conflicts. The
  checks are unchanged (from_user needs the user's own words; decisions the user's words or a settled result).
  Environment observations are ordinary memories (no separate env facts, no cap); the scan line is `N candidates,
  kept K`. The briefing lists memories as `#id from you|<label> [where]` and shows facts as measured by memcode.
- Step 7: surfaces. The activity feed counts `{memories, from_you}` (command counters aside); saved events read
  `from you: ...` or `(topic) ...`; the session-start event `N from you, M memories`. `memcode list` labels each
  memory (from you, topic, decision with date, origin); `show` gives importance, key, expiry and links; `add --topic`;
  `stats` counts from you, stale and links; `export` includes the command counters. MCP `memory_search` is embedding
  search plus graph neighbours; `memory_add` takes a topic. Status mod 0.4.0: `37 memories · 12 from you` (reads old
  feeds too). README, guide and architecture describe the flat model. Versions bumped (memcode 0.15.0, mod 0.4.0).
- Step 8 (asked after step 7): inference kinds as a running list. `memcode/kinds.py` holds every kind the memory
  agent looks for (topic, what to look for, example); the prompt, the schema's topics and the profile floor come from
  it. New kinds: infra, deployment, branching, location, reference. New `unusual` flag (column `memories.unusual`):
  set when a memory differs from the usual way for this kind of project; kept from a rating of 3, +1 in the start
  block's ranking, shown as `(topic, unusual)`. memcode keeps up to 6 candidates per piece of log (was 4).
- Live check (Haiku, a synthetic shop-service log): 7 candidates, kept 6, $0.0015: from you, the branching rule (off
  develop, never main); unusual, tests in checks/ with the working command; infra (EKS eu-west-1, ECR, RDS); the
  deployment pipeline (release.sh tags v*, deploy.yml staging then approved prod); the Grafana link; the runbook's
  location. A component summary rated 2 was dropped.
- Tests: 239 Python, 13 mod.

## Previous release (memcode 0.14.0)

- Facts know Maven (`pom.xml`, `./mvnw` when present) and Gradle (`build.gradle[.kts]`, `./gradlew`) builds, and show
  "built with Maven" next to the languages.
- The memory agent sees code: `[read] path | <opening 1500 chars>` for files the coding agent read, `[edited] path |
  <new text>` and `[wrote] path | <text>` for changes.
- It infers a project profile nobody states (stack, integration, component, structure, domain, convention), kept from
  a rating of 3, never pinned to file content, updated rather than duplicated; shown at session start as `## Project`.
- Live check (a Java session log, Haiku): 5 candidates, kept 4: the Stripe SDK wrapped by PaymentGateway and who calls
  it, OrderService as the central lifecycle entry point, OrderState's states and canCancel, the module test command.
- Arrows (`->`) survive the start block's bracket guard (shown as →).
- Tests: 227 Python, 13 mod.

## Previous release (memcode 0.13.0)

- The memory agent keeps a running conversation per coding session (agent/conversation.py, table agent_sessions).
  Every SessionStart (startup, resume, clear, compact) opens a fresh one: the worker sends the role and the full
  briefing at once. Each turn resumes it (`claude -p --resume`) with only the new log and a delta: which of its
  proposals memcode applied, memories changed by other paths, memories newly shown to the coding agent. It starts over
  after 30 calls or ~40k tokens; the opening's cost counts toward the session budget; a replaced conversation's saved
  file is deleted. Conversations live in `.memcode/agent/` (Claude Code saves them per working directory).
- Live check (temp repo, Haiku): opening $0.00035; a stated convention saved on turn 1; on turn 2 "same convention as
  I said earlier" proposed nothing new; context 3.9k -> 4.8k tokens over three calls.
- Tests no longer start real memory-agent calls: every test that runs a hook switches the agent off.
- Tests: 224 Python, 13 mod.

## Previous release (memcode 0.12.2)

- The memory agent's scan line counts environment facts as kept: `4 candidates, kept 3 (2 memories, 1 fact)`
  (agent.worker.scan_line). Tests: 220 Python, 13 mod.

## Previous release (memcode 0.12.1, memcode-status 0.3.0)

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

- Timely triggers during work: the held first write, recall after each command or edit, and the memory agent's flags
  (one turn late: it reads a turn after it ends). Nothing yet stops a command before it runs (Guardian).
- No shipped way to measure the memory agent after prompt changes (PLAN, next step 2).
- Checkouts share the store, so staleness and the map follow whichever checkout last started a session.
- Pattern triggers see only the last 200 events per session.

## How to verify and release

```text
python3 -m unittest discover -s tests          # 250 tests, offline
claude plugin test mods/memcode-status         # 13 mod tests
claude plugin validate .claude-plugin/plugin.json --strict
```

The minimum Python is 3.9 (bin/memcode MIN_PYTHON): when touching the code, also run the suite with a 3.9 interpreter
(`uv python install 3.9`, then `$(uv python find 3.9) -m unittest discover -s tests`).

Release: bump the version in `.claude-plugin/plugin.json`, the memcode entry of `.claude-plugin/marketplace.json` and
`memcode/mcp_server.py` (serverInfo); for the mod, `mods/memcode-status/.claude-plugin/plugin.json` and its
marketplace entry. Merge to master, then `claude plugin marketplace update memcode` and
`claude plugin update memcode@memcode --scope project` (and `memcode-status@memcode`), and restart Claude Code.
