"""`memcode eval-agent`: how well the memory agent does on fixed cases, so its prompt, model and effort are tuned on
evidence instead of guesses.

Each case in eval_cases.json is a condensed log (with files and starting memories when it needs them) and what memcode
should end up with: memories it keeps (`expect`), mistakes it must not make (`avoid`), a stale memory updated and
revived (`memory` + `fresh`), a memory flagged for the coding agent's next step (`recall`). A case runs the real
pipeline in a scratch repository: the briefing, one model call (one-off, not the running conversation), memcode's
checks and curation. The score is the share of checks passed; cost and time are the model's.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from . import curate, db, model

CASES = Path(__file__).with_name("eval_cases.json")


def load_cases() -> list[dict]:
    return json.loads(CASES.read_text())["cases"]


def _matches(text: str, groups: list[str]) -> bool:
    """Every group present in text; a group's alternatives are '|'-separated; '' matches anything."""
    t = (text or "").lower()
    return all(not g or any(alt.strip().lower() in t for alt in g.split("|")) for g in groups)


def _setup(case: dict, root: str):
    from .. import store, tree
    subprocess.run(["git", "init", "-q", root], check=True)
    files = dict(case.get("files") or {})
    for m in case.get("memories") or []:                 # a stale memory was written against the file as it was
        if m.get("stale") and m.get("anchor"):
            files.setdefault(m["anchor"], "")
    for rel, text in files.items():
        p = Path(root, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    con = store.connect(root)
    db.ensure(con)
    ids = {}
    for i, m in enumerate(case.get("memories") or [], 1):
        anchor, h = m.get("anchor", ""), None
        if m.get("stale") and anchor:
            h = store.sha1(m.get("original", "").encode("utf-8"))      # hashed as it was: the file now differs
        ids[i] = store.add_memory(con, "agent", m["text"], anchor, h, {}, topic=m.get("topic", ""),
                                  from_user=bool(m.get("from_user")))
    tree.mark_stale(con, root)
    con.commit()
    return con, ids


def run_case(case: dict, extract_fn=None) -> dict:
    """One case through the real pipeline. -> {name, checks: [(label, ok)], cost, seconds, kept, error}."""
    extract_fn = extract_fn or model.extract
    with tempfile.TemporaryDirectory() as root:
        con, ids = _setup(case, root)
        try:
            log = "\n".join(case["log"])
            t0 = time.time()
            res = extract_fn(log, model.briefing(con, root, "eval"))
            seconds = time.time() - t0
            if not res or "error" in res:
                return {"name": case["name"], "checks": [], "cost": 0.0, "seconds": seconds, "kept": [],
                        "error": (res or {}).get("error") or "no answer"}
            start = set(ids.values())
            curate.store_items(con, root, "eval", res["items"], log, res.get("model", ""))
            new = [dict(r) for r in con.execute("SELECT * FROM memories WHERE trigger='agent' AND mkey IS NULL")
                   if r["id"] not in start]
            flagged = {r[0] for r in con.execute("SELECT memory_id FROM pending_recalls")}
            checks = []
            for e in case.get("expect") or []:
                if "recall" in e:
                    ok = ids.get(e["recall"]) in flagged
                elif "memory" in e:
                    r = con.execute("SELECT * FROM memories WHERE id=?", (ids.get(e["memory"]),)).fetchone()
                    ok = bool(r) and _matches(r["text"], e.get("all", [])) and (not e.get("fresh") or not r["stale"])
                else:
                    ok = any(_matches(m["text"], e.get("all", []))
                             and ("from_user" not in e or bool(m["from_user"]) == e["from_user"])
                             and ("topic" not in e or m["topic"] == e["topic"]) for m in new)
                checks.append((f"keeps: {e['name']}", ok))
            for a in case.get("avoid") or []:
                bad = any(_matches(m["text"], a.get("all", []))
                          and ("from_user" not in a or bool(m["from_user"]) == a["from_user"]) for m in new)
                checks.append((f"avoids: {a['name']}", not bad))
            refused = [f"{r['op']} \"{r['text'][:90]}\": {r['reason']}" for r in con.execute(
                "SELECT op, text, reason FROM proposals ORDER BY id")]
            return {"name": case["name"], "checks": checks, "cost": float(res.get("cost_usd") or 0.0),
                    "seconds": seconds, "kept": [m["text"] for m in new], "refused": refused,
                    "proposed": [f"{i.get('op')} {i.get('topic')}: {str(i.get('text'))[:90]}" for i in res["items"]],
                    "error": None}
        finally:
            con.close()


def run(effort: str | None = None, model_name: str | None = None, repeat: int = 1, only: str | None = None,
        extract_fn=None) -> dict:
    """Every case `repeat` times with the given effort and model. -> a report (see main for the layout)."""
    saved = {k: os.environ.get(k) for k in ("MEMCODE_AGENT_EFFORT", "MEMCODE_CAPTURE_MODEL")}
    if effort:
        os.environ["MEMCODE_AGENT_EFFORT"] = effort
    if model_name:
        os.environ["MEMCODE_CAPTURE_MODEL"] = model_name
    try:
        results = [run_case(c, extract_fn) for _ in range(max(1, repeat)) for c in load_cases()
                   if not only or only.lower() in c["name"].lower()]
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    passed = sum(ok for r in results for _, ok in r["checks"])
    total = sum(len(r["checks"]) for r in results)
    return {"effort": effort or model.DEFAULT_EFFORT, "model": model_name or os.environ.get("MEMCODE_CAPTURE_MODEL")
            or model.DEFAULT_MODEL, "repeat": repeat, "results": results, "passed": passed, "total": total,
            "score": passed / total if total else 0.0, "cost": sum(r["cost"] for r in results),
            "seconds": sum(r["seconds"] for r in results), "errors": sum(1 for r in results if r["error"])}


def render(report: dict) -> str:
    lines = [f"memory agent eval: {report['model']}, effort {report['effort']}, {report['repeat']} run(s) per case"]
    for r in report["results"]:
        if r["error"]:
            lines.append(f"  ERROR {r['name']}: {r['error'][:160]}")
            continue
        ok = sum(o for _, o in r["checks"])
        lines.append(f"  {ok}/{len(r['checks'])}  {r['name']}  (${r['cost']:.4f}, {r['seconds']:.0f}s)")
        lines += [f"        missed: {label}" for label, o in r["checks"] if not o]
        if ok < len(r["checks"]):            # why: what the agent proposed, and what memcode refused
            lines += [f"          proposed: {p}" for p in r.get("proposed", [])]
            lines += [f"          refused:  {p}" for p in r.get("refused", [])]
    lines.append(f"score {report['passed']}/{report['total']} = {report['score']:.0%}; cost ${report['cost']:.4f}; "
                 f"{report['seconds']:.0f}s; errors {report['errors']}")
    return "\n".join(lines)
