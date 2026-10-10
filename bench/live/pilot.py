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
from bench.live.candidates3 import CANDIDATES3  # noqa: E402
from bench.live.candidates4 import CANDIDATES4  # noqa: E402
from bench.live.pressure import CANDIDATES as _PC, REPO as _PREPO  # noqa: E402
PCANDS = [dict(c, files=dict(_PREPO)) for c in _PC]
from bench.live.pressure2_candidates import CANDIDATES as _P2  # noqa: E402
P2CANDS = [c for c in _P2 if c["name"].endswith("_s300")]   # pilots carry no memory, so one size suffices
from bench.live.salience1_candidates import CANDIDATES as _S1, files_for as _s1files  # noqa: E402
# Gate 2: the oracle carries ALL seven relevant rules, so it checks the needed rule is followed amid its competitors
S1CANDS = [dict(c, files=_s1files(c), oracle="Project rules: " + " ".join([c["target"]] + c["competitors"]))
           for c in _S1]


ORACLE = False


def one(args):
    sc, model = args
    repo = run.make_repo(sc)
    prompt = sc["later"] + (" " + sc["oracle"] if ORACLE else "")
    m = metrics.metrics(run.claude(repo, prompt, model, "nomem"), sc["trap_regex"], sc.get("trap_on", "cmd_path"),
                        sc.get("trap_path"))
    return sc["name"], m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=6)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--pool", default="1", choices=("1", "2", "3", "4", "P", "P2", "S1"))
    ap.add_argument("--oracle", action="store_true", help="append the scenario's rules to the prompt (traps must then be ~0)")
    ap.add_argument("--scenarios", default="", help="comma-separated names (default: the whole pool)")
    a = ap.parse_args()
    pool = {"1": CANDIDATES, "2": CANDIDATES2, "3": CANDIDATES3, "4": CANDIDATES4, "P": PCANDS, "P2": P2CANDS, "S1": S1CANDS}[a.pool]
    if a.scenarios:
        pool = [c for c in pool if c["name"] in a.scenarios.split(",")]
    global ORACLE
    ORACLE = a.oracle
    units = [(sc, a.model) for sc in pool for _ in range(a.repeats)]
    with cf.ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(one, units))
    out = {}
    for name, m in res:
        d = out.setdefault(name, {"hits": 0, "n": 0, "evidence": []})
        d["n"] += 1
        d["hits"] += m["trap_hit"]
        if m["trap_hit"]:
            d["evidence"].append(m.get("evidence_match") or m["evidence"])
    for name, d in out.items():
        print(f"{name:18s} {'oracle' if ORACLE else 'nomem'} trap rate {d['hits']}/{d['n']}")
    Path(HERE := ROOT / "bench" / "live" / "results").mkdir(parents=True, exist_ok=True)
    (HERE / (f"pilot{a.pool}{'_' + a.scenarios.replace(',', '+') if a.scenarios else ''}{'_oracle' if a.oracle else ''}.json")).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
