"""bench/precision: corpus integrity, the capture numbers it reports, and that proposal.diff == proposal.py.

Deterministic, no model calls. The frozen numbers below are what the CURRENT triggers do on the corpus; if a change
to memcode/triggers.py moves them, update them on purpose and re-run bench/precision/evaluate.py for the report.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bench.precision import evaluate as E  # noqa: E402
from bench.precision import proposal as P  # noqa: E402

PRECISION = ROOT / "bench" / "precision"
SETS = ("corpus.jsonl", "heldout.jsonl", "heldout2.jsonl")


class CorpusIntegrity(unittest.TestCase):
    def test_rows_are_well_formed(self):
        for name in SETS:
            rows = E.load(PRECISION / name)
            self.assertTrue(rows, name)
            seen = set()
            for r in rows:
                self.assertIn(r["prior_agent_action"], ("none", "text_only", "tool", "edit"), r)
                self.assertIn(r["label"], ("rule", "not_rule"), r)
                self.assertIn(r["scope"], ("repo", "dir", "file", "none"), r)
                self.assertEqual(r["scope"] == "none", r["label"] == "not_rule", r)
                key = " ".join(r["text"].split()).lower()
                self.assertNotIn(key, seen, r)
                seen.add(key)

    def test_corpus_size_and_sources(self):
        rows = E.load(PRECISION / "corpus.jsonl")
        self.assertGreaterEqual(len(rows), 150)
        self.assertGreaterEqual(sum(r["source"] == "real" for r in rows), 60)
        self.assertTrue(any(r["text"].startswith("No, not just heirarchical memory") for r in rows))


class CurrentCapture(unittest.TestCase):
    """Frozen: what the prompt triggers capture now that proposal.diff has landed in memcode/triggers.py.
    Before it landed (commit 5b84354 and earlier) the corpus gave tp/fp/fn = 39/49/26 and the dogfooding turn
    "No, not just heirarchical memory ..." was stored as a rule."""

    @classmethod
    def setUpClass(cls):
        cls.res = E.capture(E.load(PRECISION / "corpus.jsonl"))
        cls.s = E.summarize(cls.res)

    def test_frozen_counts(self):
        o = self.s["overall"]
        self.assertEqual((o["tp"], o["fp"], o["fn"]), (39, 5, 26))

    def test_dogfooding_false_positive_fixed(self):
        r = next(r for r in self.res if r["text"].startswith("No, not just heirarchical memory"))
        self.assertFalse(r["captured"])

    def test_harness_turns_never_captured(self):
        self.assertFalse(any(r["captured"] for r in self.res if r["category"] == "harness"))

    def test_first_turn_never_captured(self):
        self.assertFalse(any(r["captured"] for r in self.res if r["prior_agent_action"] == "none"))


class Proposal(unittest.TestCase):
    def test_proposal_numbers(self):
        want = {"corpus.jsonl": (39, 5, 26), "heldout.jsonl": (14, 2, 17), "heldout2.jsonl": (17, 1, 15)}
        for name, (tp, fp, fn) in want.items():
            o = E.summarize(E.capture(E.load(PRECISION / name), proposal=True))["overall"]
            self.assertEqual((o["tp"], o["fp"], o["fn"]), (tp, fp, fn), name)

    def test_veto_reasons(self):
        self.assertEqual(P.veto("No, not just heirarchical memory, i am talking about the memcode whole project."),
                         "interpretation")
        self.assertEqual(P.veto("Don't push yet."), "one-off")
        self.assertEqual(P.veto("Should we always use async here?"), "question")
        self.assertEqual(P.veto("That's wrong."), "bare")
        self.assertIsNone(P.veto("No, use pathlib instead of os.path."))
        self.assertIsNone(P.veto("nope, our dates go through utils.time helpers, never raw datetime.now()"))
        # an explicit rule phrase beats the soft vetoes in a mixed message
        self.assertIsNone(P.veto("No, I meant the payments module. And remember that we never log card numbers."))

    def test_landed_code_matches_proposal(self):
        """memcode/triggers.py (with proposal.diff landed) captures exactly what proposal.py describes."""
        for name in SETS:
            landed = [i["captured"] for i in E.capture(E.load(PRECISION / name))]
            mp = [i["captured"] for i in E.capture(E.load(PRECISION / name), proposal=True)]
            self.assertEqual(landed, mp, name)

if __name__ == "__main__":
    unittest.main()
