"""Directory-tree spine: scan, incremental git refresh, staleness marking."""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from .store import sha1, upsert_path

SKIP_DIRS = {".git", ".memcode", "node_modules", "__pycache__"}


def _git(repo_root, *args) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True,
                           check=False)
    except (OSError, ValueError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "surrogateescape")


def _skipped(rel: str) -> bool:
    return any(p in SKIP_DIRS for p in rel.split("/"))


def list_files(repo_root) -> list[str]:
    """Repo-relative files: git ls-files (tracked + untracked, ignoring ignored) or os.walk."""
    out = _git(repo_root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    root = Path(repo_root)
    if out is not None:
        files = [f for f in out.split("\0") if f and not _skipped(f)
                 and (root / f).is_file()]  # drops deleted-but-tracked & submodules
        return sorted(set(files))
    files = []
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in SKIP_DIRS)
        rel_dir = os.path.relpath(dp, root).replace(os.sep, "/")
        for fn in sorted(fns):
            files.append(fn if rel_dir == "." else f"{rel_dir}/{fn}")
    return files


def _hash_file(repo_root, rel) -> str | None:
    try:
        return sha1((Path(repo_root) / rel).read_bytes())
    except OSError:
        return None


def _ensure_dirs(con, rel: str) -> None:
    upsert_path(con, "", "dir")
    parts = rel.split("/")[:-1]
    for i in range(1, len(parts) + 1):
        upsert_path(con, "/".join(parts[:i]), "dir")


def _add_file(con, repo_root, rel) -> None:
    _ensure_dirs(con, rel)
    h = _hash_file(repo_root, rel)
    if h is None:
        return
    upsert_path(con, rel, "file", content_hash=h)
    # upsert's COALESCE keeps old hash when new is None; here h is never None.


def scan_repo(con, repo_root) -> dict:
    """Populate `paths` from the working tree; removes rows for vanished paths."""
    files = list_files(repo_root)
    now = time.time()
    keep = {""}
    for f in files:
        parts = f.split("/")
        for i in range(1, len(parts)):
            keep.add("/".join(parts[:i]))
        keep.add(f)
    upsert_path(con, "", "dir")
    for f in files:
        _add_file(con, repo_root, f)
    existing = [r[0] for r in con.execute("SELECT path FROM paths")]
    gone = [p for p in existing if p not in keep]
    con.executemany("DELETE FROM paths WHERE path=?", [(p,) for p in gone])
    con.commit()
    return {"files": len(files), "dirs": len(keep) - len(files) - 1,
            "removed": len(gone), "at": now}


def _prune_empty_dirs(con) -> None:
    while True:
        rows = con.execute(
            """SELECT path FROM paths d WHERE kind='dir' AND path!='' AND NOT EXISTS
               (SELECT 1 FROM paths c WHERE c.parent=d.path)""").fetchall()
        if not rows:
            return
        con.executemany("DELETE FROM paths WHERE path=?", [(r[0],) for r in rows])
        con.commit()


def refresh_from_git_diff(con, repo_root, since_rev: str | None = None) -> dict:
    """Incremental update from `git diff --name-status` (vs since_rev, default HEAD).

    Renames re-anchor memories (anchor_path moves to the new path). Falls back to a
    full scan when git is unavailable or the diff fails.
    """
    args = ["diff", "--name-status", "-M", "-z"]
    args.append(since_rev or "HEAD")
    out = _git(repo_root, *args)
    if out is None:
        res = scan_repo(con, repo_root)
        res["fallback"] = True
        return res
    toks = out.split("\0")
    if toks and toks[-1] == "":
        toks.pop()
    stats = {"added": 0, "modified": 0, "deleted": 0, "renamed": 0}
    i = 0
    now = time.time()
    while i < len(toks):
        status = toks[i]
        c = status[0]
        if c in "RC":
            old, new = toks[i + 1], toks[i + 2]
            i += 3
            if _skipped(new):
                continue
            _add_file(con, repo_root, new)
            if c == "R":
                con.execute("DELETE FROM paths WHERE path=?", (old,))
                con.execute("UPDATE memories SET anchor_path=?, updated_at=? "
                            "WHERE anchor_path=?", (new, now, old))
                stats["renamed"] += 1
            else:
                stats["added"] += 1
        else:
            p = toks[i + 1]
            i += 2
            if _skipped(p):
                continue
            if c == "D":
                con.execute("DELETE FROM paths WHERE path=?", (p,))
                stats["deleted"] += 1
            elif (Path(repo_root) / p).is_file():
                _add_file(con, repo_root, p)
                stats["added" if c == "A" else "modified"] += 1
    # untracked (not ignored) files are invisible to git diff
    untracked = _git(repo_root, "ls-files", "-z", "--others", "--exclude-standard") or ""
    for f in filter(None, untracked.split("\0")):
        if not _skipped(f) and (Path(repo_root) / f).is_file():
            _add_file(con, repo_root, f)
            stats["added"] += 1
    con.commit()
    _prune_empty_dirs(con)
    return stats


def mark_stale(con, repo_root) -> int:
    """Set stale=1 where the anchor path is gone or its hash differs from anchor_hash.

    Memories without an anchor_hash (or repo-wide, anchor '') never go stale.
    Returns the number of newly staled memories.
    """
    rows = con.execute("SELECT id, anchor_path, anchor_hash FROM memories "
                       "WHERE stale=0 AND anchor_hash IS NOT NULL AND anchor_path!=''"
                       ).fetchall()
    n = 0
    for r in rows:
        p = Path(repo_root) / r["anchor_path"]
        cur = _hash_file(repo_root, r["anchor_path"]) if p.is_file() else None
        if cur is None or cur != r["anchor_hash"]:
            con.execute("UPDATE memories SET stale=1, updated_at=? WHERE id=?",
                        (time.time(), r["id"]))
            n += 1
    con.commit()
    return n
