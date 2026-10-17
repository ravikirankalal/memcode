"""FROZEN e2e1 set (2026-10-17): a realistic simulated week on the `shelf` project. DO NOT EDIT; add a new set instead.

Content = bench/live/e2e1_candidates.py (conventions, teaching week, measured sessions, judges) + bench/live/e2e1_project.py
(starter repo and canonical day states); the hash below covers both and is enforced by tests/test_e2e_bench.py.

Pilots (Haiku, later sessions from the canonical repo): oracle (all rules + facts in the prompt) 0/36 lesson mistakes;
no memory 22/54. Lessons no memory gets wrong (the PRIMARY cells): thu_recent C1 P2 P3 E1, fri_markdown C1 C2 P2 P3.
C3 C4 P1 E2 were 0/6 without memory (visible in the repo): kept as regression cells (memory must not break them).

Pre-registered predictions (written before any memory arm ran):
- memcode: offline replay of the teaching turns captures C1 C3 C4 P1 P2 P3 and MISSES C2 (descriptive phrasing). Expect
  primary-cell mistakes well below nomem except fri C2 (~like nomem); E1 only if the facts table picks up `make check`
  from the teaching sessions (a fact, never stated). Irrelevant injected lines on mon_question small.
- claudemd (user says "save this rule to CLAUDE.md" after each convention): near 0 on all conventions incl. C2; E1 like
  nomem unless the agent writes it down unasked.
- builtin: between nomem and claudemd.
- nomem: ~ the pilot (C1, P2, P3 mostly wrong; C2 on Friday; E1 on Thursday).
Primary comparison: memcode vs nomem and vs claudemd on the 8 primary cells, Wilson 95% intervals; cost per week.
"""
from bench.live.e2e1_candidates import CONVENTIONS, FACTS, JUDGE, KEYS, LATER, ORACLE, TEACH  # noqa: F401

PRIMARY = {"thu_recent": ["C1", "P2", "P3", "E1"], "fri_markdown": ["C1", "C2", "P2", "P3"]}
FROZEN_SHA256 = "eb92fcb5698c21f874baaf923e0695976597df8c0f7ed92e31e6ebc0f6e74752"
