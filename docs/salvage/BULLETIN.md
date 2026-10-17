# Hierarchical memory: team bulletin (append-only)

Every agent on this project: READ this file before starting each step, and APPEND an entry whenever you
decide something others depend on (schema, function signatures, flags, rendered line formats), finish a
milestone, hit a blocker, or learn a fact about the codebase another agent would want. Never edit or delete
earlier entries. Format:

## <UTC time> <agent role> — <one-line headline>
<2-6 lines: what, where (file:function), what others must do or know>

Roles: coordinator, planner, impl-scope (A), impl-abstraction (B), bench (hier1), reviewer, runner.

---

## coordinator — bulletin created
Base branch: ccr-aa3778d8-8nvyvz in /home/user/memcode. Implementers work in their own git worktrees and
must not push; the coordinator merges. Run tests with: python3 -m unittest discover -s tests
New behaviour stays behind flags (default off) so tests/test_heldout_frozen.py predictions stay green.

## 20:31 coordinator — roster (SendMessage addresses)
- coordinator: "main"
- planner (design, read-only): a64b4db47c2a87d0b
- bench-scope (hier1 frozen set, scope hierarchy tests): ad2ad156070a3a46b
- bench-abstraction (consolidation / storage budget / labels tests): a1b24c660de502c39
- impl-scope (A) and impl-abstraction (B): ids posted here when they start (after the plan + shared schema commit).
Goal the user set for the testers: answer "is it useful, what do we gain over the run that does not use it" — flag-off vs flag-on on the same stores: repeated mistakes, tokens injected, latency, with pre-registered predictions.

## 20:32 coordinator — SCOPE WIDENED + real false-positive capture
The user's question is about the WHOLE memcode project: "is it useful, what do we gain over a run that does not
use it" — not only hierarchical memory. Hierarchy testers keep their tasks; two more testers join for whole-project
evaluation (bench-e2e, bench-precision).
Real dogfooding false positive (this repo, just now): the user's clarification to the agent "No, not just
hierarchical memory, I am talking about the memcode whole project..." was captured as a repo-wide project RULE
(correction trigger: starts with "No," after agent tool use) and injected on the next prompt. It is a correction of
the agent's interpretation of a request, not a codebase convention. Removed (memory #3). bench-precision owns
measuring this class; developers should not change triggers.py for it until the precision corpus exists.

## 20:45 bench-abstraction — shared measures agreed with bench-scope (both reports use these)
tokens_injected = chars/4 (pinned.TOKEN_DIVISOR) of: pinned_tokens (render_pinned text as engine.session_start returns it,
recomputed from rendered text so the new ## Facts section counts) + retrieval_tokens (retrieval.render after pinned
shown_ids are recorded in injections) + extra_tokens (any NEW injection point a flag adds); total = sum, each reported.
needed_surfaced: by id (pinned.shown_ids or retrieval ids) AND by text (per-scenario key regex in pinned+retrieval+extra
text; counts a lesson that keeps the fact). Latency: in-process perf_counter around engine.session_start / prompt and the
consolidation step, median/p95, stores seeded like bench/perf.py at 5k/20k. Flag-off baseline "flat" = MEMCODE_* stripped,
MEMCODE_RETRIEVAL=1, MEMCODE_RANK unset (= run.py memcode_split); flag-on = flat + the feature flag only.
Storage-budget checks cover the memories table only (facts are a separate table).

## 20:40 bench (hier1) — started; what the hier1 harness needs from impl-scope (A)
Harness: bench/live/hier1_candidates.py (offline_check per arm "flat" = defaults + MEMCODE_RETRIEVAL=1, "hier" = same + the
hier flag), tests/test_hier_bench.py. I simulate exactly: seed store -> tree.scan_repo/mark_stale -> pinned.render_pinned ->
record shown ids in injections -> retrieval.score/render(con) for the later prompt. A, please tell me (or post here):
 1. flag name (assumed MEMCODE_HIER=1) and whether it changes the session-start block, the prompt retrieval, or adds a NEW
    injection point (e.g. on Read/Edit of a file); give me the function(s) to call offline for each.
 2. how a correction rule gets its scope: at capture (triggers._prompt writing anchor_path='billing/'?) or derived at read
    time from the text? I need ONE callable to seed rules the way capture would, e.g. scope_for(con, root, text) -> anchor.
 3. whether a store written with the flag ON (scoped anchors) must behave exactly like today when the flag is OFF
    (flat retrieval's _mentions() gives +3 when a dir anchor like 'billing' appears in the prompt, vs +2 scope today).
 4. rendered line format of a scoped rule (shown_ids must still find it; I also use a key-text fallback).
Shared measures agreed with bench-abstraction: tokens = len(pinned + retrieval [+ any new injection]) / 4, reported per part.

## 20:33 coordinator — roster update
- bench-e2e (whole-project usefulness: scorecard + realistic multi-session "week" benchmark): a0c6bcefb0a5c8e3d
- bench-precision (capture precision/recall, junk harm, facts accuracy): afa9fcd029d400864
Testers: agree on shared measures (repeated mistakes with Wilson intervals; tokens injected from rendered text;
cost USD; tool calls / exploration; latency). Every paid run over ~$1 needs main's approval first.

## 20:55 bench-e2e — started (whole-project usefulness: scorecard + new realistic multi-session set "e2e1")
Owns NEW files only: bench/scorecard.py (offline table of Runs 1-12 from RESULTS.md, Wilson CIs, headline deltas),
bench/live/e2e1*.py (week-long realistic project set), bench/live/e2e_run.py (runner reusing run.make_repo/
fresh_with_memory/metrics; own claude() wrapper only for max-turns/tool allowlist, same MEMCODE_* stripping),
tests/test_e2e_bench.py. Arms: nomem, builtin, claudemd, memcode (MEMCODE_RETRIEVAL=1). Will also measure tool calls,
tokens, cost, wall time, exploration-to-run-tests, irrelevant injections. Plugin code under test: a `git archive`
snapshot (read-only) of the branch main tells me to use; default = integration branch (has facts). Not editing memcode/*.py.

## 20:55 bench-precision — started: capture precision corpus + junk harm + facts accuracy
Worktree branch worktree-agent-afa9fcd029d400864 (base master 681da90). Files: bench/precision/ (corpus.jsonl, evaluate.py,
harm.py, facts_eval.py, junk.py), tests/test_precision_bench.py. Real prompts: the store has only 18 user prompts, so I also
read the user's own turns from the session transcript (~64 distinct, read-only) and record what the agent did before each
(none/text_only/tool/edit) for the two-tier condition. Prompt-trigger code is identical on master and the branch.
Agreed with bench-abstraction: I expose bench/precision/junk.py JUNK=[{trigger,text,anchor_path,junk,why}] for their noise class.

## 20:39 coordinator — PLAN ready + shared schema commit landed (b9c7754)
Plan: /tmp/claude-0/-home-user-memcode/8067e07a-55bf-587b-83df-bff1f90a2e13/scratchpad/hier/PLAN.md (the planner agent was
stopped; the coordinator wrote the plan). Flags: MEMCODE_HIER=1 (scope inheritance + per-level budget),
MEMCODE_CONSOLIDATE=1 (lessons shown, children hidden), MEMCODE_STORE_BUDGET=N. Labels always assigned, display only.
New columns on memories: scope_path, scope_kind, parent_id, level, labels, evidence_count. Helpers:
store.scope_chain(path), store.injectable_sql(alias). memcode/maintenance.py calls scope.rescope_new(con, root),
labels.backfill(con), consolidate.run_if_enabled(con), budget.enforce_if_enabled(con) if present.
Testers: in your harness, set these env flags per arm; flag_present = the module exists (import memcode.scope /
memcode.consolidate). Developers start now from this commit.

## 20:40 coordinator — roster: developers started
- impl-scope (Implementer A: scope hierarchy, MEMCODE_HIER): a492677f210457041
- impl-abstraction (Implementer B: consolidation, storage budget, labels): a0c00099d02f8d44e
Pairs that should talk directly: impl-scope <-> bench-scope (ad2ad156070a3a46b); impl-abstraction <->
bench-abstraction (a1b24c660de502c39) and bench-precision (afa9fcd029d400864); impl-scope <-> impl-abstraction
on the shared files (cli.py blocks; pinned/retrieval are A's, salience/mcp_server are B's).

## 20:58 impl-abstraction (B) — started; draft interfaces (consolidate / budget / labels)
Worktree branch worktree-agent-a0c00099d02f8d44e (ff'd to b9c7754). API: consolidate.run(con, now=None)->dict, run_if_enabled(con);
budget.enforce(con, cap, now=None, dry_run=False)->dict, enforce_if_enabled(con); labels.VOCAB, auto(trigger,text,anchor)->list,
backfill(con)->int, parse(s), of(row). Lesson row: trigger='lesson', level=1, parent_id NULL, text "{N} similar {trigger} notes on
{anchor|the repo}: {newest child text}", provenance {"source":"consolidate","trigger":t,"sig":signature,"absorbed":[child ts...]}.
Grouping key (trigger, anchor_path, signature): signature keeps "double-quoted" snippets verbatim (revert detail), normalizes
`commands` to triggers._cmd_key with numbers-><n>, other paths-><path> (runs collapsed), numbers-><n>. Create at >=3; dissolve when
live children + absorbed < 2. Budget cap counts ALL memories rows; evicts (1) stale level-0 oldest (2) consolidated children oldest
(absorbed into lesson) (3) top-level retry/dep_change by salience asc; never correction/manual/lesson/team (source team or team_id).
labels column: '' = not yet labelled, '-' = labelled, none apply. VOCAB: testing build style naming git deps security env perf api data docs ci.

## 08:39 coordinator — all agents resumed after an API rate limit
All six agents stopped at ~21:00 UTC on a shared session rate limit (reset 00:50 UTC) and were resumed at 08:39 UTC
from their saved state. Six concurrent agents exhausted the limit in ~15 minutes: work economically (targeted reads,
targeted tests, commit at milestones). If you hit the limit again, your state is saved; the coordinator resumes you.

## 08:45 impl-scope (A) — MEMCODE_HIER interfaces fixed (code landing in worktree-agent-a492677f210457041)
API (memcode/scope.py): assign(con, trigger, text, anchor_path, anchor_symbol)->(scope_path, scope_kind);
rescope_new(con, root)->dict (always runs at session start, flag-independent, O(n)); rescope_all(con, root)->dict (CLI);
working_set(con, session, prompt, root=None)->set[str] (lowercase repo-relative); hier_enabled() = env MEMCODE_HIER=="1".
Scope rule: anchor!='' -> anchor (symbol|dir|file); anchor '' + correction/manual -> existing paths named in rule text,
file token -> its parent dir (rules never file-scoped), several -> deepest common ancestor, none -> repo; else repo.
rescope_new touches ALL levels only when row is at default ('' , 'repo'); re-anchor fix (scope!=anchor) only level 0.
-> impl-abstraction: lessons may set scope_path=anchor_path/scope_kind yourself; if you leave the default, rescope_new
   assigns scope=anchor at next session start. Kinds: repo|dir|file|symbol.
Retrieval (flag on): eligibility = repo scope | scope on chain of a working-set path | scope inside a ws path | named in
prompt; +SCOPE_W for on-chain scope not already path/active-scored; TOP_K: one slot per level nearest first
(file/symbol, dirs deepest->shallowest, repo), rest by score; split promotions unchanged. Pinned (flag on AND retrieval
on): rules section = repo-scope rules only; Map marks scope dirs/files "name/ [N rules]" / "x.py [1 rule]" right after
the name; Map title gains a legend when markers exist. ## Memories unchanged. Full spec sent to bench-scope.
cli.py: my block is `# --- scope (A) ---` ... `# --- end scope (A) ---`: adds `rescope` and `list --scope DIR`
via sub.choices["list"].add_argument, dispatched before the generic table.

## 08:40 coordinator — decision: "first touch" injection for directory-scoped rules
Risk (raised by impl-scope): under MEMCODE_HIER, dir-scoped rules leave the start block and arrive only via
retrieval, so a prompt without any path that leads the agent into billug/billing/ would never see billing rules (flat
shows them if among the newest 20). Decision: impl-scope provides scope.rules_for_path(con, session, path) ->
(text, ids): not-yet-shown rules/notes on the path's scope chain (excluding repo scope), nearest first, small cap,
retrieval framing, injections recorded with source='touch' (once per session). Coordinator wires it after merge into
engine.tool_result + hook_cli + hooks.json (PostToolUse on Read/Edit/Write/MultiEdit; Codex apply_patch; Gemini
read/write tools) under MEMCODE_HIER. bench-scope adds shape (f): prompt with no path, target dir found by
exploring — the shape where hierarchy is most likely to lose.

## bench-precision — capture precision measured; proposal ready (no memcode/ edits), commit b2da867
Corpus bench/precision/corpus.jsonl (222 turns: 68 real, 154 synthetic). CURRENT triggers: precision 0.44, recall 0.60
(39 TP / 49 FP / 26 FN). Real stream: 76 real user turns -> 1 capture, and it was junk (the "No, not just hierarchical
memory..." turn). Junk classes: corrections of the current change 15/15 captured, interpretation corrections 11/17,
one-off instructions 10/17, bare complaints 5/12, questions 3/21, task directions 5/31. Also a bug: the weak tier
(agent acted) omits _STRONG, so "Always keep X" after an edit is dropped. Proposal (bench/precision/proposal.diff, +
proposal_tests.diff for 2 tests that used "no, that's wrong" as their rule): dev P 0.89 R 0.60; independent held-out
sets (Haiku-written, after design): P 0.67->0.88 (R 0.45 same), P 0.73->0.94 (R 0.50->0.53). Full suite green on a
patched copy. Junk lands as trigger='correction' = shown at every session start, outside the untrusted wrapper.

## 2026-10-17 bench-abstraction — harness committed (worktree branch worktree-agent-a1b24c660de502c39, fafac8c)
bench/consolidation_eval.py (deterministic, no model calls): stores of 100/1k/5k memories (near-duplicate fail_to_fix/
revert/retry on hot files, stale, distractor + needed rules, a team rule and team note via .memcode-team.jsonl, 11
needed facts with prompts); arms flat / consol (MEMCODE_CONSOLIDATE=1) / budget (+MEMCODE_STORE_BUDGET=n/2) /
labels_user vs labels_empty. Adapter class Feature is the only place naming B's API (consolidate.run(con, now),
budget.enforce(con, cap), labels.auto(trigger, text, anchor_path), parent_id). Flag-off baseline at 1k/5k: needed
facts surfaced 6/11 and 4/11 (crowded rules rank ~100-500 behind same-file near-duplicates).
bench/live/consol1_candidates.py: 6 live scenarios: 3 gain (crowded rule x2, crowded manual note) and 3 controls
(unique revert among same-file noise, look-alike revert on a sibling file, retry whose flag variant is the fact).
Design simulation of B's announced grouping: gains flat miss -> consol hit; c_retry_flags flat hit -> consol MISS
(lesson keeps only the newest child's variants): a predicted harm, reported to B.

## 21:40 bench (hier1) — candidate set + harness committed (worktree-agent-ad2ad156070a3a46b @ 2311929); pilots starting
bench/live/hier1_candidates.py: ONE shared store (76 rules over 18 dirs + 5 repo-wide, 29 file notes), 9 scenarios:
nearest_crowded, parent_rule, grandparent_rule, repo_wide_old, and controls (flat hits) repo_wide_recent, two_dirs,
rule_names_sibling_file, no_path_in_prompt (coordinator's shape f; offline: hier NOT surfaced at prompt time, live
depends on first-touch), file_note. offline_check(sc) -> flat_*/hier_* incl. surfaced_at_prompt, needed_first_touch,
pinned/retrieval/extra/total tokens, shown_relevant/shown_irrelevant, needed_scope_path, hier_flag_present.
Flat today: surfaced only in the 5 controls; shows ~50 memories per task of which 4-10 are relevant; ~1500-1700 tokens.
First-touch: my adapter calls the first of engine.first_touch / scope.first_touch / engine.file_context /
scope.file_context / scope.touch_context as f(con, root, session, rel_path) -> text. Coordinator/A: tell me the real name.
NOTE for first-touch design: on PostToolUse, a Write that CREATES a file in the dir is the first touch, so the rules
arrive after that file is already written (most hier1 tasks create a new file). PreToolUse (or also on Read/Grep/ls of
the dir) would arrive in time.
Measure another checkout: HIER1_MEMCODE_SRC=<dir containing memcode/> python3 bench/live/hier1_candidates.py
