"""Frozen hier1 set (scope hierarchy live gate). Do NOT edit: add a new set instead (tests/test_hier_bench.py checks the hash).

Built from bench/live/hier1_candidates.py (9 scenarios, shared shopfront history). Pilots (Haiku, 2026-10-17): without
memory every trap fired 6/6 in every scenario ($0.27); with every relevant memory in the prompt 0/4 everywhere except
c_auth_audit 1/4 ($0.26). All 9 kept.

Pre-registered predictions (offline check of the plugin as merged in 0.7.0, written before any live arm ran):
- "surfaced" = the needed memory reaches the agent (flat: pinned block or prompt retrieval; hier: also first touch,
  simulated offline as the agent touching the target file). A surfaced memory is expected to give ~0 mistakes (oracle
  pilot); an unsurfaced one ~ the nomem pilot (6/6).
- flat surfaces 5/9 (exactly the 5 controls): misses nearest_crowded, parent_rule, grandparent_rule, repo_wide_old ->
  expect those 4 at ~nomem rates on flat, the controls at ~0.
- hier surfaces 9/9; 2 of them (nearest_crowded, no_path_in_prompt) only via first touch, which live depends on the agent
  reading or editing a file in that folder BEFORE writing the target: those two are the uncertain cells.
Gate: hier total mistakes below flat (Wilson intervals), no control worse than flat by more than 1/6.
"""
from bench.live import hier1_candidates as _H

SCENARIOS = [_H.freeze(sc) for sc in _H.SCENARIOS]
FROZEN_SHA256 = "6b08d4930eb5ae61e9a7a668987587644c7fee2893f45e9ef230f6155b2b74b3"
PREDICTIONS = {
 "h_pricing_epoch": {
  "flat": False,
  "hier": True,
  "hier_via": "touch"
 },
 "h_checkout_footer": {
  "flat": False,
  "hier": True,
  "hier_via": "prompt"
 },
 "h_insights_schema": {
  "flat": False,
  "hier": True,
  "hier_via": "prompt"
 },
 "c_repo_header": {
  "flat": True,
  "hier": True,
  "hier_via": "pinned"
 },
 "h_repo_reviewed": {
  "flat": False,
  "hier": True,
  "hier_via": "pinned"
 },
 "c_jobs_run_id": {
  "flat": True,
  "hier": True,
  "hier_via": "prompt"
 },
 "c_auth_audit": {
  "flat": True,
  "hier": True,
  "hier_via": "prompt"
 },
 "c_alerts_prefix": {
  "flat": True,
  "hier": True,
  "hier_via": "touch"
 },
 "c_avatar_prefix": {
  "flat": True,
  "hier": True,
  "hier_via": "pinned"
 }
}
