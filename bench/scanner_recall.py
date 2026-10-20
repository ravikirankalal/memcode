"""Scanner recall on a real session log: how many of the memories a careful reader would keep does the memory agent
(memcode/transcript_capture.py) propose, and what else does it propose?

Runs every MAX_CHARS piece of one transcript through `extract` with an EMPTY memory briefing (so "already known" never
hides a candidate) and matches the proposals against GOLD: things a future session in this repo should know, each with
a loose regex on the proposed text. Matching is approximate; every proposal is also written out for review.

  python3 bench/scanner_recall.py TRANSCRIPT.jsonl --out results.json [--pieces 0-29]

Cost: one model call per piece (Haiku: about $0.004 each; a 10k-line session is 30 pieces).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from memcode import store, transcript_capture as tc  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # the session's repo (memcode itself)

# what this repo's development session (memcode, 2026-10-18) taught that a later session should know
GOLD = {
    "rule: no subagents": r"subagent",
    "rule: no PR unless asked": r"\bPRs?\b|pull request",
    "release: bump versions in the manifests": r"marketplace\.json|mcp_server|version (?:bump|in)|bump.*version",
    "mod: test in a real session with --plugin-dir": r"plugin-dir",
    "mod: a dev-mods copy overrides the installed mod": r"dev-mods",
    "nested claude: unset CLAUDE_CODE_SESSION_ID": r"CLAUDE_CODE_SESSION_ID|session.id",
    "tmux: trust prompt needs Down then Enter": r"trust",
    "mod tests: claude plugin test": r"claude plugin test",
    "desktop app: CLAUDE_PROJECT_DIR is the main checkout": r"CLAUDE_PROJECT_DIR",
    "lint: ruff has ~125 pre-existing findings": r"\bruff\b",
    "mod: $ only to top-level functions / h shadows JSX": r"top-level|JSX|\bshadow",
    "mod: colors are theme keys": r"\btheme\b",
    "bench: usage limit (429) must be waited out": r"usage limit|\b429\b|rate.?limit",
    "bench: arms pin MEMCODE_HIER / TRANSCRIPT_CAPTURE": r"MEMCODE_HIER|MEMCODE_TRANSCRIPT_CAPTURE",
    "bench: frozen sets are never edited": r"\bfrozen\b",
    "headless claude -p needs --setting-sources '' etc.": r"setting-sources|--bare|headless",
    "env: sqlite3 can be installed": r"sqlite",
    "phone: no plugin surfaces, the bar is not drawn": r"\bphone\b|surfaces?\b",
    "mod: register the command last, with .catch": r"command\.register|register.{0,30}last",
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pieces", default="", help="a-b range of piece indexes (default: all)")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--sequential", action="store_true",
                    help="real use: pieces in order, each briefed with the memory the earlier ones stored (temp store)")
    a = ap.parse_args(argv)
    lines = open(a.transcript, errors="replace").read().splitlines()
    pieces = [p for _, p in tc.chunks(lines)]
    if a.pieces:
        lo, hi = (int(x) for x in a.pieces.split("-"))
        pieces = pieces[lo:hi + 1]
    d = tempfile.mkdtemp()
    con = store.connect(d)
    brief = tc.briefing(con, d, "eval")
    if a.sequential:
        return sequential(con, pieces, a.out)
    con.close()

    def one(i):
        r = tc.extract(pieces[i], brief) or {"error": "none"}
        items = r.get("items", [])
        for it in items:
            it["verified"] = tc.verified(it, pieces[i], REPO)
        return {"piece": i, "error": r.get("error"), "cost": r.get("cost_usd", 0.0),
                "candidates": r.get("candidates", len(items)), "items": items}

    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(one, range(len(pieces))))
    def rating(it):
        try:
            return int(it.get("importance", tc.MIN_IMPORTANCE))
        except (TypeError, ValueError):
            return tc.MIN_IMPORTANCE
    kept = []                                   # what store_items would keep: verified, rated high enough, top few
    for r in res:
        ok = sorted((it for it in r["items"] if it.get("verified") and it.get("op", "add") == "add"
                     and rating(it) >= (tc.MIN_RULE_IMPORTANCE if it.get("kind") == "rule" else tc.MIN_IMPORTANCE)),
                    key=lambda it: -rating(it))
        kept += ok[:tc.MAX_ITEMS]
    hits = {g: [it["text"] for it in kept if re.search(rx, it["text"], re.I)] for g, rx in GOLD.items()}
    found = [g for g, h in hits.items() if h]
    out = {"pieces": len(pieces), "cost": round(sum(r["cost"] for r in res), 4),
           "errors": sum(1 for r in res if r["error"]), "proposed": sum(len(r["items"]) for r in res),
           "verified": sum(1 for r in res for it in r["items"] if it.get("verified")), "kept": len(kept),
           "kept_items": [{"importance": it.get("importance"), "kind": it.get("verified"), "category": it.get("category"),
                           "text": it["text"]} for it in kept], "gold_found": len(found), "gold_total": len(GOLD),
           "hits": hits, "results": res}
    with open(a.out, "w") as fh:
        json.dump(out, fh, indent=1)
    print(f"pieces {out['pieces']}  cost ${out['cost']}  errors {out['errors']}  proposed {out['proposed']}  "
          f"verified {out['verified']}  kept {out['kept']}  gold {len(found)}/{len(GOLD)}")
    for g in GOLD:
        print(f"  {'+' if hits[g] else '-'} {g}" + (f"  <- {hits[g][0][:90]}" if hits[g] else ""))
    return 0


def sequential(con, pieces, out_path) -> int:
    """Each piece is briefed with the memory as it stands and its operations are applied with store_items (rooted
    at this repo for anchors), as the worker does. Reports what the store holds at the end."""
    cost, log = 0.0, []
    for i, piece in enumerate(pieces):
        r = tc.extract(piece, tc.briefing(con, REPO, "eval")) or {"error": "none"}
        cost += r.get("cost_usd", 0.0)
        ids = tc.store_items(con, REPO, "eval", r.get("items", []), piece, r.get("model", ""))
        log.append({"piece": i, "error": r.get("error"), "proposed": len(r.get("items", [])), "changed": ids})
        print(f"piece {i}: proposed {len(r.get('items', []))}, changed {ids}", flush=True)
    rows = [dict(r) for r in con.execute("SELECT id, trigger, text, anchor_path FROM memories WHERE stale=0 ORDER BY id")]
    ops = [tuple(r) for r in con.execute("SELECT op, COUNT(*) FROM memory_log GROUP BY op")]
    hits = {g: [m["text"] for m in rows if re.search(rx, m["text"], re.I)] for g, rx in GOLD.items()}
    with open(out_path, "w") as fh:
        json.dump({"cost": round(cost, 4), "ops": ops, "memories": rows, "log": log, "hits": hits}, fh, indent=1)
    print(f"cost ${cost:.4f}  ops {ops}  live memories {len(rows)}  gold {sum(1 for h in hits.values() if h)}/{len(GOLD)}")
    for m in rows:
        print(f"  #{m['id']} {m['trigger'][:4]} [{m['anchor_path'] or 'repo'}] {m['text'][:140]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
