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
