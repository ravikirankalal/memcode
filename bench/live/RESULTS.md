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
