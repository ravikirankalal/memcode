"""Capture precision/recall of memcode's prompt triggers on the labelled corpus. Deterministic, no model calls.

  python3 bench/precision/evaluate.py                       # current triggers, corpus.jsonl
  python3 bench/precision/evaluate.py --proposal            # with the proposed filter (bench/precision/proposal.py)
  python3 bench/precision/evaluate.py --corpus bench/precision/heldout.jsonl --proposal
  python3 bench/precision/evaluate.py --json out.json       # machine-readable results

Each item runs through the real hook entry points (memcode.engine.prompt / engine.tool_result) in a throwaway repo,
in its own session, after a simulated prefix that reproduces `prior_agent_action`:
  none       the item is the first prompt of the session
  text_only  neutral prompt -> Bash command -> neutral prompt (agent replied in text only) -> item
  tool       neutral prompt -> Bash command -> item
  edit       neutral prompt -> Edit of app.py -> item
"Captured" = a new trigger='correction' memory (what is injected as a user rule) was written by the item.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

from memcode import engine, store, triggers  # noqa: E402

NEUTRAL = "Please take a look at the failing build."
NEUTRAL2 = "Thanks."


def load(path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


@contextlib.contextmanager
def patched(proposal: bool):
    """Swap in the proposed TriggerEngine._prompt without editing memcode/."""
    if not proposal:
        yield
        return
    from bench.precision import proposal as P
    old = triggers.TriggerEngine._prompt
    triggers.TriggerEngine._prompt = P.proposed_prompt
    try:
        yield
    finally:
        triggers.TriggerEngine._prompt = old


@contextlib.contextmanager
def clean_env():
    saved = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith("MEMCODE_")}
    os.environ["MEMCODE_RETRIEVAL"] = "0"
    os.environ["MEMCODE_MODEL_CAPTURE"] = "0"
    try:
        yield
    finally:
        for k in list(os.environ):
            if k.startswith("MEMCODE_"):
                del os.environ[k]
        os.environ.update(saved)


def new_repo(tmp: str) -> str:
    root = os.path.join(tmp, "repo")
    os.makedirs(root, exist_ok=True)
    Path(root, "app.py").write_text("def add(a, b):\n    return a + b\n")
    return root


def run_prefix(con, root, sess, prior):
    bash = {"session": sess, "tool": "Bash", "input": {"command": "python3 -m pytest -q"}, "command": "python3 -m pytest -q",
            "exit_code": 1, "output": ""}
    if prior == "none":
        return
    engine.prompt(con, root, sess, NEUTRAL)
    if prior in ("tool", "text_only"):
        engine.tool_result(con, root, dict(bash))
    if prior == "text_only":
        engine.prompt(con, root, sess, NEUTRAL2)
    if prior == "edit":
        engine.tool_result(con, root, {"session": sess, "tool": "Edit", "input": {"file_path": os.path.join(root, "app.py"),
                                                                  "old_string": "return a + b",
                                                                  "new_string": "return int(a) + int(b)"},
                                       "file_path": os.path.join(root, "app.py"), "exit_code": 0, "output": ""})


def capture(items: list[dict], proposal: bool = False) -> list[dict]:
    """-> items with 'captured' (bool) and 'stored' (rule text or None)."""
    out = []
    with clean_env(), patched(proposal), tempfile.TemporaryDirectory() as tmp:
        root = new_repo(tmp)
        con = store.connect(root)
        try:
            for i, it in enumerate(items):
                sess = f"s{i}"
                run_prefix(con, root, sess, it["prior_agent_action"])
                before = con.execute("SELECT COALESCE(MAX(id),0) FROM memories").fetchone()[0]
                engine.prompt(con, root, sess, it["text"])
                new = con.execute("SELECT text FROM memories WHERE id>? AND trigger='correction'",
                                  (before,)).fetchall()
                # prefix prompts are neutral and must never capture; assert so a broken prefix cannot hide
                assert not con.execute("SELECT 1 FROM memories WHERE id<=? AND trigger='correction'",
                                       (before,)).fetchone(), "prefix captured a rule"
                out.append(dict(it, captured=bool(new), stored=new[0][0] if new else None))
                con.execute("DELETE FROM memories")          # independent items: no dedup across items
                con.commit()
        finally:
            con.close()
    return out


def prf(rows, positive=lambda r: r["label"] == "rule"):
    tp = sum(1 for r in rows if r["captured"] and positive(r))
    fp = sum(1 for r in rows if r["captured"] and not positive(r))
    fn = sum(1 for r in rows if not r["captured"] and positive(r))
    tn = len(rows) - tp - fp - fn
    p = tp / (tp + fp) if tp + fp else float("nan")
    rc = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * p * rc / (p + rc) if tp and (p + rc) else 0.0
    return {"n": len(rows), "tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": p, "recall": rc, "f1": f1}


def summarize(res: list[dict]) -> dict:
    s = {"overall": prf(res), "no_borderline": prf([r for r in res if not r.get("borderline")]),
         "by_source": {}, "by_category": {}, "by_prior": {}}
    for key, field in (("by_source", "source"), ("by_category", "category"), ("by_prior", "prior_agent_action")):
        groups = defaultdict(list)
        for r in res:
            groups[r[field]].append(r)
        s[key] = {g: prf(rs) for g, rs in sorted(groups.items())}
    s["false_positives"] = [{"id": r["id"], "category": r["category"], "prior": r["prior_agent_action"],
                             "text": r["text"], "stored": r["stored"]} for r in res
                            if r["captured"] and r["label"] != "rule"]
    s["false_negatives"] = [{"id": r["id"], "category": r["category"], "prior": r["prior_agent_action"],
                             "text": r["text"]} for r in res if not r["captured"] and r["label"] == "rule"]
    # scope: every captured rule is stored repo-wide (anchor ''); count dir/file-scoped rules that lose their scope
    s["scope_lost"] = sum(1 for r in res if r["captured"] and r["label"] == "rule" and r["scope"] in ("dir", "file"))
    # real stream: per real user TURN (repeated turns counted), how many captures and how many were junk
    real = [r for r in res if r["source"] == "real"]
    turns = sum(r.get("real_turns", 1) for r in real)
    s["real_stream"] = {"turns": turns, "captured": sum(r.get("real_turns", 1) for r in real if r["captured"]),
                        "junk": sum(r.get("real_turns", 1) for r in real if r["captured"] and r["label"] != "rule"),
                        "rules_labelled": sum(r.get("real_turns", 1) for r in real if r["label"] == "rule")}
    return s


def fmt(x):
    return "  -  " if x != x else f"{x:.2f}"


def report(s: dict, title: str) -> str:
    L = [f"## {title}", "", "| slice | n | TP | FP | FN | precision | recall | F1 |", "|---|---|---|---|---|---|---|---|"]

    def row(name, m):
        L.append(f"| {name} | {m['n']} | {m['tp']} | {m['fp']} | {m['fn']} | {fmt(m['precision'])} | "
                 f"{fmt(m['recall'])} | {fmt(m['f1'])} |")
    row("**overall**", s["overall"])
    row("overall, borderline excluded", s["no_borderline"])
    for k in ("by_source", "by_prior", "by_category"):
        for g, m in s[k].items():
            row(f"{k[3:]}={g}", m)
    L += ["", f"real stream: {s['real_stream']}", f"dir/file-scoped rules stored repo-wide: {s['scope_lost']}", "",
          f"false positives ({len(s['false_positives'])}):"]
    L += [f"- [{f['id']} {f['category']}, after {f['prior']}] {f['text'][:110]!r}" for f in s["false_positives"]]
    L += ["", f"false negatives ({len(s['false_negatives'])}):"]
    L += [f"- [{f['id']} {f['category']}, after {f['prior']}] {f['text'][:110]!r}" for f in s["false_negatives"]]
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(HERE / "corpus.jsonl"))
    ap.add_argument("--proposal", action="store_true")
    ap.add_argument("--json")
    ap.add_argument("--compare", action="store_true", help="list items whose capture differs current vs proposal")
    a = ap.parse_args()
    if a.compare:
        cur, new = capture(load(a.corpus)), capture(load(a.corpus), proposal=True)
        for c, n in zip(cur, new):
            if c["captured"] != n["captured"]:
                good = n["captured"] == (n["label"] == "rule")
                print(f"{'FIXED' if good else 'BROKE'} {'+' if n['captured'] else '-'} [{n['id']} {n['category']}, "
                      f"after {n['prior_agent_action']}] {n['text'][:100]!r}")
        return
    res = capture(load(a.corpus), proposal=a.proposal)
    s = summarize(res)
    print(report(s, f"{Path(a.corpus).name}: {'PROPOSED' if a.proposal else 'CURRENT'} triggers"))
    if a.json:
        Path(a.json).write_text(json.dumps({"summary": s, "items": res}, indent=1, default=str))


if __name__ == "__main__":
    main()
