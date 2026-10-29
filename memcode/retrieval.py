"""Per-prompt relevance retrieval (opt-in, behind a flag).

The pinned block is built at session start, before the task is known. With retrieval on, every user
prompt also gets the few stored memories most relevant to THAT prompt, as additional context on the
UserPromptSubmit hook. Enable with `python3 -m memcode config retrieval on` or MEMCODE_RETRIEVAL=1.

Relevance (stdlib, deterministic), summed per memory:
  * anchor named in the prompt: the anchor path, its file name, its stem, or its symbol    (+PATH_W)
  * scope: the memory text names a path or directory ("under billing/", "util/dates.py") and the
    prompt mentions a path inside it ("billing/refunds.py")                                (+SCOPE_W)
  * anchor file edited by the agent earlier in this session                               (+ACTIVE_W)
  * similarity: cosine of the prompt's and the memory's local embeddings (embed.py), counted from VEC_MIN
    (0..VEC_W); plus CONTEXT_W times the cosine with the recent conversation (the session's last CONTEXT_PROMPTS
    prompts and CONTEXT_TOOLS tool calls: commands, files, edits), so a decision or a fact about what the work is on
    comes back even when this prompt does not name it
Candidates: every live memory except facts not worth showing (facts.shown) and expired ones. Only memories scoring
>= MIN_SCORE are shown, at most TOP_K, under TOKEN_CAP, never one already shown in this session (pinned or
retrieved; a memory that was only in the start block is shown once more when it scores RESHOW_MIN), never a stale
one. Ranking: the relevance top TOP_K, plus up to HOP_K neighbours of those in the memory
graph (graph.py), plus up to PROMOTE_K extra slots for relevant memories outside the top with strong cost evidence
(restated by the user or a recurring failure, decayed weight >= PROMOTE_MIN), best salience first.
Framing matches the pinned block: user rules as rules, everything else inside the untrusted wrapper.

Scope hierarchy (scope.py, on unless MEMCODE_HIER=0): only memories whose scope is the repo, on or inside the request's
working set (prompt paths + files edited this session), or named by the prompt are candidates; an on-chain scope earns
+SCOPE_W; TOP_K is allocated one slot per scope level nearest first, the rest by score.
"""
from __future__ import annotations

import json
import os
import re
import time

from . import pinned, scope, store

TOP_K = 5
PROMOTE_K = 2             # extra slots for costly memories outside the relevance top-k
PROMOTE_MIN = 1.0         # decayed restatements + recurrences needed to qualify for promotion
TOKEN_CAP = 600
MIN_SCORE = 0.8
HOP_K = 2                 # neighbours of the top memories in the memory graph
HOP_MIN = 0.3             # link weight a neighbour needs
VEC_MIN = 0.15            # cosine below this is noise
CONTEXT_W = 0.5           # the recent conversation counts half as much as the prompt itself
CONTEXT_PROMPTS, CONTEXT_TOOLS = 3, 12   # how much of the recent conversation: earlier prompts, tool calls
RESHOW_MIN = 2.4          # a memory already in the start block is shown again next to the work only this relevant
ACTION_MIN, ACTION_K = 1.5, 2   # recall after a command or an edit: stricter, and at most this many
ACTION_COS = 0.3          # ... and about the same thing: a path the command names is not enough on its own
PATH_W, SCOPE_W, ACTIVE_W, VEC_W = 3.0, 2.0, 1.0, 3.0
STOP = set("""a an and are as at be but by can do does for from has have how i if in into is it its just
let me my no not of on or our please so that the their them then there these this those to up us use
using was we what when where which who why will with you your yes ok okay now also add make get set
new file files code function functions test tests fix change update""".split())
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


def enabled(root) -> bool:
    from . import config
    return config.switch(root, "MEMCODE_RETRIEVAL", "retrieval", True)


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
    # substring test first: the boundary regex (compiled per candidate) only runs when the text is present at all
    return any(c in prompt_l and re.search(r"(?<![\w/.])" + re.escape(c) + r"(?![\w])", prompt_l)
               for c in cands if c)


_PATHTOK = re.compile(r"(?<![\w./-])((?:[A-Za-z0-9_.-]+/)+(?:[A-Za-z0-9_.-]+)?)")


def path_tokens(text: str) -> set[str]:
    """Path-like tokens: 'billing/', 'util/dates.py', 'src/api/' (no URLs, no bare words)."""
    out = set()
    for m in _PATHTOK.findall(text or ""):
        if "://" in m or m.startswith(("http", "www.")):
            continue
        out.add(m.strip(".").lower())
    return {p for p in out if p and p != "/"}


def _in_scope(prompt_paths: set[str], mem_paths: set[str]) -> bool:
    for mp in mem_paths:
        for pp in prompt_paths:
            if pp == mp or (mp.endswith("/") and pp.startswith(mp)) or pp.startswith(mp.rstrip("/") + "/"):
                return True
    return False


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


def context_text(con, session: str, skip: str = "") -> str:
    """The recent conversation of a session, as text to compare memories with: its last CONTEXT_PROMPTS prompts
    (not `skip`, the one being answered) and CONTEXT_TOOLS tool calls (the command, the file, the start of an edit)."""
    prompts, tools = [], []
    for kind, payload in con.execute("SELECT kind, payload FROM events WHERE session=? AND kind IN ('prompt', "
                                     "'tool_use') ORDER BY id DESC LIMIT 80", (session,)):
        try:
            e = json.loads(payload)
        except ValueError:
            continue
        if kind == "prompt" and len(prompts) < CONTEXT_PROMPTS:
            t = str(e.get("prompt") or "")
            if t and t != skip:
                prompts.append(t[:600])
        elif kind == "tool_use" and len(tools) < CONTEXT_TOOLS:
            tools.append(action_text(e))
    return "\n".join(prompts + [t for t in tools if t])


def action_text(ev: dict) -> str:
    """What a tool call is about: its command, or its file and the start of the new text."""
    inp = ev.get("input") if isinstance(ev.get("input"), dict) else {}
    if ev.get("command"):
        return str(ev["command"])[:400]
    path = ev.get("file_path") or inp.get("file_path") or inp.get("notebook_path") or ""
    body = inp.get("new_string") or inp.get("content") or ""
    return f"{path} {str(body)[:300]}".strip()


def _candidates(con) -> list[dict]:
    """Live memories that may be recalled: not expired; facts only those worth showing."""
    from . import facts
    try:
        fact_ids = {fr["id"] for fr, _, _ in facts.shown(con, pinned.MAX_FACTS)}
    except Exception:                     # noqa: BLE001
        fact_ids = set()
    return [dict(r) for r in con.execute("SELECT * FROM memories m WHERE m.stale=0 AND "
                                         "(m.expires_at IS NULL OR m.expires_at>?)", (time.time(),))
            if r["mkey"] is None or r["id"] in fact_ids]


def score(con, root: str, session: str, prompt: str, context: str = "", min_cos: float = 0.0) -> list[tuple[float, dict]]:
    """[(score, memory row as dict)] for candidate memories, best first (only score >= MIN_SCORE). With MEMCODE_HIER
    the first TOP_K are the per-level allocation (scope.allocate), nearest scope first; the rest follow by score."""
    hier = scope.hier_enabled()
    prompt_l = (prompt or "").lower()
    src: dict[int, set] = {}
    for mid, source in con.execute("SELECT memory_id, source FROM injections WHERE session=?", (session,)):
        src.setdefault(mid, set()).add(source)
    # MEMCODE_HIER (hier1 Run 14): a note on a file the prompt names is shown again next to the task even if the start
    # block already listed it; a start-block mention among many was followed less often than one beside the request
    again = lambda r: (hier and src.get(r["id"]) == {"pinned"} and bool(r["anchor_path"])
                       and _mentions(prompt_l, r["anchor_path"], r["anchor_symbol"]))
    # never twice in a session, except a memory that was only in the start block (long ago, among many): it may come
    # back once next to the work when it is clearly relevant (RESHOW_MIN), or when the prompt names its file (again)
    rows = [r for r in _candidates(con) if r["id"] not in src or src[r["id"]] == {"pinned"}]
    if not rows:
        return []
    from . import embed
    body = lambda r: pinned._rule_text(r["text"]) if r["from_user"] else r["text"]   # drop the context tail
    embed.refresh(con)
    vectors = embed.load(con)
    idfs = embed.idf(vectors)
    q = embed.weigh(embed.vector(prompt), idfs)
    cos = {r["id"]: embed.cosine(q, embed.weigh(vectors[r["id"]], idfs)) if r["id"] in vectors else 0.0 for r in rows}
    qc = embed.weigh(embed.vector(context), idfs) if context else {}
    ccos = {r["id"]: embed.cosine(qc, embed.weigh(vectors[r["id"]], idfs)) if qc and r["id"] in vectors else 0.0
            for r in rows}
    active = _active_files(con, session)
    rootp = os.path.realpath(root).replace(os.sep, "/") + "/"
    prompt_paths = path_tokens(prompt)
    if hier:
        ws = scope.working_set(con, session, prompt, root, active=active)
        chain = scope.chains(ws)
    out = []
    for r in rows:
        a = r["anchor_path"] or ""
        named = _mentions(prompt_l, a, r.get("anchor_symbol"))
        if hier:
            sp = r.get("scope_path") or ""
            spl = sp.lower()
            on_chain = bool(spl) and spl in chain
            sc_named = bool(sp) and sp != a and scope.scope_named(prompt_l, sp, r.get("scope_kind"))
            if spl and not (on_chain or named or sc_named or scope.inside(spl, ws)):
                continue                                  # off-chain: outside this request's scope
        c, cc = cos[r["id"]], ccos[r["id"]]
        if c < min_cos:
            continue
        s = (VEC_W * c if c >= VEC_MIN else 0.0) + (CONTEXT_W * VEC_W * cc if cc >= VEC_MIN else 0.0)
        active_hit = bool(a) and any(f == a or f.endswith("/" + a) or f == rootp + a for f in active)
        if named or (hier and sc_named):
            s += PATH_W
        elif prompt_paths and _in_scope(prompt_paths, path_tokens(body(r))):
            s += SCOPE_W
        elif hier and on_chain and not active_hit:
            s += SCOPE_W
        if active_hit:
            s += ACTIVE_W
        if r["id"] in src and not again(r) and s < RESHOW_MIN:
            continue                                      # in the start block already, and not relevant enough
        if s >= MIN_SCORE:
            out.append((s, r))
    out.sort(key=lambda x: (-x[0], -x[1]["updated_at"], -x[1]["id"]))
    if hier:
        out = scope.allocate(out, TOP_K)                  # scored[:TOP_K] is the per-level allocation
    return out


def select(con, scored: list[tuple[float, dict]], session: str = "") -> list[tuple[float, dict]]:
    """The memories to show, in order: the top TOP_K by relevance, their strongest neighbours in the memory graph
    (up to HOP_K), plus up to PROMOTE_K costly ones (repeated or recurring mistakes) from further down."""
    top = scored[:TOP_K]
    if con is None:
        return top
    top = top + _hops(con, top, session)
    taken = {r["id"] for _, r in top}
    rest = [(s, r) for s, r in scored[TOP_K:] if r["id"] not in taken]
    if not rest:
        return top
    from . import salience
    idx = salience.Index(con)                       # one pass over the store, not one per candidate
    cands = []
    for s, r in rest:
        ev = idx.evidence(r)
        if ev["repeats"] + ev["recurrences"] >= PROMOTE_MIN:
            cands.append((salience.score(con, r, index=idx), s, r))
    cands.sort(key=lambda x: (-x[0], -x[1], -x[2]["updated_at"], -x[2]["id"]))
    return top + [(s, r) for _, s, r in cands[:PROMOTE_K]]


def _hops(con, top: list[tuple[float, dict]], session: str) -> list[tuple[float, dict]]:
    """Neighbours of the top memories (graph.neighbours), not shown this session, not the user's words (those come
    by scope), as candidates: [(parent score x link weight, row)]."""
    if not top:
        return []
    from . import graph
    best = {r["id"]: s for s, r in top}
    shown = {m for (m,) in con.execute("SELECT memory_id FROM injections WHERE session=?", (session,))}
    allowed = {r["id"] for r in _candidates(con)}
    out = []
    for o, w, _ in graph.neighbours(con, list(best), limit=HOP_K * 4):
        if w < HOP_MIN or o in shown or o not in allowed:
            continue
        r = con.execute("SELECT * FROM memories WHERE id=?", (o,)).fetchone()
        if r is None or r["from_user"]:
            continue
        out.append((max(best.values()) * w, dict(r)))
        if len(out) >= HOP_K:
            break
    return out


def render(scored: list[tuple[float, dict]], con=None, session: str = "") -> tuple[str, list[int]]:
    """con enables the graph neighbours and the promotions of costly memories (see select)."""
    rules, notes, ids, used = [], [], [], 0
    for s, r in select(con, scored, session):
        if r["from_user"]:
            line = pinned._from_you_line(r)
        else:
            line = pinned.memory_line(r)
        if (used + len(line)) / pinned.TOKEN_DIVISOR > TOKEN_CAP:
            break
        used += len(line) + 1
        (rules if r["from_user"] else notes).append(line)
        ids.append(r["id"])
    parts = []
    if rules:
        parts.append("## From you, relevant to this request (stated by the user earlier; follow them)\n" + "\n".join(rules))
    if notes:
        parts.append("\n".join([pinned.NOTES_HEADER, pinned.NOTES_OPEN, "## Memory relevant to this request",
                                *notes, pinned.NOTES_CLOSE]))
    return "\n\n".join(parts), ids


def for_prompt(con, root: str, session: str, prompt: str) -> str:
    """Context to add for this prompt ('' when nothing is relevant), judged against the prompt and the recent
    conversation. Records what was shown."""
    text, ids = render(score(con, root, session, prompt, context_text(con, session, skip=prompt)), con, session)
    if ids:
        now = time.time()
        con.executemany("INSERT INTO injections(session,memory_id,ts,source) VALUES(?,?,?,'prompt')",
                        [(session, i, now) for i in ids])
        store.bump(con, session, "prompt_injected", len(ids), commit=False)
        con.commit()
        from . import activity
        activity.note(con, "recalled", f"{len(ids)} memor{'y' if len(ids) == 1 else 'ies'} for this prompt"
                      f"{activity.first(con, ids)}", len(ids))
    return text


def for_action(con, root: str, session: str, ev: dict) -> str:
    """Context to add after a command or an edit: the few memories closely related to that action (at most ACTION_K,
    scoring ACTION_MIN), e.g. the pitfall or the fact about how tests run here after a test command. Records them."""
    query = action_text(ev)
    if not query:
        return ""
    scored = [x for x in score(con, root, session, query, min_cos=ACTION_COS)   # a measured command would echo it
              if x[0] >= ACTION_MIN and x[1]["trigger"] != "command"][:ACTION_K]
    text, ids = render(scored, None)
    if not ids:
        return ""
    text = text.replace("relevant to this request", "relevant to what you just did")
    now = time.time()
    con.executemany("INSERT INTO injections(session,memory_id,ts,source) VALUES(?,?,?,'action')",
                    [(session, i, now) for i in ids])
    con.commit()
    from . import activity
    what = (f"`{query[:40]}`" if ev.get("command") else query.split(" ", 1)[0])
    activity.note(con, "recalled", f"{len(ids)} memor{'y' if len(ids) == 1 else 'ies'} for {what}"
                  f"{activity.first(con, ids)}", len(ids))
    return text


def flagged(con, session: str) -> str:
    """Memories the memory agent flagged for what the session is doing now (agent.curate.queue_recall), with its
    reason, delivered once at the next prompt or tool call; a memory already shown this session (beyond the start
    block) is skipped. Records them."""
    rows = con.execute("SELECT p.memory_id, p.why, m.* FROM pending_recalls p JOIN memories m ON m.id=p.memory_id "
                       "WHERE p.session=? AND m.stale=0 ORDER BY p.ts", (session,)).fetchall()
    if not rows:
        return ""
    con.execute("DELETE FROM pending_recalls WHERE session=?", (session,))
    seen = {m for (m,) in con.execute("SELECT memory_id FROM injections WHERE session=? AND source!='pinned'",
                                      (session,))}
    rules, notes, ids = [], [], []
    for r in rows:
        if r["id"] in seen:
            continue
        why = " ".join(str(r["why"] or "").split())[:240]
        line = pinned._from_you_line(r) if r["from_user"] else pinned.memory_line(r)
        line += f" (why now: {pinned._one_line(why, 240)})" if why else ""
        (rules if r["from_user"] else notes).append(line)
        ids.append(r["id"])
    con.commit()
    if not ids:
        return ""
    parts = []
    if rules:
        parts.append("## From you, flagged by memcode's memory agent for what you are doing now (follow them)\n"
                     + "\n".join(rules))
    if notes:
        parts.append("\n".join([pinned.NOTES_HEADER, pinned.NOTES_OPEN,
                                "## Memory flagged by memcode's memory agent for what you are doing now", *notes,
                                pinned.NOTES_CLOSE]))
    now = time.time()
    con.executemany("INSERT INTO injections(session,memory_id,ts,source) VALUES(?,?,?,'flagged')",
                    [(session, i, now) for i in ids])
    con.commit()
    from . import activity
    activity.note(con, "recalled", f"{len(ids)} flagged by the memory agent{activity.first(con, ids)}", len(ids))
    return "\n\n".join(parts)
