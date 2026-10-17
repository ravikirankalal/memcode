"""Does junk hurt? Deterministic part: where false-positive rules land and what they cost. No model calls.

  python3 bench/precision/harm.py [--json out.json]

1. crowding   One real rule plus k junk rules. The session-start block keeps the NEWEST MAX_RULES (20) rules, shows them
              oldest -> newest, and then cuts the joined text at token_cap*4//3 = 2000 chars, so the cut removes the
              NEWEST rules first. Measured: the k at which the real rule stops being shown, for junk of realistic
              lengths, with the real rule captured first (oldest) or last (newest).
2. lifetime   The captures the triggers actually make on corpus.jsonl (current vs proposed), stored in random orders
              (200 shuffles): rules shown per session start, how many are junk, junk tokens per session start, real
              rules stored but not shown.
3. retrieval  Per-prompt retrieval (MEMCODE_RETRIEVAL=1) over a store holding those captures: for each real user prompt of
              this repo, in a session where nothing was shown yet, how often a junk rule clears MIN_SCORE (it would be
              injected as "Project rules relevant to this request ... follow them").
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics as S
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

from bench.precision import evaluate as E  # noqa: E402
from memcode import pinned, retrieval, store  # noqa: E402

PREFIX = "Rule from user correction: "
REAL_RULE = "Never call pytest directly here; always run ./qa."
# junk of the length real conversational turns have (the dogfooding turn: 115 chars; long task clarifications are
# clipped at 240 by triggers._clip)
REAL_JUNK = "Not just heirarchical memory, i am talking about the memcode whole project. Looks like planning agent is complete."


def _rules_shown(con, root) -> list[str]:
    text = pinned.render_pinned(con, root)
    out, on = [], False
    for line in text.splitlines():
        if line == pinned.RULES_HEADER:
            on = True
        elif not line.strip():
            on = False
        elif on and line.startswith("- "):
            out.append(line[2:])
    return out, text


def _seed(con, texts):
    t0 = 1_700_000_000.0
    for i, t in enumerate(texts):
        mid = store.add_memory(con, "correction", PREFIX + t, "", None, {"session": "seed"}, 0.7, commit=False)
        con.execute("UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (t0 + i, t0 + i, mid))
    con.commit()


def _fresh(tmp, name):
    root = os.path.join(tmp, name)
    os.makedirs(root)
    Path(root, "app.py").write_text("x = 1\n")
    return root, store.connect(root)


def crowding() -> dict:
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        n = 0
        for jlen in (60, 115, 240):
            junk = (REAL_JUNK * 3)[:jlen]
            for where in ("real_oldest", "real_newest"):
                lost_at = None
                for k in range(0, 25):
                    n += 1
                    root, con = _fresh(tmp, f"c{n}")
                    js = [f"{i:02d} {junk}"[:jlen] for i in range(k)]
                    _seed(con, ([REAL_RULE] + js) if where == "real_oldest" else (js + [REAL_RULE]))
                    shown, _ = _rules_shown(con, root)
                    con.close()
                    if REAL_RULE not in shown:
                        lost_at = k
                        break
                out[f"junk_len={jlen},{where}"] = lost_at
    return out


def _captured(res):
    return [(r["stored"][len(PREFIX):].split(" (context:")[0], r["label"] == "rule") for r in res if r["captured"]]


def lifetime(caps, shuffles=200, seed=7) -> dict:
    rng = random.Random(seed)
    m = {"rules_shown": [], "junk_shown": [], "junk_tokens": [], "block_tokens": [], "real_stored_not_shown": []}
    with tempfile.TemporaryDirectory() as tmp:
        for s in range(shuffles):
            order = caps[:]
            rng.shuffle(order)
            root, con = _fresh(tmp, f"l{s}")
            _seed(con, [t for t, _ in order])
            shown, _ = _rules_shown(con, root)
            con.close()
            label = {pinned._one_line(t, 240): real for t, real in order}
            junk = [l for l in shown if label.get(l) is False]
            m["rules_shown"].append(len(shown))
            m["junk_shown"].append(len(junk))
            m["junk_tokens"].append(sum(len(l) + 3 for l in junk) / pinned.TOKEN_DIVISOR)
            m["block_tokens"].append(sum(len(l) + 3 for l in shown) / pinned.TOKEN_DIVISOR)
            m["real_stored_not_shown"].append(sum(1 for _, real in order if real) - (len(shown) - len(junk)))
    return {"stored": len(caps), "stored_junk": sum(1 for _, r in caps if not r),
            **{k: round(S.mean(v), 1) for k, v in m.items()}}


def retrieval_hits(caps, prompts) -> dict:
    os.environ["MEMCODE_RETRIEVAL"] = "1"
    with tempfile.TemporaryDirectory() as tmp:
        root, con = _fresh(tmp, "r")
        _seed(con, [t for t, _ in caps])
        real = {PREFIX + t for t, r in caps if r}
        q_junk = q_real = n_junk = 0
        examples = []
        for i, p in enumerate(prompts):
            scored = retrieval.score(con, root, f"q{i}", p)
            picked = retrieval.select(con, scored)
            j = [r for _, r in picked if r["text"] not in real]
            q_junk += bool(j)
            n_junk += len(j)
            q_real += any(r["text"] in real for _, r in picked)
            if j and len(examples) < 5:
                examples.append({"prompt": p[:100], "junk_rule": j[0]["text"][len(PREFIX):][:100]})
        con.close()
    return {"queries": len(prompts), "queries_with_junk": q_junk, "junk_injections": n_junk,
            "queries_with_real_rule": q_real, "examples": examples}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    items = E.load(HERE / "corpus.jsonl")
    with E.clean_env():
        out = {"crowding": crowding()}
        for arm, prop in (("current", False), ("proposed", True)):
            caps = _captured(E.capture(items, proposal=prop))
            out[f"lifetime_{arm}"] = lifetime(caps)
            out[f"retrieval_{arm}"] = retrieval_hits(caps, [r["text"] for r in items if r["source"] == "real"])
    print(json.dumps(out, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
