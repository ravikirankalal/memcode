"""Proposed change to memcode's prompt capture (triggers.TriggerEngine._prompt), evaluated WITHOUT editing memcode/.

evaluate.py --proposal swaps `proposed_prompt` in for TriggerEngine._prompt. The same change as a patch against
memcode/triggers.py is bench/precision/proposal.diff (tests/test_precision_bench.py checks both give identical
captures on the corpus).

What it changes (each is aimed at a false-positive class measured on corpus.jsonl):
  1. Bug fix: the weak tier (agent acted since the last prompt) did not include _STRONG, so "Always keep functions
     short" after an edit was dropped while the same text after a text-only reply was captured. Weak tier now
     accepts _CORRECTION | _STATEMENT | _STRONG.
  2. "revert/undo that|this|it" removed from _CORRECTION: it names the current change, and a real revert is already
     captured (with the diff) by the revert trigger.
  3. A turn is NOT a rule when, outside a subordinate clause, no strong rule phrase (_STRONG / _STATEMENT) carries it
     and any of these hold:
       interpretation   it corrects the agent's reading of the request ("I meant", "I'm talking about", "not just X",
                        "the other one", "not what I asked", "you misunderstood", "wrong file")
       one-off          it is about now ("now", "yet", "for now", "right now", "this time", "today", "until",
                        "wait", "first", "for this", "in this PR", "just fix/commit ...")
       status           a status report or diagnosis ("still failing", "the bug is in", "is failing because")
       deictic          it points at the current change ("there", "back", "this function", "line 40", "you added")
       bare             nothing is left once the opener is removed ("No.", "That's wrong.", "Stop, wait.")
     and, regardless of rule phrases:
       question         every sentence is a question ("Should we always use async here?")
       subordinate      the rule phrase sits in a clause that describes the task ("add a hook so we never commit .env")
"""
from __future__ import annotations

import re

from memcode import triggers as T

# 2. _CORRECTION without the revert/undo alternatives (otherwise identical to memcode.triggers._CORRECTION)
CORRECTION = re.compile(
    r"(?i)^\s*(no[,.!:]|no\s*[-–—]|no\s+(?:don't|do not|that|use|not)\b|nope\b|don'?t\b(?!\s+forget)|do not\b|stop\s+\w+ing\b)"
    r"|\bthat'?s (?:wrong|not (?:right|correct|what))\b|\binstead,? use\b|\buse\b.{1,60}\binstead\b"
    r"|\byou (?:should not|shouldn'?t)\b"
    r"|\b(?:never|always)\s+(?:use|run|call|put|write|add|commit)\b|\bremember (?:that|this)\b|\bfrom now on\b")

INTERPRET = re.compile(
    r"(?i)\bI(?:'m|\s+am|\s+was)\s+(?:talking|asking|referring)\b|\bI\s+(?:meant|mean|asked|want|wanted)\b"
    r"|\bnot what I\b|\bmisunderst\w*|\bthe other (?:one|file|pr|branch|function|module|test)\b"
    r"|\bnot (?:just|only)\b|\bthe question (?:was|is)\b"
    r"|\bwrong (?:repo|file|function|method|branch|pr|one|place|folder|directory|variable|module)\b")
ONE_OFF = re.compile(
    r"(?i)\b(?:right now|for now|yet|this time|today|tonight|tomorrow|until|wait|for this|this one|in this pr"
    r"|just (?:fix|commit|do|answer|show|tell|leave|change))\b|(?<![.\w])now\b(?!\s+on\b|\()")
STATUS = re.compile(r"(?i)\bstill\b|\bthe (?:bug|problem|issue|error|failure) is\b|\b(?:is )?fail(?:s|ing)? because\b")
DEICTIC = re.compile(
    r"(?i)\bthere\b(?!\s*(?:is|are|was|were|'s)\b)|\b(?:it|that|this) back\b|\bback to\b"
    r"|\b(?:this|that) (?:function|method|file|line|loop|variable|test|case|change|one)\b|\bline \d+|\byou (?:just )?added\b")
COMPLAINT = re.compile(r"(?i)\bthat'?s (?:wrong|not (?:right|correct))(?: at all)?\b")
SUBORDINATE = re.compile(r"(?i)\b(?:that|so|so that|which|whether|ensures?|ensuring|checks?)\s+(?:we\s+|it\s+|you\s+|they\s+)?$")


def _phrases(rx, text):
    """Matches of rx that do not sit in a subordinate clause ("... a hook so we never commit .env")."""
    return [m for m in rx.finditer(text) if not SUBORDINATE.search(text[max(0, m.start() - 30):m.start()])]


def _all_questions(text: str) -> bool:
    sents = [s for s in re.split(r"(?<=[.!?])\s+|\n+", text.strip()) if s.strip()]
    return bool(sents) and all(s.rstrip().endswith("?") for s in sents)


def veto(text: str) -> str | None:
    """Why this turn is not a standing rule, or None."""
    t = " ".join(text.split())
    if _all_questions(t):
        return "question"
    if _phrases(T._STRONG, t) or _phrases(T._STATEMENT, t):
        return None                            # an explicit rule phrase wins over the soft vetoes below
    for name, rx in (("interpretation", INTERPRET), ("one-off", ONE_OFF), ("status", STATUS), ("deictic", DEICTIC)):
        if rx.search(t):
            return name
    rest = COMPLAINT.sub("", T._LEAD_ACK.sub("", t))
    rest = re.sub(r"(?i)^\s*(?:stop|nope|no)\b", "", rest)
    if len(re.findall(r"[A-Za-z0-9_./'`-]+", rest)) < 3:
        return "bare"
    return None


def is_rule_turn(text: str, weak: bool, acted_ever: bool) -> bool:
    if weak:
        ok = bool(_phrases(CORRECTION, text) or _phrases(T._STATEMENT, text) or _phrases(T._STRONG, text))
    else:
        ok = acted_ever and bool(_phrases(T._STRONG, text) or _phrases(T._STATEMENT, text))
    return ok and veto(text) is None


def proposed_prompt(self, event, sess, st, ev):
    """Drop-in replacement for TriggerEngine._prompt: same storage, new acceptance test."""
    text = T._s(event.get("text") or event.get("prompt"))
    had_edit, acted = st.edited_since_prompt, st.acted_since_prompt
    st.edited_since_prompt = st.acted_since_prompt = False
    if not is_rule_turn(text, had_edit or acted, st.acted_ever):
        return []
    if had_edit and st.edits:
        last = st.edits[-1]
        msg = f"Rule from user correction: {T._clip(T._imperative(text), 240)} (context: {last['path']})"
        return [self._write("correction", msg, "", sess, [last["ev"], ev], 0.7)]
    msg = f"Rule from user correction: {T._clip(T._imperative(text), 240)}"
    return [self._write("correction", msg, "", sess, [ev], 0.7)]
