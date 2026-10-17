"""Live gate for the scope hierarchy (costs money: real `claude -p` runs, Haiku by default; NOT run in CI).

Every unit: a fresh shopfront repo, the shared hier1 history seeded into .memcode exactly as capture writes it, then ONE
later session with memcode as a plugin. Arms differ only in switches:
  flat   MEMCODE_RETRIEVAL=1 (default split ranking)            = memcode 0.7.0 defaults with retrieval on
  hier   flat + MEMCODE_HIER=1 (scoped rules, nearest-first retrieval, first-touch injection on Read/Edit)
Scored with the scenario's trap (bench/live/metrics.py, same as the pilots). Also read back from the unit's store:
whether the needed memory was injected and through which path (pinned / prompt / touch), and injected tokens.

  python3 bench/live/hier1_gate.py --repeats 6                     # both arms, every scenario
  python3 bench/live/hier1_gate.py --summarize FILE.json
Predictions are frozen in bench/live/hier1.py before the first run.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from bench.live import hier1_candidates as H, metrics, run  # noqa: E402
from bench.live.e2e_run import snapshot_plugin  # noqa: E402

# arm -> (run.claude config, extra switches). flat / hier: retrieval on. default / hier_noret: retrieval off, which is
# what an install gets unless the user turns retrieval on (the question for making MEMCODE_HIER the default).
ARMS = {"flat": ("memcode_split", {}), "hier": ("memcode_split", dict(H.HIER_ENV)),
        "default": ("memcode", {}), "hier_noret": ("memcode", dict(H.HIER_ENV))}


def one(args) -> dict:
    sc, arm, model, plugin_dir = args
    repo = run.make_repo(dict(sc, files=sc.get("files") or dict(H.FILES)))
    nid = H.seed_store(repo, sc)
    t0 = time.perf_counter()
    config, extra = ARMS[arm]
    events = run.claude(repo, sc["later"], model, config, extra_env=extra, plugin_dir=plugin_dir)
    m = metrics.metrics(events, sc["trap_regex"], sc.get("trap_on", "cmd_path"), sc.get("trap_path"))
    final = next((e for e in reversed(events) if e.get("type") == "result"), {})
    import re
    tp = re.compile(sc.get("trap_path") or r"$^")
    wrote = any(tp.search(p) for p in metrics.edit_paths(events)) or any(
        tp.search(str(f.relative_to(repo))) for f in repo.rglob("*.py"))
    inj = {"pinned": False, "prompt": False, "touch": False}
    try:
        con = sqlite3.connect(repo / ".memcode" / "memory.db")
        for (src,) in con.execute("SELECT source FROM injections WHERE memory_id=?", (nid,)):
            key = "pinned" if src == "pinned" else "touch" if src == "touch" else "prompt"
            inj[key] = True
        n_touch = con.execute("SELECT COUNT(*) FROM injections WHERE source='touch'").fetchone()[0]
        con.close()
    except sqlite3.Error:
        n_touch = None
    return {"name": sc["name"], "shape": sc["shape"], "control": bool(sc.get("control")), "arm": arm,
            "ok": bool(final) and not final.get("is_error"), "wrote_target": wrote,
            "trap_hit": bool(m["trap_hit"]) or not wrote,   # never writing the file is a failed task, not a pass
            "needed_injected": inj, "touch_injections": n_touch, "cost_usd": final.get("total_cost_usd", 0.0),
            "bash_calls": m.get("bash_calls"), "wall_s": round(time.perf_counter() - t0, 1),
            "evidence": m.get("evidence")}


def summarize(rows: list[dict]) -> str:
    from bench.scorecard import wilson
    rows = [r for r in rows if r["ok"]]
    names = list(dict.fromkeys(r["name"] for r in rows))
    arms = [a for a in ARMS if any(r["arm"] == a for r in rows)]
    hier_arms = [a for a in arms if a.startswith("hier")]
    L = ["| scenario | shape | " + " | ".join(f"{a} mistakes" for a in arms)
         + "".join(f" | {a}: needed via pinned / prompt / touch" for a in hier_arms) + " |",
         "|" + "---|" * (2 + len(arms) + len(hier_arms))]
    tot = {a: [0, 0] for a in arms}
    for n in names:
        cells = []
        for a in arms:
            rs = [r for r in rows if r["name"] == n and r["arm"] == a]
            k = sum(r["trap_hit"] for r in rs)
            tot[a][0] += k
            tot[a][1] += len(rs)
            cells.append(f"{k}/{len(rs)}")
        for a in hier_arms:
            hs = [r for r in rows if r["name"] == n and r["arm"] == a]
            cells.append(" / ".join(str(sum(r["needed_injected"][k] for r in hs)) for k in ("pinned", "prompt", "touch")))
        shape = next(r["shape"] for r in rows if r["name"] == n)
        L.append(f"| {n} | {shape} | " + " | ".join(cells) + " |")
    L.append("")
    for a, (k, n) in tot.items():
        lo, hi = wilson(k, n) if n else (0, 0)
        L.append(f"{a}: {k}/{n} mistakes [{lo:.2f}, {hi:.2f}], cost ${sum(r['cost_usd'] for r in rows if r['arm'] == a):.2f}")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=6)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--scenarios", default="")
    ap.add_argument("--set", default="hier1", choices=("hier1", "hier2"))
    ap.add_argument("--plugin-ref", default="HEAD")
    ap.add_argument("--out", default="")
    ap.add_argument("--summarize", nargs="+", metavar="JSON")
    a = ap.parse_args()
    if a.summarize:
        print(summarize([r for f in a.summarize for r in json.loads(Path(f).read_text())["rows"]]))
        return
    import importlib
    F = importlib.import_module(f"bench.live.{a.set}")
    pool = [sc for sc in F.SCENARIOS if not a.scenarios or sc["name"] in a.scenarios.split(",")]
    plugin_dir, sha = snapshot_plugin(a.plugin_ref)
    units = [(sc, arm, a.model, plugin_dir) for sc in pool for arm in a.arms.split(",") for _ in range(a.repeats)]
    with cf.ThreadPoolExecutor(a.workers) as ex:
        rows = list(ex.map(one, units))
    out = Path(a.out or ROOT / "bench" / "live" / "results" / f"{a.set}_gate_{a.model}_{int(time.time())}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"meta": {"set": a.set, "plugin_sha": sha, "model": a.model, "frozen_sha256": F.FROZEN_SHA256},
                               "rows": rows}, indent=1))
    print(summarize(rows))
    print(f"\nraw: {out}")


if __name__ == "__main__":
    main()
