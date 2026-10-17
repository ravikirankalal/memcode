"""Frozen hier2 set: untuned confirmation of the scope hierarchy, and the gate for making it the default.
Do NOT edit: add a new set instead (tests/test_hier2_bench.py checks the hash).

Built from bench/live/hier2_candidates.py (clinic project, 9 scenarios). Pilots (Haiku, 2026-10-17), before any memory
arm ran on this set: without memory 6/6 traps in 8 scenarios and 5/6 in c2_shift_hours; with every relevant memory in
the prompt 0/4 everywhere. Pre-freeze fixes driven by the pilots only: two traps judged code the rule does not cover
(the existing chart_scale; private helpers), and c2_shift_hours' prompt suggested the needed name ("night-shift
time" -> night_hours, 0/6 traps); reworded.

Pre-registered predictions (offline check, plugin at this commit; surfaced = the needed memory reaches the agent; a
surfaced memory is expected near the oracle pilot (~0 mistakes), an unsurfaced one near the nomem pilot (~6/6)):
  surfaced: flat 6/9, hier 9/9 (retrieval on); default 5/9, hier_noret 9/9
  (retrieval off, i.e. a default install). Per scenario in PREDICTIONS.
Gate for adopting MEMCODE_HIER as the default, BOTH pairs must pass:
  (1) hier vs flat and hier_noret vs default: total mistakes lower, with the Wilson 95% intervals not overlapping;
  (2) in each pair no control scenario is worse than its baseline by more than 1/6.
"""
from bench.live import hier2_candidates as _H2

SCENARIOS = [_H2.freeze(sc) for sc in _H2.SCENARIOS]
FROZEN_SHA256 = "efbc65ad8e4216b4fa5747c32000b57cd24682f9e84ff3d0a40357b9682b6fa3"
ENVS = {"flat": {"MEMCODE_RETRIEVAL": "1", "MEMCODE_HIER": "0"}, "hier": {"MEMCODE_RETRIEVAL": "1", "MEMCODE_HIER": "1"}, "default": {"MEMCODE_HIER": "0"}, "hier_noret": {"MEMCODE_HIER": "1"}}
PREDICTIONS = {
 "h2_slots_version": {
  "flat": False,
  "hier": True,
  "default": False,
  "hier_noret": True
 },
 "h2_claims_ledger": {
  "flat": True,
  "hier": True,
  "default": False,
  "hier_noret": True
 },
 "h2_exports_phi": {
  "flat": False,
  "hier": True,
  "default": False,
  "hier_noret": True
 },
 "h2_repo_license": {
  "flat": False,
  "hier": True,
  "default": False,
  "hier_noret": True
 },
 "c2_repo_header": {
  "flat": True,
  "hier": True,
  "default": True,
  "hier_noret": True
 },
 "c2_lab_code": {
  "flat": True,
  "hier": True,
  "default": True,
  "hier_noret": True
 },
 "c2_chart_rows": {
  "flat": True,
  "hier": True,
  "default": True,
  "hier_noret": True
 },
 "c2_remind_prefix": {
  "flat": True,
  "hier": True,
  "default": True,
  "hier_noret": True
 },
 "c2_shift_hours": {
  "flat": True,
  "hier": True,
  "default": True,
  "hier_noret": True
 }
}
