"""Day one: the first session in a repository has the memory agent read the repository's key files once, so the
project profile (stack, infra, deployment, branching, structure, where docs and scripts live, conventions) exists
before anyone has worked here.

The files are shown to the agent as [read] lines (and the branches and recent commit subjects as [ran] lines), the
same evidence it reads in a session; one call, outside the session's running conversation. CLAUDE.md and AGENTS.md
are left out: Claude Code already gives them to the coding agent every session.
"""
from __future__ import annotations

import glob
import os
import subprocess

from . import curate, model

PER_FILE = 1500
TOTAL = 20000
MAX_ITEMS = 10               # a whole repository at once: more room than one turn's piece

# what to read, in order (globs relative to the repository root); the first matches win until TOTAL
FILES = ("README*", "CONTRIBUTING*", "docs/*.md", "package.json", "pyproject.toml", "setup.cfg", "Cargo.toml",
         "go.mod", "pom.xml", "build.gradle*", "Makefile", "justfile", "Dockerfile", "docker-compose*.y*ml",
         "compose*.y*ml", ".github/workflows/*.y*ml", ".gitlab-ci.yml", "Jenkinsfile", ".circleci/config.yml",
         "CODEOWNERS", ".github/CODEOWNERS", "Procfile", "fly.toml", "vercel.json", "netlify.toml", "app.yaml",
         "serverless.y*ml", "Chart.yaml", "*/Chart.yaml", "deploy/**/*.y*ml", "k8s/**/*.y*ml", "infra/**/*.tf",
         "terraform/**/*.tf", "*.tf")
PER_GLOB = 4
SKIP = {"CLAUDE.md", "AGENTS.md"}

PREFACE = ("This message is not a session transcript. memcode read this repository's key files once, so you can build "
           "the project profile now, before anyone works here. There are no [user] lines, so nothing here is "
           "from_user and there are no decisions. Propose what a newcomer needs and the files show: the stack and "
           "build, infra, deployment, branching (from the branches and the CI triggers), structure, where important "
           "docs and scripts are, important links, integrations, central components, conventions (commit messages "
           "from the recent subjects), workflows the files state (how to build, test, release), and anything unusual "
           "for this kind of project. Quote the [read] or [ran] line as evidence. CLAUDE.md and AGENTS.md are not "
           "shown: the coding agent gets them every session, so never restate what they would say.")


def _git(root, *args) -> str:
    try:
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10)
        return " ".join(p.stdout.split()) if p.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def gather(root) -> str:
    """The condensed 'transcript' of the repository's key files, at most TOTAL characters."""
    root = str(root)
    lines, used, seen = [], 0, set()
    for pattern in FILES:
        for p in sorted(glob.glob(os.path.join(root, pattern), recursive=True))[:PER_GLOB]:
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if rel in seen or os.path.basename(p) in SKIP or not os.path.isfile(p) or "/node_modules/" in f"/{rel}":
                continue
            seen.add(rel)
            try:
                with open(p, errors="replace") as fh:
                    text = " ".join(fh.read(PER_FILE * 2).split())[:PER_FILE]
            except OSError:
                continue
            if not text:
                continue
            line = f"[read] {rel} | {text}"
            if used + len(line) > TOTAL:
                break
            lines.append(line)
            used += len(line) + 1
    top = sorted(e + ("/" if os.path.isdir(os.path.join(root, e)) else "") for e in os.listdir(root)
                 if not e.startswith(".") or e in (".github", ".gitlab-ci.yml"))
    lines.append(f"[ran] `ls` -> ok | {' '.join(top)[:600]}")
    branches = _git(root, "branch", "-a", "--format=%(refname:short)")
    if branches:
        lines.append(f"[ran] `git branch -a` -> ok | {branches[:400]}")
    subjects = _git(root, "log", "-n", "15", "--format=%s |")
    if subjects:
        lines.append(f"[ran] `git log -n 15 --format=%s` -> ok | {subjects[:1200]}")
    return "\n".join(lines)


def run(root, extract_fn=model.extract) -> list[int]:
    """Read the repository once and store what the memory agent keeps. -> ids stored."""
    from .. import activity, store
    con = store.connect(root)
    try:
        condensed = gather(root)
        if not condensed.strip():
            return []
        activity.busy(con, "agent", True)
        try:
            res = extract_fn(condensed, PREFACE + "\n\n" + model.briefing(con, str(root), "bootstrap"))
        finally:
            activity.busy(con, "agent", False)
        if not res or "items" not in res:
            return []
        ids = curate.store_items(con, str(root), "bootstrap", res["items"], condensed, res.get("model", ""),
                                 max_items=MAX_ITEMS)
        activity.note(con, "scanned", f"read the repository: {len(res['items'])} candidates, kept {len(ids)}",
                      len(res["items"]))
        curate._log(con, "bootstrap", "read", None, after=f"read the repository: kept {len(ids)}",
                    evidence=f"${res.get('cost_usd') or 0:.4f}")
        con.commit()
        return ids
    finally:
        con.close()
