"""Per-prompt relevance retrieval (opt-in, behind a flag).

The pinned block is built at session start, before the task is known. With retrieval on, every user
prompt also gets the few stored memories most relevant to THAT prompt, as additional context on the
UserPromptSubmit hook. Enable with `python3 -m memcode config retrieval on` or MEMCODE_RETRIEVAL=1.

Relevance (stdlib, deterministic), summed per memory:
  * anchor named in the prompt: the anchor path, its file name, its stem, or its symbol    (+PATH_W)
  * anchor file edited by the agent earlier in this session                               (+ACTIVE_W)
  * term overlap: IDF-weighted overlap of prompt and memory terms (identifiers are split, so
    parse_items / ParseItems / "parse items" match), normalised by the prompt's term weight (0..TERM_W);
    counts only with >= MIN_SHARED_TERMS shared terms
Only memories scoring >= MIN_SCORE are shown, at most TOP_K, under TOKEN_CAP, never one already shown
in this session (pinned or retrieved), never a stale one. Ranking is relevance only; the salience
multiplier from the plan exists behind MEMCODE_RANK=salience for a later A/B and is off by default.
Framing matches the pinned block: user rules as rules, everything else inside the untrusted wrapper.
"""
from __future__ import annotations

import json
import math
import os
import re
import time

from . import pinned, store

TOP_K = 5
TOKEN_CAP = 600
MIN_SCORE = 0.8
MIN_SHARED_TERMS = 2      # one shared word is not enough to call a memory relevant
PATH_W, ACTIVE_W, TERM_W = 3.0, 1.0, 2.0
STOP = set("""a an and are as at be but by can do does for from has have how i if in into is it its just
let me my no not of on or our please so that the their them then there these this those to up us use
using was we what when where which who why will with you your yes ok okay now also add make get set
new file files code function functions test tests fix change update""".split())
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


def enabled(root) -> bool:
    from .model_capture import read_config
    env = os.environ.get("MEMCODE_RETRIEVAL", "").lower()
    if env in ("0", "false", "off"):
        return False
    return env in ("1", "true", "on") or bool(read_config(root).get("retrieval"))


def terms(text: str) -> set[str]:
    out = set()
    for w in _WORD.findall(text or ""):
        for part in [w] + w.split("_") + _CAMEL.findall(w):
            p = part.lower()
            if len(p) >= 3 and p not in STOP:
                plural = p.endswith("s") and len(p) > 4 and not p.endswith(("ss", "us", "is", "ys"))
                out.add(p[:-1] if plural else p)                           # crude plural folding
    return out


def _mentions(prompt_l: str, anchor: str, symbol: str | None) -> bool:
    if not anchor:
        return False
    base = anchor.rsplit("/", 1)[-1].lower()
    stem = base.rsplit(".", 1)[0]
    cands = {anchor.lower(), base} | ({stem} if len(stem) >= 4 else set())
    if symbol:
        cands |= {symbol.lower(), symbol.rsplit(".", 1)[-1].lower()}
    return any(re.search(r"(?<![\w/.])" + re.escape(c) + r"(?![\w])", prompt_l) for c in cands if c)


def _active_files(con, session: str) -> set[str]:
    out = set()
    for (p,) in con.execute("SELECT payload FROM events WHERE session=? AND kind='tool_use'", (session,)):
        try:
            e = json.loads(p)
        except ValueError:
            continue
        if str(e.get("tool", "")).lower() in ("edit", "write", "multiedit", "notebookedit"):
            inp = e.get("input") if isinstance(e.get("input"), dict) else {}
            fp = (inp.get("file_path") or inp.get("notebook_path") or "").replace(os.sep, "/")
            if fp:
                out.add(fp)
    return out


def score(con, root: str, session: str, prompt: str) -> list[tuple[float, dict]]:
    """[(score, memory row as dict)] for candidate memories, best first (only score >= MIN_SCORE)."""
    shown = {r[0] for r in con.execute("SELECT memory_id FROM injections WHERE session=?", (session,))}
    rows = [dict(r) for r in con.execute("SELECT * FROM memories WHERE stale=0") if r["id"] not in shown]
    if not rows:
        return []
    pt = terms(prompt)
    body = lambda r: pinned._rule_text(r["text"]) if r["trigger"] == "correction" else r["text"]   # drop boilerplate
    docs = {r["id"]: terms(body(r) + " " + (r["anchor_path"] or "") + " " + (r["anchor_symbol"] or "")) for r in rows}
    n = len(rows) + 1
    df: dict[str, int] = {}
    for d in docs.values():
        for t in d:
            df[t] = df.get(t, 0) + 1
    idf = lambda t: math.log(1 + n / (1 + df.get(t, 0)))
    p_weight = sum(idf(t) for t in pt) or 1.0
    active = _active_files(con, session)
    rootp = os.path.realpath(root).replace(os.sep, "/") + "/"
    prompt_l = (prompt or "").lower()
    salience_rank = os.environ.get("MEMCODE_RANK") == "salience"
    out = []
    for r in rows:
        shared = pt & docs[r["id"]]
        s = TERM_W * sum(idf(t) for t in shared) / p_weight if len(shared) >= MIN_SHARED_TERMS else 0.0
        a = r["anchor_path"] or ""
        if _mentions(prompt_l, a, r.get("anchor_symbol")):
            s += PATH_W
        if a and any(f == a or f.endswith("/" + a) or f == rootp + a for f in active):
            s += ACTIVE_W
        if salience_rank and s > 0:                       # Phase 2 A/B only; off by default
            from . import salience
            sv = salience.compute(con, con.execute("SELECT * FROM memories WHERE id=?", (r["id"],)).fetchone())
            s *= 1 + sum(sv.values()) / 4
        if s >= MIN_SCORE:
            out.append((s, r))
    out.sort(key=lambda x: (-x[0], -x[1]["updated_at"], -x[1]["id"]))
    return out


def render(scored: list[tuple[float, dict]]) -> tuple[str, list[int]]:
    rules, notes, ids, used = [], [], [], 0
    for s, r in scored[:TOP_K]:
        if r["trigger"] == "correction":
            line = f"- {pinned._one_line(pinned._rule_text(r['text']), 240)}"
        else:
            line = f"- ({r['trigger']}) {pinned._one_line(r['text'])}" + (f" [{r['anchor_path']}]" if r["anchor_path"] else "")
        if (used + len(line)) / pinned.TOKEN_DIVISOR > TOKEN_CAP:
            break
        used += len(line) + 1
        (rules if r["trigger"] == "correction" else notes).append(line)
        ids.append(r["id"])
    parts = []
    if rules:
        parts.append("## Project rules relevant to this request (stated by the user earlier; follow them)\n" + "\n".join(rules))
    if notes:
        parts.append("\n".join([pinned.NOTES_HEADER, pinned.NOTES_OPEN, "## Notes relevant to this request",
                                *notes, pinned.NOTES_CLOSE]))
    return "\n\n".join(parts), ids


def for_prompt(con, root: str, session: str, prompt: str) -> str:
    """Context to add for this prompt ('' when nothing is relevant). Records what was shown."""
    text, ids = render(score(con, root, session, prompt))
    if ids:
        now = time.time()
        con.executemany("INSERT INTO injections(session,memory_id,ts,source) VALUES(?,?,?,'prompt')",
                        [(session, i, now) for i in ids])
        store.bump(con, session, "prompt_injected", len(ids), commit=False)
        con.commit()
    return text
