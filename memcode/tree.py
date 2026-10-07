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
    """sha1 of a regular file inside the repo; symlinks that leave the repo are not followed."""
    try:
        root = Path(repo_root).resolve()
        f = (root / rel).resolve()
        f.relative_to(root)
        return sha1(f.read_bytes())
    except (OSError, ValueError):
        return None


def _ensure_dirs(con, rel: str) -> None:
    upsert_path(con, "", "dir", commit=False)
    parts = rel.split("/")[:-1]
    for i in range(1, len(parts) + 1):
        upsert_path(con, "/".join(parts[:i]), "dir", commit=False)


def _add_file(con, repo_root, rel) -> None:
    """Register a file (no commit; callers batch)."""
    _ensure_dirs(con, rel)
    h = _hash_file(repo_root, rel)
    if h is None:
        return
    try:
        st = os.stat(Path(repo_root) / rel)
        mt, sz = st.st_mtime_ns, st.st_size
    except OSError:
        mt = sz = None
    upsert_path(con, rel, "file", content_hash=h, mtime_ns=mt, size=sz, commit=False)


def _reanchor_by_hash(con) -> int:
    """Memories whose anchor file vanished follow the file if exactly one current file has
    the anchored content hash (plain `mv`, or a committed rename)."""
    n = 0
    rows = con.execute(
        """SELECT m.id, m.anchor_hash FROM memories m WHERE m.anchor_path!='' AND m.anchor_hash IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM paths p WHERE p.path=m.anchor_path)""").fetchall()
    for r in rows:
        cands = con.execute("SELECT path FROM paths WHERE kind='file' AND content_hash=?",
                            (r["anchor_hash"],)).fetchall()
        if len(cands) == 1:
            con.execute("UPDATE memories SET anchor_path=?, stale=0, updated_at=? WHERE id=?",
                        (cands[0][0], time.time(), r["id"]))
            n += 1
    return n


def scan_repo(con, repo_root) -> dict:
    """Populate `paths` from the working tree in ONE transaction; removes rows for vanished
    paths. Files whose mtime and size are unchanged are neither re-hashed nor rewritten."""
    files = list_files(repo_root)
    now = time.time()
    root = Path(repo_root)
    keep = {""}
    for f in files:
        parts = f.split("/")
        for i in range(1, len(parts)):
            keep.add("/".join(parts[:i]))
        keep.add(f)
    existing = {r["path"]: r for r in con.execute(
        "SELECT path, kind, content_hash, mtime_ns, size FROM paths")}
    fileset = set(files)
    for d in sorted(p for p in keep if p not in fileset):
        if d not in existing or existing[d]["kind"] != "dir":
            upsert_path(con, d, "dir", commit=False)
    hashed = 0
    for f in files:
        old = existing.get(f)
        try:
            st = os.stat(root / f)
        except OSError:
            continue
        if old is not None and old["kind"] == "file" and old["content_hash"] \
                and old["mtime_ns"] == st.st_mtime_ns and old["size"] == st.st_size:
            continue
        h = _hash_file(repo_root, f)
        if h is None:
            continue
        hashed += 1
        upsert_path(con, f, "file", content_hash=h, mtime_ns=st.st_mtime_ns,
                    size=st.st_size, commit=False)
    gone = [p for p in existing if p not in keep]
    con.executemany("DELETE FROM paths WHERE path=?", [(p,) for p in gone])
    reanchored = _reanchor_by_hash(con)
    con.commit()
    return {"files": len(files), "dirs": len(keep) - len(files) - 1,
            "removed": len(gone), "hashed": hashed, "reanchored": reanchored, "at": now}


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
    dir_moves: set = set()
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
                con.execute("UPDATE memories SET anchor_path=?, anchor_hash=COALESCE(?, anchor_hash),"
                            " stale=0, updated_at=? WHERE anchor_path=?",
                            (new, _hash_file(repo_root, new), now, old))
                od, nd = os.path.dirname(old), os.path.dirname(new)
                if od != nd and os.path.basename(old) == os.path.basename(new):
                    dir_moves.add((od, nd))
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
    for od, nd in sorted(dir_moves):   # directory renames: rewrite anchors under the old dir
        if od and not (Path(repo_root) / od).exists():
            con.execute("UPDATE memories SET anchor_path=? || substr(anchor_path, ?), updated_at=? "
                        "WHERE anchor_path=? OR substr(anchor_path,1,?)=?",
                        (nd, len(od) + 1, now, od, len(od) + 1, od + "/"))
    stats["reanchored"] = _reanchor_by_hash(con)  # plain `mv`: D + untracked, same hash
    con.commit()
    _prune_empty_dirs(con)
    return stats


def mark_stale(con, repo_root) -> int:
    """Reconcile `stale` with the working tree (reversible).

    A memory is stale when its anchor is gone, or its anchor_hash is set and differs from
    the file's current hash. Stale memories whose anchor matches again are revived.
    Repo-wide memories (anchor '') never go stale. Returns the number newly staled.
    """
    rows = con.execute("SELECT id, anchor_path, anchor_hash, stale FROM memories "
                       "WHERE anchor_path!=''").fetchall()
    root = Path(repo_root)
    n = 0
    now = time.time()
    for r in rows:
        p = root / r["anchor_path"]
        if r["anchor_hash"] is not None:
            cur = _hash_file(repo_root, r["anchor_path"]) if p.is_file() else None
            bad = cur is None or cur != r["anchor_hash"]
        else:
            bad = not p.exists()
        if bad != bool(r["stale"]):
            con.execute("UPDATE memories SET stale=?, updated_at=? WHERE id=?",
                        (int(bad), now, r["id"]))
            n += bad
    con.commit()
    return n
