"""Scorecard of every recorded live run (bench/live/RESULTS.md, Runs 1-12). No model calls, no network.

  python3 bench/scorecard.py            # markdown tables
  python3 bench/scorecard.py --json     # the same data as JSON

Every count below is copied by hand from the tables in bench/live/RESULTS.md (the run and table are cited per row).
Where RESULTS.md gives only a rate, the count is rate x runs, and the per-scenario table of the same run was checked
to sum to it (noted as "from per-scenario table"). Costs are reproduced exactly as recorded: "total" is the summed
later-session cost of a config, "per session" is what RESULTS.md calls per-run/per-session cost, "approx per config"
is a "~$x per config" remark (which in Runs 3-6 may include teaching sessions; RESULTS.md does not say). A derived
per-session cost (total / runs) is printed only where a total and its run count are both recorded, marked "derived".

Intervals: Wilson score 95% for each proportion; Newcombe hybrid score 95% for each difference of two proportions
(arms are independent samples). Runs 1-3 are development runs (scenarios tuned while fixing triggers; Run 3 also
contains a known scoring bug, fixed in 3b); only Runs 4-12 use frozen held-out sets.
"""
from __future__ import annotations

import argparse
import json
import math

Z = 1.959963984540054

# arm roles used for the headline deltas
NOMEM, BUILTIN, CLAUDEMD, MEMCODE = "nomem", "builtin", "claudemd", "memcode"

# Each run: id, title, frozen?, arms: list of (arm label, role or None, mistakes, runs, cost note), notes.
RUNS = [
    {"run": "1", "set": "dev: 1 scenario (floor effect)", "frozen": False, "model": "haiku",
     "source": "RESULTS.md 'Live Gate 1 run' table",
     "arms": [("none", NOMEM, 0, 4, {"total": 0.011}),
              ("memcode", MEMCODE, 0, 4, {"total": 0.010})],
     "note": "trap never fired even without memory: no signal"},
    {"run": "2", "set": "dev: tests_in_checks + run_via_qa (tuned on)", "frozen": False, "model": "haiku",
     "source": "RESULTS.md Run 2 table",
     "arms": [("none", NOMEM, 4, 8, {"total": 0.025}),
              ("memcode (before trigger fix)", None, 4, 8, {"total": 0.027}),
              ("memcode (after trigger fix)", MEMCODE, 0, 8, {"total": 0.032})],
     "note": "scenarios and the trigger fix were tuned after seeing the first run"},
    {"run": "3", "set": "dev: 6 scenarios", "frozen": False, "model": "haiku",
     "source": "RESULTS.md Run 3 table (counts from per-scenario table)",
     "arms": [("nomem", NOMEM, 9, 36, {"approx_per_config": 0.14}),
              ("builtin", BUILTIN, 11, 36, {"approx_per_config": 0.14}),
              ("memcode", MEMCODE, 6, 36, {"approx_per_config": 0.14})],
     "note": "commit_prefix 3/6 in every arm was a scoring bug (fixed in 3b); builtin wrote memory 0/18"},
    {"run": "3b", "set": "dev: commit_prefix + logging_not_print re-run", "frozen": False, "model": "haiku",
     "source": "RESULTS.md Run 3b re-run table",
     "arms": [("nomem", NOMEM, 5, 12, {"approx_per_config": 0.04}),
              ("builtin", BUILTIN, 4, 12, {"approx_per_config": 0.04}),
              ("memcode", MEMCODE, 0, 12, {"approx_per_config": 0.04})],
     "note": "these two scenarios drove the fix (tuned on)"},
    {"run": "4", "set": "heldout (frozen)", "frozen": True, "model": "haiku",
     "source": "RESULTS.md Run 4 table (counts from per-scenario table)",
     "arms": [("nomem", NOMEM, 9, 40, {"approx_per_config": "0.13-0.18"}),
              ("builtin", BUILTIN, 13, 40, {"approx_per_config": "0.13-0.18"}),
              ("claudemd", CLAUDEMD, 0, 40, {"approx_per_config": "0.13-0.18"}),
              ("memcode", MEMCODE, 6, 40, {"approx_per_config": "0.13-0.18"})],
     "note": "later sessions NOT clean copies (session-1 code leaked style into nomem); old untrusted framing"},
    {"run": "5", "set": "heldout2 (frozen, clean copies)", "frozen": True, "model": "haiku",
     "source": "RESULTS.md Run 5 table",
     "arms": [("nomem", NOMEM, 50, 50, {"approx_per_config": "0.19-0.21"}),
              ("claudemd", CLAUDEMD, 0, 50, {"approx_per_config": "0.19-0.21"}),
              ("memcode (fixed framing)", MEMCODE, 0, 50, {"approx_per_config": "0.19-0.21"}),
              ("memcode_legacy", None, 15, 50, {"approx_per_config": "0.19-0.21"})],
     "note": "framing A/B: same stored memories, only the wrapper differs"},
    {"run": "6", "set": "heldout3 (frozen, harder)", "frozen": True, "model": "haiku",
     "source": "RESULTS.md Run 6 table",
     "arms": [("nomem", NOMEM, 50, 50, {"approx_per_config": "0.20"}),
              ("claudemd", CLAUDEMD, 0, 50, {"approx_per_config": "0.20"}),
              ("memcode (pre-fix code)", MEMCODE, 12, 50, {"approx_per_config": "0.20"})],
     "note": "memcode losses are capture gaps (m_stated_as_info 0/5 stored; one rule missed in m_four_rules)"},
    {"run": "7", "set": "heldout4 (frozen, capture changes)", "frozen": True, "model": "haiku",
     "source": "RESULTS.md Run 7 tables",
     "arms": [("nomem", NOMEM, 50, 50, {}),
              ("claudemd", CLAUDEMD, 0, 50, {}),
              ("memcode (as scored)", MEMCODE, 12, 50, {}),
              ("memcode (audited)", None, 11, 50, {})],
     "note": "n_info_tabs (descriptive phrasing) not captured by design: 10/10; the other 4 scenarios 1/40 audited"},
    {"run": "8", "set": "pressure1 valid scenarios (~109 seeded memories)", "frozen": True, "model": "haiku",
     "source": "RESULTS.md Run 8 table",
     "arms": [("nomem", NOMEM, 20, 20, {}),
              ("memcode, pinned only", None, 20, 20, {}),
              ("memcode + retrieval", MEMCODE, 0, 20, {}),
              ("claudemd_full", CLAUDEMD, 0, 20, {})],
     "note": "claudemd_full = every seeded memory written to CLAUDE.md (not user-saved rules)"},
    {"run": "9a", "set": "pressure2, 300 memories", "frozen": True, "model": "haiku",
     "source": "RESULTS.md Run 9 table",
     "arms": [("nomem", NOMEM, 40, 40, {"per_session": 0.0044}),
              ("claudemd_full", CLAUDEMD, 0, 40, {"per_session": 0.0072}),
              ("memcode + retrieval", MEMCODE, 0, 40, {"per_session": 0.0053})],
     "note": "accuracy tie; cost is the difference"},
    {"run": "9b", "set": "pressure2, 1,200 memories", "frozen": True, "model": "haiku",
     "source": "RESULTS.md Run 9 table",
     "arms": [("nomem", NOMEM, 40, 40, {"per_session": 0.0045}),
              ("claudemd_full", CLAUDEMD, 0, 40, {"per_session": 0.0139}),
              ("memcode + retrieval", MEMCODE, 0, 40, {"per_session": 0.0053})],
     "note": "CLAUDE.md cost grows with store size, retrieval stays flat"},
    {"run": "10", "set": "salience1 (constructed ranking set)", "frozen": True, "model": "haiku",
     "source": "RESULTS.md Run 10 table",
     "arms": [("nomem", NOMEM, 36, 36, {"total": 0.170}),
              ("memcode_retrieval (recency)", MEMCODE, 18, 36, {"total": 0.203}),
              ("memcode_salience", None, 9, 36, {"total": 0.206})],
     "note": "no CLAUDE.md arm; the memcode role is the shipped default ranking at the time (recency)"},
    {"run": "11", "set": "salience2 (constructed ranking set)", "frozen": True, "model": "haiku",
     "source": "RESULTS.md Run 11 table",
     "arms": [("nomem", NOMEM, 36, 36, {"per_session": 0.0043}),
              ("recency", None, 24, 36, {"per_session": 0.0058}),
              ("salience", None, 6, 36, {"per_session": 0.0056}),
              ("split (became default)", MEMCODE, 6, 36, {"per_session": 0.0057})],
     "note": "no CLAUDE.md arm"},
    {"run": "12", "set": "team transfer on heldout2 (teammate's clone)", "frozen": True, "model": "haiku",
     "source": "RESULTS.md Run 12 table",
     "arms": [("nomem", NOMEM, 20, 20, {}),
              ("memcode_local (nothing shared)", None, 20, 20, {}),
              ("memcode_team", MEMCODE, 0, 20, {}),
              ("claudemd_team", CLAUDEMD, 0, 20, {})],
     "note": "$0.30 total for later sessions (all arms); memcode needed an explicit `memcode share`"},
]


def wilson(k: int, n: int, z: float = Z) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def newcombe(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float, float]:
    """Difference p1 - p2 with Newcombe's hybrid score interval (method 10)."""
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1)
    l2, u2 = wilson(k2, n2)
    d = p1 - p2
    lo = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return d, lo, hi


def _cost(c: dict, n: int) -> str:
    if "per_session" in c:
        return f"${c['per_session']:.4f}/session"
    if "total" in c:
        return f"${c['total']:.3f} total (derived ${c['total'] / n:.4f}/session)"
    if "approx_per_config" in c:
        return f"~${c['approx_per_config']} per config"
    return "-"


def _arm(run: dict, role: str):
    return next((a for a in run["arms"] if a[1] == role), None)


def deltas(runs=RUNS, frozen_only: bool = False):
    """Per run and pooled: memcode minus baseline mistake rate, for each baseline role."""
    out = {}
    for base in (NOMEM, BUILTIN, CLAUDEMD):
        rows, K1 = [], [0, 0, 0, 0]
        for r in runs:
            if frozen_only and not r["frozen"]:
                continue
            m, b = _arm(r, MEMCODE), _arm(r, base)
            if not (m and b):
                continue
            d, lo, hi = newcombe(m[2], m[3], b[2], b[3])
            rows.append({"run": r["run"], "memcode": f"{m[2]}/{m[3]}", "baseline": f"{b[2]}/{b[3]}",
                         "delta": d, "lo": lo, "hi": hi})
            K1 = [K1[0] + m[2], K1[1] + m[3], K1[2] + b[2], K1[3] + b[3]]
        pooled = None
        if rows:
            d, lo, hi = newcombe(*K1)
            pooled = {"memcode": f"{K1[0]}/{K1[1]}", "baseline": f"{K1[2]}/{K1[3]}", "delta": d, "lo": lo, "hi": hi}
        out[base] = {"rows": rows, "pooled": pooled}
    return out


def render() -> str:
    L = ["# memcode scorecard (from bench/live/RESULTS.md, Runs 1-12; Haiku throughout)", "",
         "Mistakes = later-session runs that repeated the taught mistake. 95% Wilson intervals.", "",
         "| run | set | arm | mistakes/runs | rate [95% CI] | cost (as recorded) |", "|---|---|---|---|---|---|"]
    for r in RUNS:
        for label, role, k, n, c in r["arms"]:
            lo, hi = wilson(k, n)
            tag = f" ({role})" if role and role != label else ""
            L.append(f"| {r['run']}{'' if r['frozen'] else ' (dev)'} | {r['set']} | {label}{tag} | {k}/{n} | "
                     f"{k / n:.2f} [{lo:.2f}, {hi:.2f}] | {_cost(c, n)} |")
    L += ["", "Notes per run:"] + [f"- Run {r['run']}: {r['note']} ({r['source']})" for r in RUNS]
    names = {NOMEM: "no memory", BUILTIN: "built-in memory (Claude Code default)",
             CLAUDEMD: "CLAUDE.md (user explicitly saves each rule; Runs 8-9: every memory in CLAUDE.md; Run 12: committed)"}
    for frozen_only, title in ((True, "frozen held-out sets only (Runs 4-12)"), (False, "all runs incl. dev Runs 1-3b")):
        L += ["", f"## Headline deltas, {title}",
              "delta = memcode rate minus baseline rate (negative = memcode makes fewer repeated mistakes); "
              "Newcombe 95% CI. Pooling sums counts across heterogeneous sets: read it as a summary, not an estimate "
              "of any real-world rate.", "",
              "| comparison | per run (memcode vs baseline: delta [CI]) | pooled |", "|---|---|---|"]
        for base, d in deltas(frozen_only=frozen_only).items():
            per = "; ".join(f"R{x['run']} {x['memcode']} vs {x['baseline']}: {x['delta']:+.2f} [{x['lo']:+.2f}, {x['hi']:+.2f}]"
                            for x in d["rows"]) or "no run has both arms"
            p = d["pooled"]
            pooled = (f"{p['memcode']} vs {p['baseline']}: **{p['delta']:+.2f}** [{p['lo']:+.2f}, {p['hi']:+.2f}]"
                      if p else "-")
            L.append(f"| memcode vs {names[base]} | {per} | {pooled} |")
    L += ["", "Reading (from the rows above): against no memory memcode cuts repeated mistakes on every frozen set "
          "except Run 4 (contaminated nomem baseline). Against default built-in memory only Run 4 is frozen and its "
          "interval crosses zero; the builtin arm wrote almost nothing headlessly, so it behaved like no memory. "
          "Against a CLAUDE.md the user explicitly maintains, memcode ties at best (Runs 5, 8, 9, 12) and loses where "
          "capture missed a rule (Runs 4, 6, 7); CLAUDE.md never lost a run. memcode's measured advantages over "
          "CLAUDE.md are per-session cost at large stores (Run 9b: $0.0053 vs $0.0139) and not needing the user to "
          "say 'save this'."]
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.json:
        print(json.dumps({"runs": RUNS, "deltas_frozen": deltas(frozen_only=True), "deltas_all": deltas()}, indent=1))
    else:
        print(render())


if __name__ == "__main__":
    main()
