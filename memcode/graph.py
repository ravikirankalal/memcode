"""The memory graph: links between related memories (table memory_links).

Automatic links (source 'auto') are rebuilt for a memory whenever it is new or its text changed: `same_file` to
memories anchored on the same file, `similar` to its SIMILAR_K closest memories by local embedding (embed.py) when
the cosine reaches SIMILAR_MIN. The memory agent proposes links of its own (related, refines, contradicts; source
'agent'), kept until either end is deleted. Links are undirected: stored with src < dst and looked up both ways.
Command facts take no automatic links (one per command run here: they would crowd out the rest); vector search
still finds them.
"""
from __future__ import annotations

import time

from . import embed

SIMILAR_MIN = 0.2
SIMILAR_K = 3
SAME_FILE_MAX = 8
_LINKED = "m.trigger!='command'"


def link(con, a: int, b: int, kind: str, weight: float = 1.0, source: str = "agent") -> None:
    if a == b:
        return
    a, b = min(a, b), max(a, b)
    con.execute("""INSERT INTO memory_links(src, dst, kind, weight, source, ts) VALUES(?,?,?,?,?,?)
                   ON CONFLICT(src, dst, kind) DO UPDATE SET weight=excluded.weight, source=excluded.source,
                   ts=excluded.ts""", (a, b, kind, float(weight), source, time.time()))


def update(con) -> int:
    """Embed new or changed memories and rebuild their automatic links; -> how many memories changed. Commits."""
    changed = embed.refresh(con)
    if not changed:
        con.commit()
        return 0
    vectors = embed.load(con, _LINKED)
    idfs = embed.idf(vectors)
    weighed = {m: embed.weigh(v, idfs) for m, v in vectors.items()}
    anchors = {r[0]: r[1] for r in con.execute(f"SELECT id, anchor_path FROM memories m WHERE stale=0 AND {_LINKED}")}
    for mid in changed:
        con.execute("DELETE FROM memory_links WHERE source='auto' AND (src=? OR dst=?)", (mid, mid))
        if mid not in weighed:
            continue
        a = anchors.get(mid)
        if a:
            for o in [o for o, p in anchors.items() if p == a and o != mid][:SAME_FILE_MAX]:
                link(con, mid, o, "same_file", 1.0, "auto")
        sims = sorted(((o, embed.cosine(weighed[mid], w)) for o, w in weighed.items() if o != mid),
                      key=lambda s: -s[1])[:SIMILAR_K]
        for o, s in sims:
            if s >= SIMILAR_MIN:
                link(con, mid, o, "similar", round(s, 3), "auto")
    con.commit()
    return len(changed)


def neighbours(con, ids, limit: int = 10) -> list[tuple[int, float, str]]:
    """Live memories one link away from `ids` (not in `ids`): [(id, weight, kind)], strongest first."""
    ids = [int(i) for i in ids]
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    rows = con.execute(f"""SELECT CASE WHEN l.src IN ({marks}) THEN l.dst ELSE l.src END AS other, l.weight, l.kind
                           FROM memory_links l WHERE (l.src IN ({marks}) OR l.dst IN ({marks}))""",
                       (*ids, *ids, *ids)).fetchall()
    best: dict[int, tuple[float, str]] = {}
    for other, w, kind in rows:
        if other not in ids and (other not in best or w > best[other][0]):
            best[other] = (w, kind)
    if not best:
        return []
    live = {r[0] for r in con.execute(f"SELECT id FROM memories WHERE stale=0 AND id IN ({','.join('?' * len(best))})",
                                      tuple(best))}
    return sorted(((o, w, k) for o, (w, k) in best.items() if o in live), key=lambda x: (-x[1], x[0]))[:limit]


def degree(con) -> dict[int, float]:
    """{memory id: summed link weight}: how connected each memory is (for ranking)."""
    out: dict[int, float] = {}
    for src, dst, w in con.execute("SELECT src, dst, weight FROM memory_links"):
        out[src] = out.get(src, 0.0) + w
        out[dst] = out.get(dst, 0.0) + w
    return out
