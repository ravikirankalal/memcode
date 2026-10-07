"""Gate 2 evaluator: does relevance x (1 + salience) beat recency/frequency ranking?

Usage: python3 bench/ablation.py [--k 3] [--distractors 20]

Offline plumbing, NOT evidence. For each scenario it replays the events through
the trigger engine, adds deterministic distractor memories (recent, frequently
"retrieved", irrelevant), then checks whether the memory holding the mistake's
key phrase lands in the top-k for the session-3 task prompt under each ranker.
Salience is only *evaluated* here; it is not used by the product (Phase 1 shadow
mode). Re-run on real logged data (salience_log + retrievals) to decide Gate 2.
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from bench.run import load_scenarios  # noqa: E402

WORD = re.compile(r"[a-z0-9_]+")


def relevance(query: str, text: str) -> float:
    q, t = set(WORD.findall(query.lower())), set(WORD.findall(text.lower()))
    return len(q & t) / (len(q) or 1)


def rankers(salience_of):
    return {
        "recency+frequency": lambda m, q: m["updated_at"] + 10.0 * m["uses"],
        "relevance": lambda m, q: relevance(q, m["text"]),
        "relevance*(1+salience)": lambda m, q: relevance(q, m["text"]) * (1 + salience_of(m)),
    }


def run(k: int, n_distract: int) -> dict[str, list[int]]:
    from memcode import store, salience
    from memcode.triggers import TriggerEngine
    hits = {name: [] for name in ("recency+frequency", "relevance", "relevance*(1+salience)")}
    for sc in load_scenarios(HERE / "scenarios"):
        root = tempfile.mkdtemp()
        con = store.connect(root)
        eng = TriggerEngine(con, root)
        for ev in sc["events"]:
            if ev["session"] < 3:
                eng.handle(dict(ev))
        now = time.time()
        for i in range(n_distract):
            mid = store.add_memory(con, "manual", f"unrelated note {i} about widget{i} layout",
                                   "", None, {}, 0.5)
            con.execute("UPDATE memories SET updated_at=? WHERE id=?", (now + 1 + i, mid))
        con.commit()
        rows = [dict(r, uses=0 if "unrelated" not in r["text"] else 3) for r in store.list_memories(con)]
        raw = {r["id"]: r for r in store.list_memories(con)}
        sal = lambda m: sum(salience.compute(con, raw[m["id"]]).values()) / 4
        query = next(e["text"] for e in sc["events"] if e["session"] == 3 and e["kind"] == "prompt")
        for name, fn in rankers(sal).items():
            top = sorted(rows, key=lambda m: -fn(m, query))[:k]
            for mk in sc["mistakes"]:
                hits[name].append(int(any(mk["key_phrase"] in m["text"] for m in top)))
    return hits


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--distractors", type=int, default=20)
    a = ap.parse_args()
    hits = run(a.k, a.distractors)
    print(f"| ranker | recall@{a.k} |\n|---|---|")
    for n, h in hits.items():
        print(f"| {n} | {sum(h)}/{len(h)} |")
    print("\n_Synthetic distractors; plumbing check, not evidence._")


if __name__ == "__main__":
    main()
