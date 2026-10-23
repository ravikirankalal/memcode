"""Local embeddings: hashed TF-IDF vectors over a memory's words, identifier parts and paths (stdlib only).

A vector is sparse: {bucket: weight}, bucket = crc32(term) mod DIM, weight = 1 + log(term count); it is stored in
memory_vectors with a hash of the text it was built from, so a changed memory gets a new vector on the next refresh.
IDF is applied at comparison time from the vectors stored, so adding memories never invalidates the old ones.
"""
from __future__ import annotations

import json
import math
import zlib

from . import retrieval, store

DIM = 1 << 20
# retrieval.STOP minus words that carry meaning in a memory (IDF already weighs down the common ones)
STOP = retrieval.STOP - {"test", "tests", "fix", "change", "update", "file", "files", "code", "function", "functions",
                         "new", "add", "make", "get", "set", "use", "using"}


def tokens(text: str, anchor: str = "") -> list[str]:
    """Words and identifier parts (as retrieval.terms, with repeats), plus path segments of the anchor and the text."""
    out = []
    for w in retrieval._WORD.findall(text or ""):
        for part in dict.fromkeys([w] + w.split("_") + retrieval._CAMEL.findall(w)):
            p = part.lower()
            if len(p) >= 3 and p not in STOP:
                plural = p.endswith("s") and len(p) > 4 and not p.endswith(("ss", "us", "is", "ys"))
                out.append(p[:-1] if plural else p)
    for path in retrieval.path_tokens(text or "") | ({anchor} if anchor else set()):
        out.append("path:" + path.strip("/").lower())
    return out


def vector(text: str, anchor: str = "") -> dict[int, float]:
    counts: dict[int, int] = {}
    for t in tokens(text, anchor):
        b = zlib.crc32(t.encode("utf-8")) % DIM
        counts[b] = counts.get(b, 0) + 1
    return {b: 1.0 + math.log(n) for b, n in counts.items()}


def _src(row) -> str:
    return store.sha1(f"{row['text']}\0{row['anchor_path']}".encode("utf-8"))


def refresh(con) -> list[int]:
    """Build the vectors of new or changed memories; -> their ids. The caller commits."""
    have = dict(con.execute("SELECT memory_id, src_hash FROM memory_vectors").fetchall())
    changed = []
    for r in con.execute("SELECT id, text, anchor_path FROM memories").fetchall():
        h = _src(r)
        if have.get(r["id"]) != h:
            vec = vector(r["text"], r["anchor_path"])
            con.execute("INSERT OR REPLACE INTO memory_vectors(memory_id, vec, src_hash) VALUES(?,?,?)",
                        (r["id"], json.dumps(vec), h))
            changed.append(r["id"])
    return changed


def load(con, where: str = "", params=()) -> dict[int, dict[int, float]]:
    """{memory id: vector} for live memories (optionally narrowed by a condition on memories m)."""
    rows = con.execute(f"""SELECT v.memory_id, v.vec FROM memory_vectors v JOIN memories m ON m.id=v.memory_id
                           WHERE m.stale=0{' AND ' + where if where else ''}""", params).fetchall()
    return {mid: {int(k): w for k, w in json.loads(vec).items()} for mid, vec in rows}


def idf(vectors: dict[int, dict[int, float]]) -> dict[int, float]:
    n = len(vectors)
    df: dict[int, int] = {}
    for v in vectors.values():
        for b in v:
            df[b] = df.get(b, 0) + 1
    return {b: math.log((1 + n) / (1 + d)) + 1.0 for b, d in df.items()}


def weigh(vec: dict[int, float], idfs: dict[int, float]) -> dict[int, float]:
    """TF-IDF weights, unit length."""
    w = {b: x * idfs.get(b, 1.0) for b, x in vec.items()}
    norm = math.sqrt(sum(x * x for x in w.values())) or 1.0
    return {b: x / norm for b, x in w.items()}


def cosine(a: dict[int, float], b: dict[int, float]) -> float:
    """Of two weighed (unit-length) vectors."""
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b[k] for k, x in a.items() if k in b)


def search(con, text: str, k: int = 10, where: str = "", params=(), min_score: float = 0.05) -> list[tuple[int, float]]:
    """The k live memories closest to `text`: [(id, cosine)], best first."""
    refresh(con)
    vectors = load(con, where, params)
    if not vectors:
        return []
    idfs = idf(vectors)
    q = weigh(vector(text), idfs)
    scored = [(mid, cosine(q, weigh(v, idfs))) for mid, v in vectors.items()]
    return sorted((s for s in scored if s[1] >= min_score), key=lambda s: -s[1])[:k]
