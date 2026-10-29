"""Did the coding agent use what memcode showed it? Verdicts per memory and session, fed back to the memory agent.

A memory shown next to the work (per prompt, after an action, on first touch, or flagged by the memory agent) is
`used` when one of the coding agent's replies names it in a `memcode:` line (display.MENTION asks for that), else
`unused`. The start block is not judged: it holds everything. Verdicts go to the memory agent in its next message
(conversation.delta), so it can sharpen a memory that keeps being recalled for the wrong requests or retire noise; a
memory shown MUTE_UNUSED times without ever being used is no longer recalled (retrieval._candidates) until it is
used or changed.
"""
from __future__ import annotations

import re
import time

JUDGED = ("prompt", "action", "touch", "flagged")
MUTE_UNUSED = 3
_QUOTE = re.compile(r"memcode:\s*(.{8,300})", re.I)


def _terms(text: str) -> set:
    from . import embed
    return set(embed.tokens(text))


def judge(con, session: str, condensed: str) -> tuple[list[int], list[int]]:
    """Verdicts for this session's memories shown next to the work and not judged yet, from the coding agent's replies
    in `condensed` (judged only once a reply is there). -> (used ids, unused ids)."""
    if "[agent] " not in condensed:
        return [], []
    rows = con.execute("""SELECT memory_id, MIN(source) AS source FROM injections WHERE session=? AND source IN
                          (%s) AND memory_id NOT IN (SELECT memory_id FROM memory_feedback WHERE session=?)
                          GROUP BY memory_id""" % ",".join("?" * len(JUDGED)), (session, *JUDGED, session)).fetchall()
    if not rows:
        return [], []
    quotes = [_terms(m.group(1)) for line in condensed.splitlines() if line.startswith("[agent] ")
              for m in _QUOTE.finditer(line)]
    used, unused, now = [], [], time.time()
    for mid, source in rows:
        r = con.execute("SELECT text FROM memories WHERE id=?", (mid,)).fetchone()
        if r is None:
            continue
        t = _terms(r["text"])
        hit = any(len(q & t) >= 3 or (t and len(q & t) / len(t) >= 0.4) for q in quotes)
        (used if hit else unused).append(mid)
        con.execute("INSERT OR REPLACE INTO memory_feedback(session, memory_id, verdict, source, ts) VALUES(?,?,?,?,?)",
                    (session, mid, "used" if hit else "unused", source, now))
    con.commit()
    return used, unused


def counts(con, ids=None) -> dict[int, tuple[int, int]]:
    """{memory id: (times used, times shown but unused)}, over every session."""
    out: dict[int, list] = {}
    for mid, verdict, n in con.execute("SELECT memory_id, verdict, COUNT(*) FROM memory_feedback GROUP BY 1, 2"):
        if ids is None or mid in ids:
            out.setdefault(mid, [0, 0])[0 if verdict == "used" else 1] += n
    return {k: (v[0], v[1]) for k, v in out.items()}


def muted(con) -> set[int]:
    """Memories shown MUTE_UNUSED times next to the work and never used since they last changed: not recalled."""
    return {mid for (mid,) in con.execute(
        """SELECT f.memory_id FROM memory_feedback f JOIN memories m ON m.id=f.memory_id WHERE f.ts > m.updated_at
           GROUP BY f.memory_id HAVING SUM(f.verdict='used')=0 AND SUM(f.verdict='unused') >= ?""", (MUTE_UNUSED,))}


def delta_lines(con, session: str, since: float) -> list[str]:
    """For the memory agent's next message: what was used, and what was shown but not used."""
    rows = con.execute("""SELECT f.memory_id, f.verdict, f.source, m.text FROM memory_feedback f JOIN memories m
                          ON m.id=f.memory_id WHERE f.session=? AND f.ts>? ORDER BY f.memory_id""",
                       (session, since)).fetchall()
    if not rows:
        return []
    tally = counts(con, {r["memory_id"] for r in rows})
    where = {"prompt": "recalled for a prompt", "action": "recalled after a command or edit",
             "touch": "shown on first touch of its folder", "flagged": "flagged by you"}
    out = []
    for r in rows:
        u, n = tally.get(r["memory_id"], (0, 0))
        out.append(f"- {'used' if r['verdict'] == 'used' else 'shown but not used'}: #{r['memory_id']} "
                   f"({where.get(r['source'], r['source'])}; {u} used, {n} unused so far): "
                   f"{' '.join(r['text'].split())[:140]}")
    return out
