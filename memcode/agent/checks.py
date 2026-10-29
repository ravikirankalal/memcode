"""What a proposal must pass before memcode stores it: evidence quoted from the log, rules and decisions only from the
user's words, no request for now, nothing about memcode's own tooling, no repeat of a memory or of what the coding
agent was already shown; and whether a note is tied to its file's content."""
from __future__ import annotations

import os
import re

from . import model

DUP_OVERLAP = 0.6            # term overlap with an existing memory or fact that counts as a repeat

_SELF_TOOLS = re.compile(r"(?i)\bmemory_(?:add|search|pinned|facts)\b|\b(?:agent|assistant)'?s? (?:own )?memory\b")

_SELF = re.compile(r"(?i)\b(?:memcode|memory_(?:add|search|pinned|facts)|(?:agent|assistant)'?s? (?:own )?memory)\b")


def _norm(s: str) -> str:
    """For matching quotes: case, spacing and markdown emphasis/code marks ignored (the model quotes `**X**` as X)."""
    return " ".join(re.sub(r"[*`]", "", str(s)).lower().split())

def _terms(s: str) -> set:
    from ..retrieval import terms
    return terms(s)

# a decision backed only by a [ran] line must read as a settled question, not as the agent's progress (#42 follow-up:
# "#42 is implemented and its tests pass ... pushed ... not released yet" was stored from a passing test run)
_RESULT = re.compile(r"(?i)\b(?:verified|disprove[nd]|confirmed|ruled out|reproduce[sd]?|does not reproduce|"
                     r"root cause|turned out|is caused by|caused by)\b")

_PROGRESS = re.compile(r"(?i)\b(?:implemented|pushed|committed|merged|released|unreleased|branch|tests? pass(?:es|ed)?|"
                       r"PR|pull request|version \d|is (?:done|finished|complete))\b")

def _self_repo(root) -> bool:
    """memcode's own source tree: there "memcode" is the product, not the agent's memory tooling."""
    return bool(root) and os.path.isfile(os.path.join(str(root), "memcode", "agent", "checks.py"))

def verified(item: dict, condensed: str, root=None) -> str | None:
    """'rule' | 'decision' | 'note' when the item passes the checks, else None: evidence quoted from the transcript, no
    conflict with the user's rules (the model's flag), nothing about the agent's own memory or tools."""
    ev = _norm(item.get("evidence", ""))
    text = " ".join(str(item.get("text", "")).split())
    if len(ev) < 8 or len(text) < 8 or len(text) > 300 or item.get("conflicts") is True:
        return None
    if _SELF.search(text) and not (_self_repo(root) and not _SELF_TOOLS.search(text)):
        return None
    lines = [_norm(l) for l in condensed.splitlines()]
    hits = [l for l in lines if ev in l]
    if not hits:
        return None
    if item.get("kind") == "decision":      # the user's words, or a result a command showed; never the agent's plan
        if any(l.startswith("[user]") for l in hits):
            return "decision"
        # only command output: a settled question ("hypothesis X disproven"), never the agent's progress report
        ran = any(l.startswith("[ran]") for l in hits)
        return "decision" if ran and _RESULT.search(text) and not _PROGRESS.search(text) else None
    if item.get("kind") == "rule":
        users = [l for l in hits if l.startswith("[user]")]
        if not users:
            return None     # rule-shaped but not the user's words: a fixture, an issue, another repo's rules

        from ..triggers import now_request
        # a request for now is not a rule, however the model labels it (#33)
        return None if now_request(text) or any(now_request(l) for l in users) else "rule"
    return "note"

def why_not(item: dict, condensed: str, root=None) -> str:
    """Why verified() refused an item, in words for the memory agent."""
    ev = _norm(item.get("evidence", ""))
    text = " ".join(str(item.get("text", "")).split())
    if item.get("conflicts") is True:
        return "it would contradict or weaken a from_user memory"
    if len(ev) < 8 or len(text) < 8 or len(text) > 300:
        return "the text must be 8-300 characters and the evidence an exact quote of 8+ characters"
    if _SELF.search(text) and not (_self_repo(root) and not _SELF_TOOLS.search(text)):
        return "it is about the coding agent's own memory tools"
    hits = [l for l in (_norm(x) for x in condensed.splitlines()) if ev in l]
    if not hits:
        return "the evidence is not an exact quote of the transcript"
    if item.get("kind") == "decision":
        return "a decision needs the user's words, or a [ran] result that settles a question (not the agent's progress)"
    if item.get("kind") == "rule":
        return ("from_user needs the user's own words as evidence (a [user] line), and never a request for right now")
    return "it did not pass the checks"

def is_repeat(con, text: str) -> bool:
    t = _terms(text)
    if not t:
        return True
    rows = [r[0] for r in con.execute("SELECT text FROM memories WHERE stale=0")]      # keyed memories (facts) too
    for other in rows:
        o = _terms(other)
        # most of the NEW item's terms already in one memory; a short fact ("shelf") never swallows a long item
        if len(o) >= 3 and len(t & o) / len(t) >= DUP_OVERLAP:
            return True
    return False

def user_evidence(item: dict, condensed: str) -> bool:
    ev = _norm(item.get("evidence", ""))
    return bool(ev) and any(_norm(l).startswith("[user]") and ev in _norm(l) for l in condensed.splitlines())

def echoes_context(con, session: str, item: dict, condensed: str) -> bool:
    """The item's only evidence is the main agent repeating a memory memcode already showed it this session: an
    [agent] line whose quoted part mostly repeats a shown memory. That is the memory being used, not new knowledge."""
    ev = _norm(item.get("evidence", ""))
    if not ev or any(_norm(l).startswith("[user]") and ev in _norm(l) for l in condensed.splitlines()):
        return False
    t = _terms(ev)
    if not t:
        return False
    shown = model.shown_ids(con, session)
    if not shown:
        return False
    marks = ",".join("?" * len(shown))
    for (text,) in con.execute(f"SELECT text FROM memories WHERE id IN ({marks})", tuple(shown)):
        o = _terms(text)
        if o and len(t & o) / len(t) >= DUP_OVERLAP:
            return True
    return False

# A note is tied to its file's exact content only when it describes how that code behaves ("resolve_root maps a
# worktree to ..."): an edit may make it wrong, so an edit makes it stale. A how-to ("Run X as a module", "Validate
# the manifests with ...") or a note on a manifest, config or doc stays true across edits (plugin.json changes with
# every release), so it goes stale only when the file is gone.
CODE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs", ".c",
             ".cc", ".cpp", ".h", ".hpp", ".swift", ".scala", ".sh"}

_HOWTO = re.compile(r"(?i)^(?:(?:when|if|before|after|whenever|for)\b[^,]{0,120},\s*)?(?:always |never |do not |don't )?(?:run|use|call|start|stop|validate|check|keep|give|"
                    r"set|pass|add|avoid|prefer|install|build|test|lint|invoke|launch|open|read|write|put|make|"
                    r"create|delete|remove|rebuild|restart|pin|export|send|ask|wait|retry|commit|push|copy|treat)\b")

def pins_content(text: str, path: str) -> bool:
    """Whether a note on `path` goes stale when the file changes (see CODE_EXTS / _HOWTO)."""
    return os.path.splitext(path)[1].lower() in CODE_EXTS and not _HOWTO.match(text.strip())
