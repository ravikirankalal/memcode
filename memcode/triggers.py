"""The five coding triggers. `TriggerEngine(con, repo_root).handle(event)` -> ids of memories written.

Event dicts: {kind: prompt|tool_use|tool_result, session, ...}
  prompt:      text (also accepts "prompt")
  tool_use:    tool, input {command | file_path, old_string, new_string, content}
  tool_result: tool, input, exit_code, output
Edits are detected from tool_use events (tool_result of an edit tool is only logged).
Commands are registered on tool_use; exit codes come from tool_result (Bash).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import time
from pathlib import Path

from . import store
from .redact import redact

EDIT_TOOLS = {"edit", "write", "multiedit", "notebookedit", "str_replace", "create"}
BASH_TOOLS = {"bash", "shell"}

_DEP_NAMES = re.compile(
    r"^(package\.json|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|pyproject\.toml|poetry\.lock|"
    r"uv\.lock|Pipfile|Pipfile\.lock|requirements[^/]*\.txt|Cargo\.toml|Cargo\.lock|go\.mod|go\.sum|"
    r"Gemfile|Gemfile\.lock|composer\.json|composer\.lock|setup\.cfg|tox\.ini|.*\.ya?ml)$", re.I)
_CORRECTION = re.compile(
    r"(?i)^\s*(no[,.!:]|no\s+(?:don't|do not|that|use|not)\b|nope\b|don'?t\b|do not\b|stop\b)"
    r"|\bthat'?s (?:wrong|not (?:right|correct|what))\b|\binstead,? use\b|\buse\b.{1,60}\binstead\b"
    r"|\brevert (?:that|this|it)\b|\bundo (?:that|this|it)\b|\byou (?:should not|shouldn'?t)\b")
_GIT_REVERT = re.compile(r"\bgit\s+(?:checkout|restore|revert|reset\s+--hard)\b")
_TRIVIAL = {"ls", "cd", "cat", "echo", "pwd", "head", "tail", "which", "clear", "git status",
            "git diff", "git log", "git show"}


def _s(v) -> str:
    return v if isinstance(v, str) else ("" if v is None else str(v))


def _clip(t: str, n: int = 300) -> str:
    t = " ".join(t.split())
    return t if len(t) <= n else t[:n] + "..."


def _scrub(o):
    if isinstance(o, str):
        return redact(o)
    if isinstance(o, dict):
        return {k: _scrub(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_scrub(v) for v in o]
    return o


def _cmd_key(cmd: str) -> str:
    """Command with flags stripped, used to group 'the same command with different flags'."""
    try:
        toks = shlex.split(cmd)
    except ValueError:
        toks = cmd.split()
    return " ".join(t for t in toks if not t.startswith("-"))


class _Session:
    def __init__(self):
        self.edits = []            # dicts: path, old, new, ev
        self.edited_since_prompt = False
        self.failing = {}          # cmd -> {"ev": id, "n_edits": int, "output": str}
        self.variants = {}         # cmd_key -> list of distinct raw commands
        self.retry_fired = set()
        self.cmd_ev = {}           # cmd -> last tool_use event id


class TriggerEngine:
    def __init__(self, con, repo_root):
        self.con = con
        self.root = Path(repo_root).resolve()
        self._replay = False

    # ---- helpers
    def _rel(self, p: str):
        if not p:
            return None
        pp = Path(p)
        if not pp.is_absolute():
            pp = self.root / pp
        try:
            return os.path.normpath(pp.resolve().relative_to(self.root)).replace(os.sep, "/")
        except ValueError:
            return None

    def _anchor(self, rel):
        """-> (anchor_path, anchor_hash). Registers existing files in `paths`."""
        if not rel:
            return "", None
        f = self.root / rel
        if f.is_file():
            h = store.sha1(f.read_bytes())
            store.upsert_path(self.con, rel, "file", content_hash=h)
            return rel, h
        return rel, None

    def _write(self, trig, text, rel, sess, events, conf=0.6):
        a, h = self._anchor(rel)
        prov = {"session": sess, "event_ids": [e for e in events if e], "ts": time.time()}
        if self._replay:
            return None
        return store.add_memory(self.con, trig, redact(text), a, h, prov, conf)

    # ---- entry point
    def handle(self, event: dict, history: int = 200) -> list[int]:
        """Stateless across instances: per-session state is rebuilt from the events table."""
        sess = _s(event.get("session")) or "default"
        clean = _scrub(event)
        rows = self.con.execute(
            "SELECT id, payload FROM events WHERE session=? ORDER BY id DESC LIMIT ?",
            (sess, history)).fetchall()
        st = _Session()
        self._replay = True
        try:
            for r in reversed(rows):
                try:
                    prev = json.loads(r["payload"])
                except ValueError:
                    continue
                self._dispatch(prev, sess, st, r["id"])
        finally:
            self._replay = False
        ev = store.log_event(self.con, sess, _s(clean.get("kind")), clean)
        return [i for i in self._dispatch(clean, sess, st, ev) if i is not None]

    def _dispatch(self, event, sess, st, ev):
        kind = event.get("kind")
        tool = _s(event.get("tool")).lower()
        inp = event.get("input") or {}
        if not isinstance(inp, dict):
            inp = {"command": _s(inp)}
        out: list = []
        if kind == "prompt":
            out += self._prompt(event, sess, st, ev)
        elif kind == "tool_use":
            if tool in EDIT_TOOLS or inp.get("file_path") and tool not in BASH_TOOLS:
                out += self._edit(inp, sess, st, ev)
            elif tool in BASH_TOOLS:
                out += self._bash_use(_s(inp.get("command")), sess, st, ev)
        elif kind == "tool_result":
            if tool in BASH_TOOLS:
                out += self._bash_result(_s(inp.get("command")), event, sess, st, ev)
        return out

    # ---- (a) correction
    def _prompt(self, event, sess, st, ev):
        text = _s(event.get("text") or event.get("prompt"))
        had_edit = st.edited_since_prompt
        st.edited_since_prompt = False
        if not (had_edit and st.edits and _CORRECTION.search(text)):
            return []
        last = st.edits[-1]
        msg = (f"User corrected the agent's edit to {last['path']}: \"{_clip(text)}\". "
               f"Avoid repeating the corrected approach.")
        return [self._write("correction", msg, last["path"], sess, [last["ev"], ev], 0.7)]

    # ---- (b)/(e) edits
    def _edit(self, inp, sess, st, ev):
        rel = self._rel(_s(inp.get("file_path") or inp.get("path")))
        if rel is None:
            return []
        old, new = _s(inp.get("old_string")), _s(inp.get("new_string") or inp.get("content"))
        out = []
        # revert: this edit exactly undoes an earlier agent edit to the same file
        if old and new:
            for prev in reversed(st.edits):
                if prev["path"] == rel and prev["old"] and prev["new"] \
                        and old == prev["new"] and new == prev["old"]:
                    out.append(self._write(
                        "revert", f"Agent edit to {rel} was undone by a later edit (changed "
                        f"\"{_clip(prev['old'], 120)}\" -> \"{_clip(prev['new'], 120)}\" and back). "
                        f"That change was wrong or unwanted.", rel, sess, [prev["ev"], ev], 0.65))
                    break
        st.edits.append({"path": rel, "old": old, "new": new, "ev": ev})
        st.edited_since_prompt = True
        for f in st.failing.values():
            f["files"].append(rel)
        if _DEP_NAMES.match(os.path.basename(rel)):
            detail = _clip(new, 200) if new else "file rewritten"
            out.append(self._write("dep_change", f"Dependency/config file {rel} was changed: {detail}",
                                   rel, sess, [ev], 0.5))
        return out

    # ---- commands
    def _bash_use(self, cmd, sess, st, ev):
        cmd = cmd.strip()
        if not cmd:
            return []
        st.cmd_ev[cmd] = ev
        out = []
        for seg in (x.strip() for x in re.split(r"&&|\|\||;|\|", cmd)):
            if _GIT_REVERT.search(seg) and st.edits:
                files = [r for r in (self._rel(t) for t in self._tokens(seg))
                         if r and any(e["path"] == r for e in st.edits)]
                if files:
                    for rel in dict.fromkeys(files):
                        e = [x for x in st.edits if x["path"] == rel][-1]
                        out.append(self._write("revert", f"Agent edits to {rel} were reverted via `{_clip(seg, 120)}`.",
                                               rel, sess, [e["ev"], ev], 0.7))
                elif not re.search(r"\b(checkout|restore)\b", seg) or "." in self._tokens(seg):
                    last = st.edits[-1]
                    out.append(self._write("revert", f"Agent edits were reverted via `{_clip(seg, 120)}` "
                                           f"(last edited {last['path']}).", last["path"], sess,
                                           [last["ev"], ev], 0.6))
        if cmd in _TRIVIAL or any(cmd.startswith(t + " ") for t in _TRIVIAL):
            return out
        key = _cmd_key(cmd)
        if not key:
            return out
        vs = st.variants.setdefault(key, [])
        if cmd not in vs:
            vs.append(cmd)
        if len(vs) >= 2 and key not in st.retry_fired:
            st.retry_fired.add(key)
            out.append(self._write("retry", f"Command `{_clip(key, 100)}` needed multiple attempts with "
                                   f"different flags/fixes: " + "; ".join(f"`{_clip(v, 100)}`" for v in vs[:4]),
                                   "", sess, [st.cmd_ev.get(v) for v in vs[:2]], 0.5))
        return out

    @staticmethod
    def _tokens(cmd):
        try:
            return shlex.split(cmd)[1:]
        except ValueError:
            return cmd.split()[1:]

    def _bash_result(self, cmd, event, sess, st, ev):
        cmd = cmd.strip()
        code = event.get("exit_code")
        if not cmd or code is None:
            return []
        if code != 0:
            st.failing[cmd] = {"ev": ev, "files": [], "output": _s(event.get("output"))}
            return []
        f = st.failing.pop(cmd, None)
        if not f or not f["files"]:
            return []
        files = list(dict.fromkeys(f["files"]))
        anchor = files[-1]
        msg = (f"`{_clip(cmd, 100)}` failed ({_clip(f['output'], 160)}) and passed after editing "
               f"{', '.join(files[:5])}. Fix was in {anchor}.")
        return [self._write("fail_to_fix", msg, anchor, sess, [f["ev"], ev], 0.7)]
