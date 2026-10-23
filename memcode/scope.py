"""Scope hierarchy (on by default since 0.8.0; MEMCODE_HIER=0 turns it off): where a memory applies, and which memories a request may see.

Every memory has a scope node (memories.scope_path, scope_kind):
  ''              repo    applies everywhere
  'billing'       dir     applies to everything under billing/
  'billing/x.py'  file    applies to that file ('symbol' when the memory is anchored to a Python symbol in it)
anchor_path still decides staleness; scope_path decides where a memory applies. Rules keep anchor_path='' (never
stale) and may still get a directory scope.

Assignment, `assign` (at capture in triggers._write, and at every session start through `rescope_new`, whatever the
flag says, so turning MEMCODE_HIER on needs no migration):
  * anchor_path set (any trigger): the anchor itself; kind 'symbol' if anchor_symbol, 'dir' if `paths` says so,
    otherwise 'file'.
  * no anchor, from_user or trigger manual (user rules): the path tokens of the rule text (retrieval's path regex; the
    "(context: ...)" tail is dropped) that exist in `paths`
    (exact, else ASCII case-insensitive). A file token stands for its directory, so rules are never file-scoped.
    One directory -> that dir; several -> their deepest common ancestor; none, or a common ancestor of '' -> repo.
  * anything else (retry notes, unanchored notes): repo.

Retrieval with the flag on (retrieval.score):
  working set   prompt path tokens + absolute paths under the root named in the prompt + files edited this session,
                repo-relative and lowercase (`working_set`)
  eligible      scope '' | scope on the scope_chain of a working-set path | scope inside a working-set path |
                the prompt names the memory (anchor per retrieval._mentions, or the scope itself: its path or, for a
                dir, a basename of >= 4 chars, as a standalone word not followed by a deeper /component)
  score         the flat score, plus +PATH_W when the scope (not the anchor) is named, else +SCOPE_W when the scope
                is on a working-set chain and the memory earned neither PATH_W, the flat SCOPE_W nor ACTIVE_W
  allocation    `allocate`: one slot per scope level, nearest first (file/symbol, then dirs deepest -> shallowest,
                then repo), each level's best memory; remaining slots by the existing order (score, recency, id).
                The chosen are ordered nearest first; split promotions then apply to the eligible rest as before.
Session start with the flag on AND retrieval on (`split_rules`): the rules section lists repo-scope rules only; each
dir/file that is the scope of live rules is expanded in the Map and marked "billing/ [3 rules]" (`rule_marks`).
With retrieval off the start block stays flat, so scoped rules are never hidden with no other way in.

`rules_for_path` gives the scoped rules and notes of a path the agent just touched (read or edited), once per
session, for a tool hook to inject.
"""
from __future__ import annotations

import os
import re
import string
import time

from . import store

RULE_TRIGGERS = ("correction", "manual")
TOUCH_TOKEN_CAP = 300
_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
_NAME_TAIL = r"/?(?![\w/-]|\.\w)"      # a standalone name: not followed by a deeper /component or more word


OFF = ("0", "false", "off")


def hier_enabled() -> bool:
    """On by default (since 0.8.0, after hier1 and hier2): MEMCODE_HIER=0, or `memcode config hierarchy off` (applied
    to the environment by apply_config at each entry point), turns it off."""
    return os.environ.get("MEMCODE_HIER", "").lower() not in OFF


def apply_config(root) -> None:
    """Entry points (hooks, CLI, MCP server) call this once they know the repo: the repo's `config hierarchy off`
    becomes MEMCODE_HIER=0 for this process unless the environment already sets MEMCODE_HIER."""
    if "MEMCODE_HIER" in os.environ:
        return
    from . import config
    if config.read(root).get("hierarchy") is False:
        os.environ["MEMCODE_HIER"] = "0"


def split_rules(root) -> bool:
    """Should the start block hold back scoped rules? With the flag on, yes: they arrive when the agent works there,
    by prompt retrieval (if on), first-touch injection on a read, or the first-write refusal (engine.before_write);
    the map marks folders that hold them. (Before first touch existed this also required retrieval.)"""
    return hier_enabled()


def _fold(s: str) -> str:
    return s.translate(_ASCII_LOWER)       # matches SQLite lower()


def norm(p: str) -> str:
    """'./billing/' -> 'billing'; '.' and '/' -> '' (the repo)."""
    p = (p or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    p = re.sub(r"/{2,}", "/", p.strip(".").strip("/"))
    return "" if p in (".", "") else p


def _text_paths(text: str) -> list[str]:
    """Path tokens of a text, case kept (retrieval.path_tokens lowercases)."""
    from .retrieval import _PATHTOK
    out = []
    for m in _PATHTOK.findall(text or ""):
        if "://" in m or m.lower().startswith(("http", "www.")):
            continue
        p = norm(m)
        if p and ".." not in p.split("/"):
            out.append(p)
    return out


class _Paths:
    """`paths` lookup: exact, then ASCII case-insensitive (lowest path wins). preload=True for batch use."""

    def __init__(self, con, preload: bool = False):
        self.con = con
        self.kind = self.lower = None
        if preload:
            self.kind = {r[0]: r[1] for r in con.execute("SELECT path, kind FROM paths WHERE path!=''")}
            self.lower = {}
            for p in sorted(self.kind):
                self.lower.setdefault(_fold(p), p)

    def get(self, p: str):
        if self.kind is not None:
            if p in self.kind:
                return p, self.kind[p]
            q = self.lower.get(_fold(p))
            return (q, self.kind[q]) if q else None
        r = (self.con.execute("SELECT path, kind FROM paths WHERE path=?", (p,)).fetchone()
             or self.con.execute("SELECT path, kind FROM paths WHERE lower(path)=? AND path!='' ORDER BY path LIMIT 1",
                                 (_fold(p),)).fetchone())
        return (r[0], r[1]) if r else None


def _common_ancestor(dirs: list[str]) -> str:
    parts = [d.split("/") if d else [] for d in dirs]
    out = []
    for comps in zip(*parts):
        if any(c != comps[0] for c in comps):
            break
        out.append(comps[0])
    return "/".join(out)


def assign(con, trigger: str, text: str, anchor_path: str, anchor_symbol: str | None = None,
           _paths: _Paths | None = None, from_user: bool | None = None) -> tuple[str, str]:
    """(scope_path, scope_kind) for a memory; see the module docstring."""
    paths = _paths or _Paths(con)
    a = anchor_path or ""
    if a:
        if anchor_symbol:
            return a, "symbol"
        hit = paths.get(norm(a))
        return a, ("dir" if hit and hit[1] == "dir" else "file")
    rule = (trigger == "correction") if from_user is None else from_user
    if not (rule or trigger in RULE_TRIGGERS):
        return "", "repo"
    from .pinned import _rule_text
    body = _rule_text(text or "")
    dirs = []
    for tok in _text_paths(body):
        hit = paths.get(tok)
        if hit:
            p, kind = hit
            dirs.append(p if kind == "dir" else (p.rsplit("/", 1)[0] if "/" in p else ""))
    common = _common_ancestor(dirs) if dirs else ""
    return (common, "dir") if common else ("", "repo")


_COLS = "id, trigger, text, anchor_path, anchor_symbol, scope_path, scope_kind, level, from_user"


def _apply(con, rows) -> dict:
    paths = _Paths(con, preload=len(rows) > 20)
    upd, kinds = [], {}
    for r in rows:
        sp, sk = assign(con, r["trigger"], r["text"], r["anchor_path"], r["anchor_symbol"], _paths=paths,
                        from_user=bool(r["from_user"]))
        kinds[sk] = kinds.get(sk, 0) + 1
        if (sp, sk) != (r["scope_path"], r["scope_kind"]):
            upd.append((sp, sk, r["id"]))
    if upd:
        con.executemany("UPDATE memories SET scope_path=?, scope_kind=? WHERE id=?", upd)
    con.commit()
    return {"checked": len(rows), "updated": len(upd), "kinds": kinds}


def rescope_new(con, root=None) -> dict:
    """Scope the rows that need it, O(n): rows still at the default whose anchor or rule text may imply a narrower
    scope (any level; a lesson whose scope was set by consolidation is left alone), level-0 rows re-anchored since
    (rename), and rules whose scope directory no longer exists. Idempotent; a second run updates nothing."""
    rows = con.execute(f"""SELECT {_COLS} FROM memories m WHERE
          (m.scope_path='' AND m.scope_kind='repo' AND (m.anchor_path!='' OR m.from_user=1 OR m.trigger='manual'))
       OR (m.level=0 AND m.anchor_path!='' AND m.scope_path!=m.anchor_path)
       OR (m.anchor_path='' AND m.scope_path!='' AND (m.from_user=1 OR m.trigger='manual')
           AND NOT EXISTS (SELECT 1 FROM paths p WHERE p.path=m.scope_path))""").fetchall()
    return _apply(con, rows)


def rescope_all(con, root=None) -> dict:
    """Recompute the scope of every level-0 row (and of any row still at the default). For `memcode rescope`."""
    rows = con.execute(f"SELECT {_COLS} FROM memories WHERE level=0 OR (scope_path='' AND scope_kind='repo')").fetchall()
    return _apply(con, rows)


def _rel(f: str, prefixes: list[str]) -> str | None:
    f = (f or "").replace(os.sep, "/")
    if not f:
        return None
    if not os.path.isabs(f):
        return norm(f)
    for cand in dict.fromkeys([f, os.path.realpath(f).replace(os.sep, "/")]):
        for pre in prefixes:
            if cand.startswith(pre):
                return norm(cand[len(pre):])
    return None


def _root_prefixes(root) -> list[str]:
    if not root:
        return []
    return list(dict.fromkeys(p.replace(os.sep, "/").rstrip("/") + "/"
                              for p in (os.path.realpath(root), os.path.abspath(root))))


def working_set(con, session: str, prompt: str, root=None, active=None) -> set[str]:
    """Paths the request is about: prompt path tokens, absolute paths under `root` named in the prompt, and files
    edited this session (retrieval._active_files; pass `active` to reuse it). Repo-relative, lowercase."""
    from . import retrieval
    ws = {norm(p) for p in retrieval.path_tokens(prompt)}
    pre = _root_prefixes(root)
    for p in pre:
        for m in re.finditer(re.escape(p) + r"([A-Za-z0-9_./-]+)", prompt or ""):
            ws.add(norm(m.group(1)).lower())
    for f in (retrieval._active_files(con, session) if active is None else active):
        r = _rel(f, pre)
        if r:
            ws.add(r.lower())
    return {w for w in ws if w and ".." not in w.split("/")}


def chains(ws) -> set[str]:
    """Union of the working-set paths' scope chains (lowercase; includes '' for the repo)."""
    out = {""}
    for w in ws:
        out.update(store.scope_chain(w))
    return out


def inside(scope_l: str, ws) -> bool:
    return any(scope_l.startswith(w + "/") for w in ws)


def scope_named(prompt_l: str, scope_path: str, kind: str | None) -> bool:
    """The prompt names the scope itself: its path, or (dir) its basename of >= 4 chars / (file) its file name, as a
    standalone token. 'billing/refunds.py' does not name 'billing' (it is inside it: the working set covers that)."""
    sp = (scope_path or "").lower().strip("/")
    if not sp:
        return False
    base = sp.rsplit("/", 1)[-1]
    cands = {sp} | ({base} if (kind != "dir" or len(base) >= 4) else set())
    return any(c in prompt_l and re.search(r"(?<![\w/.])" + re.escape(c) + _NAME_TAIL, prompt_l) for c in cands)


def level_key(r) -> tuple[int, int]:
    """Nearest first: file/symbol (0, 0) < dir (1, -depth: deeper first) < repo (2, 0)."""
    sp = r["scope_path"] if "scope_path" in r.keys() else ""
    if not sp:
        return (2, 0)
    if r["scope_kind"] == "dir":
        return (1, -(sp.strip("/").count("/") + 1))
    return (0, 0)


def allocate(scored: list, k: int) -> list:
    """scored: [(score, row)] in the existing order (score desc, recency, id). Returns the k allocated first (one per
    level nearest first, then the rest of the slots in the existing order; shown nearest first), then the others."""
    if not scored:
        return scored
    levels: dict[tuple, int] = {}
    for i, (_, r) in enumerate(scored):
        levels.setdefault(level_key(r), i)          # each level's best = its first in the existing order
    chosen = [levels[lv] for lv in sorted(levels)][:k]
    taken = set(chosen)
    for i in range(len(scored)):
        if len(chosen) >= k:
            break
        if i not in taken:
            chosen.append(i)
            taken.add(i)
    top = sorted(chosen, key=lambda i: (level_key(scored[i][1]), i))
    return [scored[i] for i in top] + [scored[i] for i in range(len(scored)) if i not in taken]


def rule_marks(con) -> dict[str, int]:
    """{scope path: number of live user rules scoped there} for paths still in the map."""
    return {r[0]: r[1] for r in con.execute(
        """SELECT m.scope_path, COUNT(*) FROM memories m WHERE m.stale=0 AND m.from_user=1
           AND m.scope_path!='' AND EXISTS (SELECT 1 FROM paths p WHERE p.path=m.scope_path)
           GROUP BY m.scope_path""")}


def list_scoped(con, d: str, include_stale: bool = False) -> list:
    """Memories scoped at directory/file `d` or inside it ('' -> repo-scope memories only)."""
    d = norm(d)
    live = "" if include_stale else " AND stale=0"
    if not d:
        return con.execute(f"SELECT * FROM memories WHERE scope_path='' AND mkey IS NULL{live} ORDER BY updated_at DESC").fetchall()
    dl = _fold(d)
    return con.execute(f"""SELECT * FROM memories WHERE (lower(scope_path)=? OR substr(lower(scope_path),1,?)=?){live}
                           ORDER BY scope_path, updated_at DESC""", (dl, len(dl) + 1, dl + "/")).fetchall()


def has_unseen_rules(con, session: str, path: str, root=None) -> bool:
    """True when a user rule scoped on `path`'s chain (repo scope excluded) has not been shown this session."""
    if not hier_enabled():
        return False
    rel = _rel(path, _root_prefixes(root)) if path else None
    chain = [c for c in store.scope_chain(rel or "") if c]
    if not chain:
        return False
    return con.execute(f"""SELECT 1 FROM memories m WHERE m.stale=0 AND m.from_user=1
                           AND m.scope_path IN ({",".join("?" * len(chain))})
                           AND m.id NOT IN (SELECT memory_id FROM injections WHERE session=?) LIMIT 1""",
                       (*chain, session)).fetchone() is not None


TOUCH_HOPS = 3


def _neighbours(con, session: str, ids: list[int]) -> list:
    """Up to TOUCH_HOPS memories linked to `ids` in the memory graph, not shown this session, not the user's words
    (a rule applies where it is scoped), not expired; strongest link first."""
    from . import graph
    out, now = [], time.time()
    for o, w, _ in graph.neighbours(con, ids, limit=TOUCH_HOPS * 4):
        r = con.execute("""SELECT * FROM memories WHERE id=? AND stale=0 AND from_user=0 AND mkey IS NULL
                           AND (expires_at IS NULL OR expires_at>?) AND id NOT IN
                           (SELECT memory_id FROM injections WHERE session=?)""", (o, now, session)).fetchone()
        if r is not None:
            out.append(r)
        if len(out) >= TOUCH_HOPS:
            break
    return out


def rules_for_path(con, session: str, path: str, root=None, token_cap: int = TOUCH_TOKEN_CAP) -> tuple[str, list[int]]:
    """Context for a path the agent just touched (read or edited): the live memories scoped on its scope_chain (repo
    scope excluded: the start block shows it) not yet shown this session, nearest first (rules before notes within a
    level, then newest), then their neighbours in the memory graph, within `token_cap`, framed like retrieval (rules outside the untrusted wrapper, notes
    inside). Records them in `injections` (source 'touch'), so each is injected once per session and retrieval
    skips it later. ('', []) when MEMCODE_HIER is off or nothing applies."""
    if not hier_enabled():
        return "", []
    from . import pinned
    rel = _rel(path, _root_prefixes(root)) if path else None
    chain = [c for c in store.scope_chain(rel or "") if c]
    if not chain:
        return "", []
    marks = ",".join("?" * len(chain))
    rows = con.execute(f"""SELECT * FROM memories m WHERE m.stale=0 AND m.scope_path IN ({marks})
                           AND m.id NOT IN (SELECT memory_id FROM injections WHERE session=?)""",
                       (*chain, session)).fetchall()
    now = time.time()
    rows = [r for r in rows if r["expires_at"] is None or r["expires_at"] > now]
    rows.sort(key=lambda r: (level_key(r), not r["from_user"], -r["updated_at"], -r["id"]))
    rows += _neighbours(con, session, [r["id"] for r in rows])
    rules, notes, ids, used = [], [], [], 0
    for r in rows:
        line = pinned._from_you_line(r) if r["from_user"] else pinned.memory_line(r)
        if (used + len(line)) / pinned.TOKEN_DIVISOR > token_cap:
            break
        used += len(line) + 1
        (rules if r["from_user"] else notes).append(line)
        ids.append(r["id"])
    if not ids:
        return "", []
    parts = []
    if rules:
        parts.append(f"## From you, for {rel} (stated by the user earlier; follow them)\n" + "\n".join(rules))
    if notes:
        parts.append("\n".join([pinned.NOTES_HEADER, pinned.NOTES_OPEN, f"## Memory for {rel}", *notes,
                                pinned.NOTES_CLOSE]))
    con.executemany("INSERT INTO injections(session,memory_id,ts,source) VALUES(?,?,?,'touch')",
                    [(session, i, now) for i in ids])
    con.commit()
    return "\n\n".join(parts), ids
