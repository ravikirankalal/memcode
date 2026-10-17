# Hierarchical memory, storage budget, labels — implementation plan (coordinator)

Base: branch `ccr-aa3778d8-8nvyvz`. Everything new is OFF by default behind flags, so defaults and the frozen-set
prediction tests (`tests/test_heldout_frozen.py`) stay green. stdlib only. No O(n^2) per session (see bench/PERF.md:
session start <= ~2.2 s at 10k files / 20k memories).

## Flags
| flag | effect when on |
|---|---|
| `MEMCODE_HIER=1` | scope inheritance + per-level budget in retrieval and in the session-start block |
| `MEMCODE_CONSOLIDATE=1` | consolidation runs at session start; consolidated children are hidden from injection (lesson shown instead) |
| `MEMCODE_STORE_BUDGET=N` | storage cap enforced at session start (0/unset = off) |
Labels are always assigned (display/filter only, never ranking, never rendered into injected lines).

## Shared commit (coordinator lands it BEFORE implementers start)
1. `store._migrate`: additive columns on `memories`
   - `scope_path TEXT NOT NULL DEFAULT ''`  — scope node: '' repo, 'billing' dir, 'billing/x.py' file
   - `scope_kind TEXT NOT NULL DEFAULT 'repo'` — repo | dir | file | symbol
   - `parent_id INTEGER` — consolidation: child -> lesson id (NULL = top level)
   - `level INTEGER NOT NULL DEFAULT 0` — 0 raw, 1 lesson (2 reserved for principles)
   - `labels TEXT NOT NULL DEFAULT ''` — comma-separated, sorted
   - `evidence_count INTEGER NOT NULL DEFAULT 1` — lessons: number of children
   - indexes `idx_mem_scope(scope_path)`, `idx_mem_parent(parent_id)`
   `anchor_path` keeps meaning "what staleness is checked against"; `scope_path` is where the memory applies.
   Rules keep anchor_path='' (never stale) but may get a dir scope.
2. `store.scope_chain(path) -> ['billing/api/x.py', 'billing/api', 'billing', '']`.
3. `store.injectable_sql() -> str`: '' when MEMCODE_CONSOLIDATE is off, else ' AND m.parent_id IS NULL'
   (aliased `m`) — wired by the coordinator into `pinned._memory_rows_base` and `retrieval.score` row queries.
4. `memcode/maintenance.py: run(con, root)` called from `engine.session_start` (inside `_safely`), which calls,
   via guarded optional imports, `scope.rescope_new(con, root)` (A), `labels.backfill(con)`,
   `consolidate.run_if_enabled(con)`, `budget.enforce_if_enabled(con)` (B). Neither implementer edits engine.py.
5. Tests: migration (columns present, old `SELECT *` readers fine), injectable_sql off/on, maintenance tolerant of
   missing modules.

## Implementer A — scope hierarchy + per-level injection budget
Owns: NEW `memcode/scope.py`, `tests/test_scope_hier.py`; edits `memcode/triggers.py` (only `_write`: set scope),
`memcode/retrieval.py`, `memcode/pinned.py`, and `memcode/cli.py` ONLY inside a block marked `# --- scope (A) ---`.
- `scope.assign(con, trigger, text, anchor_path, anchor_symbol) -> (scope_path, scope_kind)`:
  rules (correction/manual): directories/paths named in the text (reuse `retrieval.path_tokens`) that exist in
  `paths` -> that dir (several -> their deepest common ancestor; none -> repo). Notes: anchor file -> file scope
  (symbol if anchor_symbol); dir anchor -> dir; '' -> repo. Team-imported memories: same rule.
- `scope.rescope_new(con, root)`: assign scope to rows still at default whose text/anchor implies otherwise
  (idempotent; O(n)); `scope.rescope_all` for the CLI.
- `scope.working_set(con, session, prompt)`: prompt path tokens + files edited this session (reuse
  `retrieval._active_files`), normalized to repo-relative.
- Retrieval under MEMCODE_HIER: a memory is eligible if its scope is '' (repo) or lies on the scope_chain of some
  working-set path; off-chain dir/file memories are excluded (unless the prompt names them — keep path mention).
  Ordering/budget: allocate TOP_K by level, nearest scope first (file/symbol, then deepest dir ... then repo),
  each level ranked by the existing score; split promotions still apply on top. Document the exact allocation.
- Session-start block under MEMCODE_HIER: rules section shows repo-scope rules (oldest -> newest, MAX_RULES);
  dir-scoped rules are NOT dumped at start (they arrive with retrieval when working there) but the Map marks dirs
  that hold scoped rules, e.g. `billing/ [3 rules]`, so the agent knows to look (memory_search / mention path).
  Keep shown_ids/count_injected correct (rules lines unchanged in format).
- CLI: `memcode rescope`, `memcode list --scope DIR` (in the A block).
- Tests: assign() for rule phrasings ("every module under billing/ ...", "in api/handlers ...", none -> repo,
  two dirs -> common ancestor, nonexistent dir -> repo); working_set; eligibility + nearest-first allocation;
  flags-off equivalence (seeded store: retrieval ids and render_pinned text identical with and without the
  shared columns populated); the frozen tests stay green; perf: rescope_new O(n) on 20k rows.

## Implementer B — abstraction hierarchy (consolidation) + storage budget + labels
Owns: NEW `memcode/consolidate.py`, `memcode/budget.py`, `memcode/labels.py`, `tests/test_consolidate.py`,
`tests/test_budget.py`, `tests/test_labels.py`; edits `memcode/salience.py` (lesson evidence), `memcode/mcp_server.py`
(label filter on memory_search), and `memcode/cli.py` ONLY inside a block marked `# --- abstraction (B) ---`.
- `consolidate.run(con, now) -> dict` deterministic: group level-0, top-level, non-stale memories that are NOT
  user rules (trigger != 'correction'/'manual') and not team-imported, by (trigger, anchor dir-or-file, text
  signature = text with paths, numbers, quoted/backticked spans normalized). Group size >= 3 -> create or update
  ONE lesson row (trigger 'lesson', level 1, text e.g. "5 similar fail_to_fix notes on billing/x.py: <most recent
  representative text>", scope_path/anchor_path = common, evidence_count = N, labels = union, confidence = max,
  created_at = oldest child, updated_at = newest child) and set children.parent_id. Idempotent and incremental;
  O(n log n). Never merges two groups whose signatures differ (control: similar-looking but different notes).
  A child that goes stale or is forgotten updates the lesson count; a lesson with < 2 live children dissolves.
  `run_if_enabled(con)` checks MEMCODE_CONSOLIDATE. Model summarization: NOT now (note as follow-up).
- salience: a lesson's evidence includes its children (recurrences = evidence_count-1 decayed by child ages).
- `budget.enforce(con, cap) -> dict`: if live memories > cap, evict in order: (1) stale level-0, oldest first;
  (2) consolidated children (their lesson keeps the count — "merge before evict"); (3) low-evidence derived notes
  (retry, dep_change) by salience ascending. NEVER evict trigger in ('correction','manual'), team-imported, or
  lessons. Returns counts by reason. `enforce_if_enabled` reads MEMCODE_STORE_BUDGET.
- `labels.VOCAB` (justify in docstring), e.g. testing, build, style, naming, git, deps, security, env, perf, api,
  data, docs, ci; `labels.auto(trigger, text, anchor_path) -> list[str]` (keyword/path/trigger rules, precise
  rather than complete); `labels.backfill(con)` labels rows with labels=''; user labels via CLI
  `memcode label ID +x -y`, `memcode list --label X`; MCP memory_search gets optional `label` filter.
  Labels never change ranking or injected text.
- CLI: `memcode consolidate [--dry-run]`, `memcode budget N [--dry-run]`, `memcode label ...`, `list --label`.
- Tests: grouping (3 similar -> 1 lesson; 2 -> none; different signatures not merged; rules never merged; team
  never merged); idempotence; dissolve; injection with flag on shows lesson not children, flag off unchanged;
  budget eviction order and the never-evict set; labels auto precision on a fixture; flags-off equivalence;
  perf: consolidate + budget on 20k rows well under 1 s.

## Merge plan
A and B work in their own worktrees; first step for each: `git merge --ff-only ccr-aa3778d8-8nvyvz` (shared commit).
They commit locally, never push. Coordinator merges A then B, resolves `cli.py` blocks, runs the full suite and
bench/perf.py, then hands to testers (bench-scope, bench-abstraction) for offline predictions and live runs.

## Not now
Model-based summarization; labels in ranking; principles (level 2); changing default ranking. Adoption of any flag
as default only after its own pre-registered gate passes.
