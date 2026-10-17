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
    """Frozen: what the current prompt triggers capture."""

    @classmethod
    def setUpClass(cls):
        cls.res = E.capture(E.load(PRECISION / "corpus.jsonl"))
        cls.s = E.summarize(cls.res)

    def test_frozen_counts(self):
        o = self.s["overall"]
        self.assertEqual((o["tp"], o["fp"], o["fn"]), (39, 49, 26))

    def test_dogfooding_false_positive_reproduces(self):
        r = next(r for r in self.res if r["text"].startswith("No, not just heirarchical memory"))
        self.assertTrue(r["captured"])
        self.assertTrue(r["stored"].startswith("Rule from user correction: Not just heirarchical memory"))

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

    @unittest.skipUnless(shutil.which("patch"), "needs patch(1)")
    def test_diff_matches_monkeypatch(self):
        """proposal.diff applied to a copy of memcode/ captures exactly what proposal.py does."""
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(ROOT / "memcode", Path(tmp) / "memcode",
                            ignore=shutil.ignore_patterns("__pycache__"))
            subprocess.run(["patch", "-s", "-p1", "-d", tmp, "-i", str(PRECISION / "proposal.diff")], check=True)
            for name in SETS:
                out = Path(tmp) / f"{name}.json"
                subprocess.run([sys.executable, str(PRECISION / "evaluate.py"), "--corpus", str(PRECISION / name),
                                "--json", str(out)], check=True, capture_output=True,
                               env=dict(os.environ, PRECISION_MEMCODE_SRC=tmp))
                patched = [i["captured"] for i in json.loads(out.read_text())["items"]]
                mp = [i["captured"] for i in E.capture(E.load(PRECISION / name), proposal=True)]
                self.assertEqual(patched, mp, name)


if __name__ == "__main__":
    unittest.main()
