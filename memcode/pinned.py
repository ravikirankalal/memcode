"""Deterministic pinned context: compact tree + annotations + conventions + memories."""
from __future__ import annotations

TOKEN_DIVISOR = 4
LINE_MAX = 160


def approx_tokens(text: str) -> float:
    return len(text) / TOKEN_DIVISOR


def _one_line(s: str, n: int = LINE_MAX) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _tree_lines(con) -> list[str]:
    paths = con.execute("SELECT path, parent, kind, annotation FROM paths "
                        "WHERE path!='' ORDER BY path").fetchall()
    mem_paths = {r[0] for r in con.execute(
        "SELECT DISTINCT anchor_path FROM memories WHERE stale=0 AND anchor_path!=''")}
    children: dict[str, list] = {}
    for r in paths:
        children.setdefault(r["parent"], []).append(r)
    info = {r["path"]: r for r in paths}
    hot: set[str] = set()
    for r in paths:
        if r["annotation"] or r["path"] in mem_paths:
            p = r["path"]
            while p != "":
                hot.add(p)
                p = info[p]["parent"] if p in info else ""
    # memory anchored at a path missing from `paths` still heats known ancestors
    for p in mem_paths:
        if p not in info:
            q = p.rsplit("/", 1)[0] if "/" in p else ""
            while q != "":
                hot.add(q)
                q = q.rsplit("/", 1)[0] if "/" in q else ""

    def count_files(d: str) -> int:
        return sum(1 if c["kind"] == "file" else count_files(c["path"])
                   for c in children.get(d, []))

    lines: list[str] = []

    def walk(d: str, depth: int) -> None:
        hidden_files = 0
        for c in children.get(d, []):  # already sorted by path
            name = c["path"].rsplit("/", 1)[-1]
            note = f" - {_one_line(c['annotation'], 100)}" if c["annotation"] else ""
            ind = "  " * depth
            if c["kind"] == "dir":
                if c["path"] in hot:
                    lines.append(f"{ind}{name}/{note}")
                    walk(c["path"], depth + 1)
                else:
                    lines.append(f"{ind}{name}/ ({count_files(c['path'])} files){note}")
            elif c["path"] in hot or c["annotation"]:
                lines.append(f"{ind}{name}{note}")
            else:
                hidden_files += 1
        if hidden_files:
            lines.append(f"{'  ' * depth}(+{hidden_files} files)")

    walk("", 0)
    return lines


def _memory_rows(con, convention: bool):
    cond = "m.trigger='correction'" if convention else "m.trigger!='correction'"
    return con.execute(
        f"""SELECT m.* , (SELECT COUNT(*) FROM retrievals r WHERE r.memory_id=m.id) AS freq
            FROM memories m WHERE m.stale=0 AND {cond}
            ORDER BY freq DESC, m.updated_at DESC, m.id DESC""").fetchall()


def render_pinned(con, repo_root=None, token_cap: int = 1500) -> str:
    """Render the pinned block. Ordering is recency/frequency only (never salience)."""
    cap_chars = int(token_cap * TOKEN_DIVISOR)
    out: list[str] = []
    used = 0

    def add(line: str) -> bool:
        nonlocal used
        cost = len(line) + 1
        if used + cost > cap_chars:
            return False
        out.append(line)
        used += cost
        return True

    def section(title: str, lines: list[str], budget_chars: int) -> None:
        if not lines:
            return
        start = used
        if not add(title):
            return
        for i, ln in enumerate(lines):
            if used - start + len(ln) + 1 > budget_chars or not add(ln):
                add(f"(+{len(lines) - i} more)")
                break

    tree = _tree_lines(con)
    section("## Map", tree, cap_chars // 2)

    conv = [f"- {_one_line(r['text'])}" + (f" [{r['anchor_path']}]" if r["anchor_path"] else "")
            for r in _memory_rows(con, True)]
    section("## Conventions", conv, (cap_chars - used) // 2)

    mems = [f"- ({r['trigger']}) {_one_line(r['text'])}"
            + (f" [{r['anchor_path']}]" if r["anchor_path"] else "")
            for r in _memory_rows(con, False)]
    section("## Memories", mems, cap_chars - used)

    text = "\n".join(out)
    return text[:cap_chars]
