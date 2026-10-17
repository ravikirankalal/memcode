"""Pilots for the hier1 candidates (costs money: real `claude -p` runs, Haiku by default; NOT run in CI).

  python3 bench/live/hier1_pilot.py --repeats 6              # no memory: each trap must fire 6/6
  python3 bench/live/hier1_pilot.py --repeats 4 --oracle     # every relevant memory in the prompt: traps must be 0/4
Reuses bench/live/pilot.one (same repo setup, same nomem config, same metrics) on hier1_candidates.pilot_pool(), so
pilot.py itself is not edited. Writes bench/live/results/pilotH1[_oracle].json.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from bench.live import hier1_candidates, pilot  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=6)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--oracle", action="store_true")
    ap.add_argument("--scenarios", default="", help="comma-separated names (default: all)")
    a = ap.parse_args()
    pool = hier1_candidates.pilot_pool()
    if a.scenarios:
        pool = [c for c in pool if c["name"] in a.scenarios.split(",")]
    pilot.ORACLE = a.oracle
    units = [(sc, a.model) for sc in pool for _ in range(a.repeats)]
    with cf.ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(pilot.one, units))
    out = {}
    for name, m in res:
        d = out.setdefault(name, {"hits": 0, "n": 0, "cost_usd": 0.0, "evidence": [], "clean": []})
        d["n"] += 1
        d["hits"] += m["trap_hit"]
        d["cost_usd"] += m["cost_usd"] or 0.0
        (d["evidence"] if m["trap_hit"] else d["clean"]).append(m.get("evidence_match") or m["evidence"])
    total = 0.0
    for name, d in out.items():
        total += d["cost_usd"]
        print(f"{name:18s} {'oracle' if a.oracle else 'nomem'} trap rate {d['hits']}/{d['n']}  ${d['cost_usd']:.3f}")
    print(f"total ${total:.3f}")
    res_dir = ROOT / "bench" / "live" / "results"
    res_dir.mkdir(parents=True, exist_ok=True)
    tag = ("_" + a.scenarios.replace(",", "+") if a.scenarios else "") + ("_oracle" if a.oracle else "")
    (res_dir / f"pilotH1{tag}.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
