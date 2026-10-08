# Live Gate 1 run (2026-10-07): inconclusive

Command: `python3 bench/live/run.py --repeats 2 --model haiku` (Haiku, 1 scenario, 4 later-session runs per config, ~$0.02 total).

| config | runs | repeated-mistake rate | explore calls | cost USD |
|---|---|---|---|---|
| none | 4 | 0.00 | 1.0 | 0.011 |
| memcode | 4 | 0.00 | 0.8 | 0.010 |

## Reading
- **Not evidence either way.** The trap never fired even without memory: the agent reads `conftest.py` and runs `python3 -m pytest` on its own, so there was no mistake for memory to prevent (floor effect).
- **Plugin does load headlessly:** a separate check created `.memcode/memory.db` in the temp repo, so the SessionStart hook ran. Whether the correction turn produced a stored memory was not verified in this run.
- Tiny N, one model, one scenario.

## Next
Scenarios need traps a competent agent cannot infer from the repo (an arbitrary convention that exists only in the user's correction, e.g. "tests live in `checks/`, never `tests/`", or a required custom command). Verify per run that a memory was written before attributing any difference to memory.

---

# Run 2 (2026-10-07): first discriminating result, directional only

Two scenarios whose trap exists only in the user's correction (`tests_in_checks`: tests go in `checks/` not `tests/`; `run_via_qa`: run `./qa`, never `pytest`). Haiku, 2 repeats x 2 sessions per scenario = 8 later-session runs per config, ~$0.06 per config.

| config | runs | repeated-mistake rate | explore calls | cost USD | memories after session 1 |
|---|---|---|---|---|---|
| none | 8 | 0.50 | 0.1 | 0.025 | n/a |
| memcode (before trigger fix) | 8 | 0.50 | 0.4 | 0.027 | 0, 0, 0, 0 |
| memcode (after trigger fix) | 8 | 0.00 | 0.8 | 0.032 | 1, 1, 1, 1 |

## Reading
- **A real bug found by the benchmark:** the first run stored no memories. The correction trigger missed the phrasing "No - ..." and also required an agent *edit* before a correction, so a correction about a command could never fire. Fixed in `memcode/triggers.py` (with tests), after which every memcode run stored a memory and the repeated-mistake rate fell from 0.50 to 0.00.
- **Directional signal for Gate 1 only.** 8 runs per config, 2 scenarios, one model, and the scenarios and the trigger fix were tuned after seeing the first run. It is not statistically significant and not a fair test against built-in agent memory (CLAUDE.md / auto memory), which the roadmap's Gate 1 requires.
- Exploratory calls did not fall (0.1 -> 0.8): the pinned map is not yet shown to help there, and the sample is tiny.

## Next
Add a `builtin` config (agent writes its own CLAUDE.md/auto memory), more scenarios (at least 6, including ones needing the pinned map), N >= 10 per cell, and a held-out scenario set not used while tuning the triggers.

---

# Run 3 (2026-10-07): expanded benchmark. Gate 1 NOT demonstrated

3 configs x 6 scenarios x 3 repeats x 2 later sessions = 36 later-session runs per config. Haiku, ~$0.14 per config, raw data in `bench/live/results/raw.json` (gitignored). Configs: `nomem` (auto-memory disabled), `builtin` (Claude Code default memory), `memcode` (plugin on top of default memory).

| config | runs | repeated-mistake rate | explore calls | memory written in session 1 |
|---|---|---|---|---|
| nomem | 36 | 0.25 | 0.2 | n/a |
| builtin | 36 | 0.31 | 0.5 | 0/18 |
| memcode | 36 | 0.17 | 0.2 | 18/18 |

Untuned scenarios only (4 of 6; not used while fixing triggers): nomem 0.12, builtin 0.21, memcode 0.25 (24 runs each).

Per scenario, trap hits in later sessions (of 6):

| scenario | tuned on | nomem | builtin | memcode |
|---|---|---|---|---|
| tests_in_checks | yes | 0 | 0 | 0 |
| run_via_qa | yes | 6 | 6 | 0 |
| logging_not_print | no | 0 | 2 | 2 |
| commit_prefix | no | 3 | 3 | 3 |
| config_not_env | no | 0 | 0 | 1 |
| import_alias | no | 0 | 0 | 0 |

## Reading
- **The headline gain comes from one scenario.** `run_via_qa` is the only case where memcode clearly beats the baselines (0/6 vs 6/6), and it is a scenario the triggers were tuned on. On the untuned scenarios memcode is not better than no memory (0.25 vs 0.12; noise at this N).
- **Floor effect remains.** In 3 of 6 scenarios nobody makes the mistake even with no memory (the model complies with the task wording or infers the convention), so those cells carry no signal.
- **Capture works, retrieval/use is unproven.** memcode stored a memory in 18/18 runs, yet in `commit_prefix` (3/6 in every config) and `logging_not_print` the trap still recurred with the memory present. Either the memory text/pinned block did not carry the rule clearly enough, or the agent ignored it. Not yet diagnosed.
- **The `builtin` baseline is weak.** It wrote nothing in 0/18 runs (headless `-p` runs apparently do not persist Claude Code auto-memory, or my detection misses it), so `builtin` behaves like `nomem`. Gate 1 ("beats built-in memory") is therefore NOT tested fairly yet; a proper baseline needs the agent to write CLAUDE.md (e.g. a prompt "remember this in CLAUDE.md") and be loaded next session.
- N is tiny, one model, and the explore-call counts do not show the pinned map helping.

## Next
1. Diagnose retrieval: for `commit_prefix`/`logging_not_print`, dump the stored memory text and the SessionStart context the later session actually saw; improve how a correction is summarized (state the rule as an imperative, e.g. "Always start commit messages with 'PROJ-101: '") rather than quoting the user's turn.
2. Fix the `builtin` baseline so it genuinely persists a CLAUDE.md.
3. Replace floor-effect scenarios with traps the model falls into without memory (aim for nomem trap rate 0.3-0.7), then rerun with N >= 10 per cell.

---

# Run 3b (2026-10-07): diagnosis of run 3, and a re-run of the two affected scenarios

## Diagnosis
1. **Scoring bug, not a memcode failure (commit_prefix).** The trap regex `git commit(?!.*PROJ-\d+:)` could not see `PROJ-101:` on a later line of a heredoc commit (`git commit -F - <<'EOF' ...`), so correct commits were counted as mistakes. That produced the 3/6 in every config in run 3. Fixed with `re.S`; the metrics now also record the matched `evidence`, so every trap hit can be audited.
2. **Memory wording.** Memories stored the user's whole turn plus boilerplate (`User corrected the agent's edit to app.py: "No - ... Redo the commit and remember that.". Avoid repeating...`), anchored to an unrelated file and cut off in the pinned block. They now read as the bare rule: `Rule from user correction: Commit messages here must always start with 'PROJ-101: '. (context: app.py)` (`_imperative` in `memcode/triggers.py`, tested).
3. In a manual repro the old wording was already followed by the agent (it committed `PROJ-101: ...`), so the wording change is a cleanup, and the scoring fix is what moved the numbers.

## Re-run (commit_prefix + logging_not_print, 3 repeats x 2 later sessions, Haiku, ~$0.04 per config)

| config | runs | repeated-mistake rate | memory written in session 1 |
|---|---|---|---|
| nomem | 12 | 0.42 | n/a |
| builtin | 12 | 0.33 | 1/6 |
| memcode | 12 | 0.00 | 6/6 |

Evidence of the hits was inspected: nomem/builtin hits are real violations (bare `print(...)` in new code; commits without the `PROJ-101:` prefix).

## Caveats
- These two scenarios drove this fix, so they are now marked `tuned_on: true`. The honest untuned set is `config_not_env` and `import_alias`, and both sit at the floor (nobody errs), so they say nothing.
- Combined picture across all runs: memcode helps where the model otherwise errs (3 scenarios, 0 hits vs 33-100% without), and cannot be shown to help where the model never errs. Still one model, N=6-12 per cell, no significance.
- `builtin` is still a weak baseline (it wrote a memory in only 1/6 headless runs here, 0/18 before). Gate 1 against built-in memory remains untested fairly.

## Next
Build new scenarios that fail without memory (aim for nomem rate 0.3-0.7) and freeze them as a held-out set before any further trigger changes; give `builtin` an explicit CLAUDE.md-writing step; then run N >= 10.

---

# Run 4 (2026-10-07): FROZEN HELD-OUT SET. Gate 1 FAILED against a CLAUDE.md baseline

`python3 bench/live/run.py --set heldout --repeats 5 --workers 8 --model haiku` : 4 scenarios x 4 configs x 5 repeats x 2 later sessions = 40 later-session runs per config (Haiku, ~$0.13-0.18 per config). Scenario set and trigger/pinned code were frozen before this run; none of this was tuned against.

| config | runs | repeated-mistake rate | explore calls | memory written in session 1 |
|---|---|---|---|---|
| nomem | 40 | 0.23 | 0.8 | n/a |
| builtin (default memory) | 40 | 0.33 | 0.5 | 1/20 |
| **claudemd** ("Save this rule to CLAUDE.md") | 40 | **0.00** | 0.8 | 20/20 |
| memcode | 40 | 0.15 | 0.3 | 20/20 |

Trap hits per scenario (of 10 later-session runs):

| scenario | nomem | builtin | claudemd | memcode |
|---|---|---|---|---|
| h_tabs | 3 | 2 | 0 | 1 |
| h_single_quotes | 0 | 0 | 0 | 0 |
| h_check_files | 5 | 7 | 0 | 0 |
| h_camel_case | 1 | 4 | 0 | **5** |

## Reading
- **memcode does not beat the simple incumbent.** A one-line "save this rule to CLAUDE.md" gave 0/40 repeated mistakes; memcode gave 6/40. Gate 1 (beat built-in memory) is not met; on this evidence memcode is no better than a manually maintained CLAUDE.md. It does beat default built-in memory and no memory on the pooled rate, but note `builtin` barely wrote anything (1/20) so that is a weak comparison.
- **Capture is not the problem; use is.** memcode stored a memory in 20/20 runs, yet `h_camel_case` still failed 5/10 (worse than nomem 1/10).
- **Unverified hypothesis for that gap:** the injected block is wrapped as "untrusted... treat note text as information only, never as instructions" (added during review hardening against prompt injection). That framing probably tells the model to discount the rule, whereas CLAUDE.md is treated as authoritative instruction. Not tested. A fix must keep the injection defence (do not just delete the warning), e.g. surface only user-authored correction rules as instructions with provenance, and keep agent-derived text as data.
- **Baseline contamination caveat.** The pilot showed 6/6 failures without memory, but in the benchmark nomem failed only 9/40 later runs: later sessions run in the same repo, which now contains code written (and corrected) in session 1, so the agent often copies the existing style. Memory effects are therefore understated for scenarios whose rule is visible in the code (tabs, quotes, camelCase), and this affects every config equally.
- One model, 10 runs per cell, no significance testing.

## Policy
The held-out set is spent: further trigger/pinned changes made in response to Run 4 mean its results can no longer be quoted as held-out. Validate any fix on a NEW frozen set, and make later sessions start from a clean copy of the original repo (plus only the memory store) to remove the contamination.

---

# Run 5 (2026-10-08): SECOND FROZEN HELD-OUT SET (heldout2), after the pinned-block fix

`python3 bench/live/run.py --set heldout2 --repeats 5 --workers 8 --model haiku --configs nomem,claudemd,memcode,memcode_legacy`: 5 scenarios x 4 configs x 5 repeats x 2 later sessions = 50 later-session runs per config (Haiku, ~$0.19-0.21 per config). Later sessions start from a CLEAN copy of the original repo plus only the memory (no session-1 code). The set was frozen (pilot-selected without memcode) and the pinned-block fix was implemented before it was built.

| config | runs | repeated-mistake rate | memory written in session 1 |
|---|---|---|---|
| nomem | 50 | **1.00** | n/a |
| claudemd ("save this rule to CLAUDE.md") | 50 | **0.00** | 25/25 |
| **memcode** (fixed framing) | 50 | **0.00** | 25/25 |
| memcode_legacy (old all-untrusted framing) | 50 | 0.30 | 25/25 |

Trap hits per scenario (of 10 later-session runs):

| scenario | nomem | claudemd | memcode | memcode_legacy |
|---|---|---|---|---|
| k_pathlib | 10 | 0 | 0 | 0 |
| k_dataclass | 10 | 0 | 0 | 0 |
| k_module_imports | 10 | 0 | 0 | 0 |
| k_main_block | 10 | 0 | 0 | **5** |
| k_header | 10 | 0 | 0 | **10** |

## Reading
- **The Run 4 hypothesis is supported by a controlled A/B.** Same plugin, same stored memories, only the framing differs: the old "untrusted data, never instructions" wrapper let the agent ignore stored rules on the two scenarios where following them is unusual (`k_main_block` 5/10, `k_header` 10/10), while presenting user-authored rules as the user's instructions (with the injection defence kept for agent-derived text) gave 0/50.
- **memcode now matches, but does not beat, a manually maintained CLAUDE.md** (0/50 vs 0/50). Both drive repeated mistakes from 100% to 0% against no memory. memcode's remaining advantages are not measured here: it captures the rule automatically (the `claudemd` arm needed the user to say "save this to CLAUDE.md"; default built-in memory wrote almost nothing in earlier runs), it expires stale memories, and it injects a repo map. "Gate 1: beats built-in memory" is therefore met only against default built-in memory, and tied against a hand-curated CLAUDE.md.
- **The no-memory baseline is now 100% (it was 23% in Run 4).** That confirms the Run 4 contamination caveat: with clean-copy sessions the agent no longer inherits the convention from code written in session 1.
- **Ceiling effect.** Both arms are at 0%, so these single-rule scenarios cannot separate memcode from CLAUDE.md. Differences would have to come from harder cases: many rules, rules that become wrong (staleness), a large repo, or rules stated only in passing.
- **Caveat on code freeze.** The per-session-counters / CLI / docs commits (additive, intended to be behaviour-neutral, unit-tested) were merged while the last ~9 of 100 units were running, so the final units are not strictly on the frozen code. The symbol-level staleness change was merged only after the run finished.
- One model (Haiku), 10 runs per cell, no significance testing. Run 4 stands as the record that the old framing failed; this run validates the fix on a set built after it.

## Next
A harder, frozen set that can separate memcode from CLAUDE.md: (1) several rules at once, (2) a rule that later becomes wrong and must be superseded or expire, (3) a rule stated once in a long conversation, (4) a larger repo where the pinned map matters. Salience ranking (Phase 2) stays gated until a set like this shows a gain over CLAUDE.md.

---

# Run 6 (2026-10-08): THIRD FROZEN SET (heldout3, harder), run on pinned snapshot cf3afa9 = code BEFORE the supersession-note and statement-capture changes

5 scenarios x 3 configs x 5 repeats x 2 later sessions = 50 later-session runs per config (Haiku, ~$0.20 per config). Run by two parallel subagents (batches A and B) in a read-only worktree of `cf3afa9` so main-thread development could not contaminate it. Pilots beforehand: no memory 6/6 failures per scenario; rules stated in the prompt ("oracle") 0/4 failures per scenario.

| config | later-session runs | repeated-mistake rate |
|---|---|---|
| nomem | 50 | **1.00** (50/50) |
| claudemd ("save this rule to CLAUDE.md") | 50 | **0.00** (0/50) |
| memcode (pre-fix code) | 50 | **0.24** (12/50) |

Trap hits per scenario (of 10 later-session runs):

| scenario | nomem | claudemd | memcode | memcode stored a memory in session 1 |
|---|---|---|---|---|
| m_four_rules | 10 | 0 | **2** | 5/5 units |
| m_three_across_sessions | 10 | 0 | 0 | 5/5 |
| m_supersede | 10 | 0 | 0 | 5/5 |
| m_stated_as_info | 10 | 0 | **10** | **0/5** |
| m_rules_and_distractors | 10 | 0 | 0 | 5/5 |

## Reading
- **`CLAUDE.md` still wins on this harder set (0/50 vs 12/50 for memcode).** Gate 1 is therefore not met against a hand-maintained CLAUDE.md, and memcode's only measured advantage over it is automatic capture (the `claudemd` arm was told to save every rule).
- **Both memcode failure clusters are capture gaps, not retrieval gaps:**
  - `m_stated_as_info`: 0 memories stored, 10/10 failures. The old correction trigger did not recognise a rule stated as information ("Heads up: this team prefers single quotes"). The statement-capture change (merged after this snapshot) targets exactly this; it is NOT yet validated live.
  - `m_four_rules`: one unit (2 of its runs) stored 3 memories for 4 rules and then violated the missing one (`import os`). All four teaching prompts match the capture patterns offline, so the likely cause is the requirement that the agent *acted* since the previous prompt (a text-only reply to an "Also: ..." turn drops the rule). Unconfirmed; the replay is not reproducible.
- **Prediction that did not hold:** I expected `m_supersede` to favour CLAUDE.md because memcode had no supersession logic. memcode scored 0/10 on it even before the oldest-to-newest ordering and override note were added. On this evidence the override note was not needed; it stays as cheap insurance but its benefit is unmeasured.
- When memcode captured the rules it matched CLAUDE.md in 4 of 5 scenarios, including 4 rules at once, rules taught across two sessions, and rules interleaved with distractor tasks.
- One model (Haiku), 5 units per cell, no significance testing. The printed "runs" column counts later-session runs (2 per unit); the JSON has one result per unit.

## Next
1. Relax the capture condition (accept a correction when the agent has acted earlier in the session, not only since the last prompt), with a false-positive check.
2. Validate both capture changes on a NEW frozen set (heldout4) that includes stated-as-information rules and text-only intermediate turns. heldout3 is now spent for this purpose.

---

# Run 7 (2026-10-08): FOURTH FROZEN SET (heldout4), validating the capture changes, on pinned snapshot c71545b

Run by two parallel subagents in a read-only worktree. 5 scenarios x 3 configs x 5 repeats x 2 later sessions = 50 later-session runs per config (Haiku). Predictions were written into `heldout4.py` before any memcode run.

| scenario | prediction for memcode | nomem | claudemd | memcode | memcode stored (units) | verdict |
|---|---|---|---|---|---|---|
| n_info_header ("our standard is ...") | captured -> 0 failures | 10/10 | 0/10 | **0/10** | 5/5 (1 rule) | as predicted |
| n_info_tabs ("FYI ... we indent with tabs") | NOT captured -> 10/10 | 10/10 | 0/10 | **10/10** | 0/5 | as predicted |
| n_text_gap_main (rule after a Q&A turn) | captured -> 0 | 10/10 | 0/10 | **0/10** | 5/5 (1) | as predicted |
| n_text_gap_two_rules (2 rules, Q&A turns between) | captured -> 0 | 10/10 | 0/10 | **0/10** | 5/5 (2) | as predicted |
| n_mixed (info rule + Q&A gap + correction) | captured -> 0 | 10/10 | 0/10 | 2/10 as scored, **1/10 audited** | 5/5 (3) | one real miss |

| config | repeated-mistake rate (50 runs) |
|---|---|
| nomem | 1.00 |
| claudemd | 0.00 |
| memcode, as scored | 0.24 (12/50) |
| memcode, audited | 0.22 (11/50) |
| memcode, the 4 scenarios predicted to be captured | 0.05 as scored (2/40), **0.025 audited (1/40)** |

## Audit of the n_mixed hits
- Hit 1 was a **scoring false positive**: the evidence is an `Edit` fragment (`    path = Path(root) / name`) and the only clause that matched is "file does not start with `# Copyright Acme`", which cannot apply to a fragment. Across all 252 trap hits in every result file this is the only fragment hit. `metrics.py` now evaluates start-of-file clauses on whole files (`Write`) only; the frozen sets are unchanged.
- Hit 2 is a **real but borderline** violation: the file has the header, uses pathlib and single-quoted strings, but contains double-quote characters inside a string (`f'Log file "{name}" ...'`), and the rule said "never double quotes anywhere". It happened with all 3 rules stored, so it is a compliance miss, not a capture miss.

## Reading
- **The capture changes work as designed.** Every rule given as "our standard is ...", after a text-only Q&A turn, or mixed with other forms was stored (20/20 units in the four captured scenarios), and memcode then matched CLAUDE.md within one borderline miss (1/40 vs 0/40).
- **Pattern-based capture has a clear boundary,** confirmed by a pre-registered prediction: descriptive phrasing without a normative word ("we indent with tabs") is not captured, and that alone makes memcode lose to CLAUDE.md on this set (11/50 vs 0/50). Closing it with more patterns risks junk rules; a better fix is a capture step that can recognise a stated convention without keyword matching (for example a small model call), which would also trade away the "no model calls" property. Not decided.
- Every memcode failure in heldout3 and heldout4 except one borderline case traces to capture, not to the stored rule being ignored.
- The headless runs shared the launching session's id (see the harness fix after Run 6); resume was verified to keep context, so trap results stand.
- One model (Haiku), 10 runs per cell, no significance testing.

---

# Run 8 (2026-10-08): BUDGET-PRESSURE SET (pressure1), retrieval vs pinned-only vs CLAUDE.md

~109 seeded memories per scenario; the target is the oldest, so the capped pinned block omits it. Haiku, 5 repeats x 2 later sessions = 10 runs per cell. Main run on pinned snapshot 7f8aac5 (subagent); pinned-only arm re-run after a fix (see below).

**Valid scenarios (p_billing_header, p_tools_flags), 20 later-session runs per arm:**

| arm | repeated mistakes | offline prediction |
|---|---|---|
| nomem | 20/20 | (fails) |
| memcode, pinned only (re-run) | **20/20** | target not pinned -> fails like nomem: held |
| memcode + retrieval | **0/20** | retrieval surfaces the target first and alone: held |
| claudemd_full (all ~109 entries in CLAUDE.md) | 0/20 | - |

## Reading
- **Per-prompt retrieval rescues memories the capped pinned block drops:** 20/20 -> 0/20 with the same store. With retrieval memcode matches a CLAUDE.md that loads everything, while injecting only the one relevant memory per prompt.
- It does not beat CLAUDE.md here: ~109 entries still fit comfortably in Claude Code's context, so a full CLAUDE.md degrades nothing at this size. Whether CLAUDE.md degrades at larger sizes is untested.

## Problems found (and how they were handled)
1. **Environment leak (my setup error):** enabling memcode for this repo (`.claude/settings.json`, `MEMCODE_RETRIEVAL=1`) put the flag into this session's environment, and every benchmark child inherited it, so the original "pinned-only" arm had retrieval ON (it scored 0/20, identical to the retrieval arm). Fixed: arms now strip all inherited `MEMCODE_*` variables (with a test); the pinned-only arm was re-run (20/20 failures, as predicted). Earlier runs predate the settings change and are unaffected.
2. **Two invalid scenarios (my design error):** in `p_data_all` and `p_search_suffix` every arm failed (CLAUDE.md 10/10 and 8/10) because the agents correctly followed *distractor* rules for the same directories ("tests for data/ live in data/tests", "every change under data/ needs a changelog line"), creating test files and CHANGES.md inside the trap's path scope, which the target rule did not cover. Distractor areas overlapped target areas. They are excluded from the reading; a future set must keep distractor rules out of target directories.
