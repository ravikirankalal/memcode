# Runtime performance (2026-10-16)

How much latency memcode's hooks add to an agent turn, and how it scales with repo size and store size.
Harness: `python3 bench/perf.py` (no model calls). Every number is a **fresh subprocess per hook call**, exactly as
an agent runs it, so Python start-up (~15-21 ms here) is included. 4-core Linux container, Python 3.13.
Retrieval on, default split ranking. Medians in ms (3-5 reps).

## Before: quadratic session start

Commit 4c28d03 (100-file repo):

| memories | session start (cold) | session start (warm) | prompt | tool result |
|---|---|---|---|---|
| 0 | 89 | 88 | 70 | 60-66 |
| 300 | 195 | 151 | 101 | 68-71 |
| 3,000 | **4,978** | **5,344** | 236 | 74-75 |
| 20,000 | **~165,000** (one cold + warm pair took ~5.5 min) | | | |

The shadow salience log recomputed every memory's evidence by rescanning the whole store (O(n^2)). Session start
has a 30 s hook timeout, so a large store would have silently started sessions with **no memory at all**. The
same scan also made split ranking's promotion check and salience ordering O(n^2). In-process profiling at 2,000
files and 3,000 memories: warm session start 10.9 s, of which 10.2 s salience; prompt 1.49 s, of which ~1.0 s
recompiling a boundary regex per memory (overflowing `re`'s cache).

## After (commit f4d62b4)

| files | memories | start (cold) | start (warm) | prompt | tool: shell | tool: edit | MCP search |
|---|---|---|---|---|---|---|---|
| 100 | 0 | 94 | 85 | 73 | 62 | 57 | 45 |
| 100 | 300 | 93 | 83 | 79 | 63 | 70 | 55 |
| 100 | 3,000 | 189 | 195 | 205 | 73 | 70 | 61 |
| 100 | 20,000 | 871 | 911 | 921 | 64 | 60 | 140 |
| 2,000 | 0 | 361 | 134 | 69 | 62 | 62 | 47 |
| 2,000 | 300 | 357 | 152 | 87 | 59 | 66 | 56 |
| 2,000 | 3,000 | 426 | 247 | 204 | 62 | 64 | 65 |
| 2,000 | 20,000 | 933 | 872 | 999 | 65 | 86 | 205 |
| 10,000 | 0 | 1,458 | 417 | 68 | 61 | 72 | 49 |
| 10,000 | 300 | 1,301 | 561 | 129 | 68 | 68 | 51 |
| 10,000 | 3,000 | 1,543 | 588 | 193 | 66 | 79 | 90 |
| 10,000 | 20,000 | 2,173 | 1,229 | 1,102 | 87 | 82 | 162 |

Same 100-file / 3,000-memory case: session start 5.0-5.3 s -> 0.19 s (~27x). 20,000 memories: ~2.7 min -> under 1 s.

## Reading
- **Tool hooks** (fired on every shell command and edit) stay at 57-87 ms everywhere, mostly interpreter start-up.
- **Session start** is driven by repo size when cold (hashing every file once: ~1.5 s at 10,000 files) and by store
  size when warm; worst case measured 2.2 s, far inside the 30 s timeout.
- **Per-prompt retrieval** scores every memory in Python: ~200 ms at 3,000 memories, ~1 s at 20,000. Fine for
  realistic stores (this repo's benchmarks used up to 1,200); an index (e.g. SQLite FTS) would be the next step if
  stores that large become real.

## Fixes
- `salience.Index` reads all evidence inputs once; per-memory evidence is dict lookups (used by the shadow log, split
  promotion and salience ordering). Equivalence with the row-by-row version: `tests/test_perf_equivalence.py`.
- Retrieval caches each memory's terms in `memories.terms`, keyed by a hash of its source text (edits refresh it).
- The path-mention check runs its regex only when the candidate text occurs in the prompt.
- `shown_ids` uses a precomputed set instead of scanning every line per memory.
