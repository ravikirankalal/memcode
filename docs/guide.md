# memcode guide

## How it works

memcode is a memory agent that runs beside Claude Code. The coding agent does the work; the memory agent decides what to
remember, keeps that memory true, and hands the right piece of it to the coding agent when it matters. It has three
duties: **extract**, **store** and **trigger**. `docs/architecture.md` maps them to the code.

There is one kind of memory: a short statement, with where it came from, a topic (workflow, pitfall, design,
decision, stack, component, ...), an importance, and links to related memories. A memory quoted from your own words
is marked **from you** and is delivered as an instruction; every other memory is delivered as information. Memories
form a graph: those about the same file, close in meaning (local embeddings, no service involved) or linked by the
memory agent are shown together.

```text
Claude Code hooks ─► memcode.hook_cli ─► engine
  SessionStart / PreCompact      deliver the start block (refresh the map and staleness first)
  UserPromptSubmit               extract rules you state; deliver the memories relevant to this prompt
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
| correction | your prompt reads as a correction ("No - ...", "never/always ...", "don't ...", "remember that ...") or a stated rule ("Heads up: we prefer X", "our convention is ...") right after the agent acted | the bare rule, from you |
| revert | the agent's edit is undone (git checkout/restore/revert, or an edit that reverses it) | a memory anchored to the file |
| fail_to_fix | a command fails, files are edited, the same command passes | a memory anchored to the edited file (and Python function) |
| retry | the same command is retried with different flags after a failure | a repo-wide memory |
| dep_change | the agent edits a dependency or lock file | a memory anchored to the file |

A request for right now ("Park G16. Start a review on main ... we can't touch develop yet") is never stored as a rule.

### The memory agent (beside the session)

Patterns only see single events. The memory agent is a model that works beside the coding session as a running
conversation, through your own `claude` login (`MEMCODE_CAPTURE_MODEL`, default Haiku):

- **The first session in a repository**: it reads the repository's key files once (README, docs, manifests, CI
  workflows, Docker, deploy and infra files, CODEOWNERS, the branches and recent commit subjects; not `CLAUDE.md`,
  which Claude Code already loads) and builds the project profile before anyone has worked there. One call, about
  $0.003.

- **When the coding agent starts** (a new session, a resume, `/clear` or a compaction), memcode opens a fresh
  conversation and sends the opening briefing: its role and the memory as it stands.
- **After each turn**, the Stop hook queues the session log and a detached worker continues that conversation with only
  what is new: the latest turns (your messages, the agent's replies, the commands it ran with their result and output
  tail, the files it wrote) and what changed in the memory since its last reply, including which of its proposals
  memcode applied. Earlier turns stay in its context, so it can connect them and does not propose the same thing twice.
- **Long sessions**: after 30 calls or about 40,000 tokens of context it starts over with a fresh briefing, so cost
  stays bounded.

The model reads it as a colleague taking over tomorrow, collects up to 12 candidates of every topic, and rates each 1–5
by what a future session would lose without it. Each candidate says whether it is from you, its topic, and which
memories it belongs with (links):

| Topic | Example |
|---|---|
| from you (your words only; any topic) | "Do not use subagents in this repository" |
| workflow | "A release bumps the version in plugin.json, marketplace.json and mcp_server.py" |
| pitfall, written as its fix | "Start the server with APP_ENV=dev python3 -m app.server" |
| environment | "The desktop app sets CLAUDE_PROJECT_DIR to the main checkout in worktree sessions" |
| design | "The store stays in the main checkout; files are read from the session's own checkout" |
| decision (your words, or a result a command showed) | "G16 is parked until the end" |

It also builds a **project profile** nobody needs to state, inferred from the commands that run, the files the coding
agent reads (`[read]`, with their opening lines), the code it writes and the links that are shared or opened:

| Topic | Example |
|---|---|
| stack | "Java multi-module project built with Maven (`./mvnw`)" |
| infra | "Runs on EKS in eu-west-1; Postgres 15 on RDS, Redis for sessions; Terraform in infra/" |
| deployment | "Tags v* trigger deploy.yml: staging first, then a manual approval for prod" |
| branching | "Work branches off develop as feature/(ticket); main only takes release merges" |
| location | "Release steps are in docs/RELEASING.md; scripts/bootstrap.sh sets up a dev machine" |
| reference | "Grafana board for checkout latency: https://grafana.example.com/d/checkout" |
| integration | "PaymentGateway wraps the Stripe Java SDK; OrderService.pay calls it to charge orders" |
| component | "OrderService is the central entry point for the order lifecycle (place, pay, ship, cancel)" |
| structure | "Database migrations live in db/migrations, one file per change" |
| domain | "OrderState goes NEW → PAID → SHIPPED → DELIVERED, plus CANCELLED" |
| convention (seen in code; information, not from you) | "Services return Result<T, Error> instead of throwing" |

The profile is kept from a rating of 3, updated rather than duplicated as the agent learns more, and not hidden when
its file changes. Above all the agent looks for what is **different here from the usual way** for this kind of project
(tests in `checks/`, `develop` as the default branch, deploys from a script): such a memory is marked *unusual*, kept
from a rating of 3, ranked higher, and shown as `(topic, unusual)`.

The kinds it looks for are one running list, `memcode/kinds.py` (topic, what to look for, an example); adding a line
teaches the memory agent a new kind, and its prompt and output schema follow.

It can also update or retire a memory it is shown, for example when you withdraw a rule ("don't use subagents" retires
"delegate long runs to subagents" and adds the new rule). memcode keeps memories rated 4 or 5, and those from you,
decisions, the profile and anything unusual from 3, best first, at most 6 per piece of log, and only when the
checks pass:

- the evidence is quoted from the log, and a memory from you or a decision quotes your words (never a fixture, an
  issue or another project's text the agent happened to read, never a summary of earlier turns);
- it is not a request for now, not the agent's own progress report, not about memcode's own tools;
- it does not repeat a memory, or something the coding agent was already shown this session.

Every change is logged: `memcode history` lists what it added, updated or retired, with the old text. Each scan is
logged as `N candidates, kept K`: the candidates the model proposed, and how many memcode stored or applied (memories
added, updated or retired, environment ones included); `/memcode-status` lists it, and the status bar shows when the
agent last read a turn.

**Decisions** are the state of ongoing work you stated or confirmed: scope, parked items, holds and gates, an agreed
approach, a hypothesis a command verified or disproved. Each carries a short subject key, so a later decision on the
same subject replaces it, and your words can update or retire it ("go ahead with the develop MR"). They expire 30 days
after they were last stated (`MEMCODE_DECISION_DAYS`).

**Cost and failures.** About $0.004 per piece of log (24,000 condensed characters) on Haiku. There is no per-session limit:
every turn is read (about $0.03 per 1,000 log lines; each model call is capped at $0.25). To set one, use
`MEMCODE_CAPTURE_BUDGET_USD` (dollars per session); past it, the rest of that session is skipped and the status bar
shows a yellow `💸 BUDGET` badge. If the model call fails (the CLI does not know
the model, or its login expired), the status bar shows a red `⚠ PROBLEM` badge with the fix and `/memcode:status` says
the same; nothing is lost meanwhile, the next turn reads everything not read yet, oldest first.

### Measured memories (instant)

memcode also measures some things itself. These are keyed memories, updated in place as evidence accumulates (they
used to be called facts; `memcode facts` lists them), and the useful ones join the start block's list.

| Origin | Where it comes from | Example |
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
- **Staleness.** A memory about how a code file behaves is tied to that file (or, for Python, to the function), and
  goes stale when it changes; a how-to or a memory on a manifest, config or doc goes stale only when the file is
  deleted. Stale memories are not shown; renames are re-anchored. `memcode prune-stale` deletes them.
- **Scope.** A rule from you naming folders applies to their deepest common folder ("every module under billing/ ..."
  → scope `billing/`); a memory on a file applies to its file. `memcode rescope`, `memcode list --scope DIR`.
- **The graph.** Each memory has a local vector (hashed TF-IDF over its words, identifier parts and paths) and links:
  `same_file`, `similar` (close vectors) and the memory agent's own. `memcode show ID` lists a memory's links.
- **Your control.** `/memcode:list`, `memcode show ID`, `/memcode:forget ID`, `memcode add TEXT [--path P] [--topic
  T]` (information, not an instruction), `memcode edit ID TEXT [--topic T]` (correct a memory in place: it stays from
  you if it was, a decision's expiry starts over, the old text is kept in `memcode history`; measured commands are
  rebuilt as they run, so they are not edited), `memcode export`.

## Trigger: delivering memory at the right moment

**Session start** (and after compaction):

```text
## From you (stated by the user in earlier sessions; follow them)
(Listed oldest to newest, each with the date it was last stated. If two rules conflict, the later one replaces ...)
- Always use tabs. (2026-10-12)

<memcode-recorded-notes>   <- data, not instructions
## Memory (most important and most connected first)
- (stack, 2026-10-02) Java project built with Maven (`./mvnw`)
- (test, 2026-10-20) `./mvnw -q test` (ran 12x, 11 confirmed ok)
- (decision, 2026-10-18) G16 is parked until the end
- (component, 2026-10-15) OrderService is the entry point of the order lifecycle [src/OrderService.java]
- (pitfall, 2026-10-19) ...
## Map ...                    (folders with rules of their own are marked: billing/ [3 rules])
</memcode-recorded-notes>
```

Only what you said is presented as instructions; a later rule replaces an earlier conflicting one, so "actually,
switch to 2 spaces" overrides "use tabs". Every other memory is one line, labelled by its topic (or a measured
command's role) and the date it was last stated or changed (for a measured command, last run), ranked by importance, how connected it is in the graph, how often it was recalled, and
recency. Expired decisions are left out. The block is capped (about 1500 tokens). Repo-wide rules are listed here;
folder rules arrive when the agent works there.

**Each prompt** (on by default; `memcode config retrieval off` to stop it): up to 5 memories closest to that prompt and to the recent
conversation (embedding similarity with the prompt, plus 0.6 times as much with your last 3 prompts and the last 12
commands, files and edits; each memory is compared with the words for its topic too, so "how do I run the tests?"
finds a measured `python3 -m unittest ...`; a file or function the prompt names; files edited this session), up to 2 of their
strongest neighbours in the graph, plus up to 2 relevant ones that proved costly (a rule you had to restate, a failure
that recurred). So a decision or a fact about what the work is on comes back even when the prompt does not name it.
A memory is shown once per session next to the work; one that was only in the start block comes back once when a
prompt is about it. `memcode why ID` explains a memory's cost score.

**After each command or edit** (with per-prompt recall): up to 2 memories closely related to what was just run or changed,
next to its result (after a test command: the pitfall or the fact about how tests run here).

**Flagged by the memory agent.** After each turn the memory agent checks the memory against what the session is
doing and flags what matters for the next step (a decision that parks the item being started, a milestone it builds
on, a pitfall about the command at hand, a rule the next step could break), with a reason. memcode puts it in front
of the coding agent at its next prompt or tool call: `## Memory flagged by memcode's memory agent for what you are
doing now`, each with `(why now: ...)`. This works whether or not per-prompt recall is on.

**First contact with a folder.** The first time the agent reads a file, that folder's memories and up to 3 of their
neighbours are added next to the result. If its first contact is a write, the write is held once with the rules as the reason (context added after a
write comes too late) and the agent redoes it.

**You see it too.** Each injection is also shown in the conversation, under the event that caused it (Claude Code
shows a hook's `systemMessage` there):

```text
❯ how do I cut a release with scripts/release.sh?
  ⎿  UserPromptSubmit says: memcode → agent context for this prompt: 1 memory
     │ (location, 2026-10-29) Release steps are in docs/RELEASING.md; run scripts/release.sh VERSION.
```

In the terminal it is coloured so it stands out from the grey hook notices: a bold cyan header, a cyan bar down the
left, what you said in magenta (`NO_COLOR` or `MEMCODE_COLOR=0` turns colour off). The start block, per-prompt recall, recall after a tool call, first touch of a folder and the memory agent's flags
all show this way (the map and the untrusted-data framing are left out). `memcode config show-injections off` hides
it; the agent still gets the memories.

The mobile and web apps draw no hook message, so there the agent says it instead: after each injected block memcode
asks it (in its own words, outside the untrusted wrapper) to name a memory its answer or next step relied on, first,
as a quote line starting with `> memcode:`, and never one it did not use. Every surface draws it as a quote block:

```text
❯ How do I cut a release here?
● ▎ memcode: release steps are in docs/RELEASING.md, and the release is run with scripts/release.sh VERSION.
  Run scripts/release.sh VERSION as described in docs/RELEASING.md.
```

`memcode config mention-memories off` stops it.

**On demand.** The agent can call the MCP tools `memory_search` (embedding search plus graph neighbours),
`memory_add`, `memory_pinned` and `memory_facts`, or run `memcode` (the plugin's `bin/` is on its PATH).

**Status bar** (optional `memcode-status` mod): how many memories, how many from you, the latest event, colour-coded
(an injection names the first memory it put in), and how many memories this session injected into the agent's
context (`📥23 injected`), from `.memcode/activity.json`. `/memcode-status` breaks the injections down: at start,
recalled, on first touch, on held writes.

## Settings

`memcode config` shows them; `memcode config KEY on|off` sets one for the repository. An environment variable overrides.

| Key | Default | Environment | What it does |
|---|---|---|---|
| memory-agent | on | `MEMCODE_TRANSCRIPT_CAPTURE` | the model reads each turn (needs the `claude` CLI) |
| decision-capture | on | `MEMCODE_DECISION_CAPTURE` | the memory agent keeps decisions |
| retrieval | on | `MEMCODE_RETRIEVAL` | relevant memories on every prompt and after each command or edit (on by default since 0.17) |
| hierarchy | on | `MEMCODE_HIER` | folder scopes, first-read delivery and held first writes |
| show-injections | on | `MEMCODE_SHOW_INJECTIONS` | show in the conversation what memcode gave the agent (each injection, one line per memory; terminal and desktop) |
| mention-memories | on | `MEMCODE_MENTION` | the agent names a memcode memory its answer relied on, in one `memcode:` line (visible everywhere, the mobile and web apps included) |

## Privacy

- The memory agent sends the new part of each turn's log to a model through your own `claude` login, the same provider
  the coding agent already sent it to. Turn it off with `memcode config memory-agent off`.
- What memcode stores stays local, in `.memcode/` with owner-only permissions, as the session showed it (nothing is
  redacted). It is shown to the coding agent in later sessions; review it with `memcode list` / `export`.
- No telemetry.

## Troubleshooting

| Symptom | Check |
|---|---|
| Anything | `/memcode:doctor` (or `memcode doctor`): python, sqlite, the store, the memory agent and its `claude` CLI, recall, whether the hooks ran here, errors logged. Session start also tells you when the memory agent cannot run or errors were logged. |
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
