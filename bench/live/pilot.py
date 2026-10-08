"""No-memory pilot: how often does an agent with NO memory violate each candidate rule?

  python3 bench/live/pilot.py --repeats 6
Runs only the neutral `later` prompt (no correction, no plugin, auto-memory disabled).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from bench.live import metrics, run  # noqa: E402
from bench.live.candidates import CANDIDATES  # noqa: E402
from bench.live.candidates2 import CANDIDATES2  # noqa: E402


def one(args):
    sc, model = args
    repo = run.make_repo(sc)
    m = metrics.metrics(run.claude(repo, sc["later"], model, "nomem"), sc["trap_regex"], sc.get("trap_on", "cmd_path"))
    return sc["name"], m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=6)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--pool", default="1", choices=("1", "2"))
    a = ap.parse_args()
    pool = CANDIDATES2 if a.pool == "2" else CANDIDATES
    units = [(sc, a.model) for sc in pool for _ in range(a.repeats)]
    with cf.ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(one, units))
    out = {}
    for name, m in res:
        d = out.setdefault(name, {"hits": 0, "n": 0, "evidence": []})
        d["n"] += 1
        d["hits"] += m["trap_hit"]
        if m["trap_hit"]:
            d["evidence"].append(m["evidence"])
    for name, d in out.items():
        print(f"{name:18s} nomem trap rate {d['hits']}/{d['n']}")
    Path(HERE := ROOT / "bench" / "live" / "results").mkdir(parents=True, exist_ok=True)
    (HERE / ("pilot2.json" if a.pool == "2" else "pilot.json")).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
