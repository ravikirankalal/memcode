import io
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

from memcode import cli, pinned, salience, store

DAY = 86400.0


class Evidence(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.con = store.connect(self.root)
        store.upsert_path(self.con, "billing", "dir")
        store.upsert_path(self.con, "billing/x.py", "file")

    def tearDown(self):
        self.con.close()

    def add(self, trigger, anchor="billing/x.py", age_days=0.0, confidence=0.5, symbol=None):
        mid = store.add_memory(self.con, trigger, f"{trigger} note", anchor, None, {},
                               confidence=confidence, anchor_symbol=symbol)
        ts = time.time() - age_days * DAY
        self.con.execute("UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (ts, ts, mid))
        self.con.commit()
        return mid

    def row(self, mid):
        return self.con.execute("SELECT * FROM memories WHERE id=?", (mid,)).fetchone()

    def test_recurrences_raise_surprise(self):
        m = self.add("retry")
        before = salience.compute(self.con, self.row(m))["surprise"]
        self.add("fail_to_fix"); self.add("fail_to_fix")
        after = salience.compute(self.con, self.row(m))["surprise"]
        self.assertGreater(after, before)

    def test_recurrence_respects_symbol(self):
        m = self.add("retry", symbol="f")
        self.add("fail_to_fix", symbol="g")
        self.assertEqual(salience.evidence(self.con, self.row(m))["recurrences"], 0.0)
        self.add("fail_to_fix", symbol="f")
        self.assertGreater(salience.evidence(self.con, self.row(m))["recurrences"], 0.9)

    def test_repeated_corrections_raise_friction(self):
        m = self.add("dep_change")
        before = salience.compute(self.con, self.row(m))["friction"]
        for s in ("s1", "s2", "s3"):
            self.con.execute("INSERT INTO outcomes VALUES(?,?,?,?)", (s, m, "failure:repeated", time.time()))
        self.con.commit()
        after = salience.compute(self.con, self.row(m))["friction"]
        self.assertGreater(after, before)
        self.assertEqual(salience.evidence(self.con, self.row(m))["verified_bad"], 3)

    def test_reverts_under_folder_raise_fragility(self):
        m = self.add("dep_change", anchor="billing/x.py")
        self.assertEqual(salience.compute(self.con, self.row(m))["fragility"], 0.0)
        self.add("revert", anchor="billing")
        self.add("revert", anchor="other/y.py")           # outside the folder: ignored
        ev = salience.evidence(self.con, self.row(m))
        self.assertAlmostEqual(ev["reverts"], 1.0, places=3)
        self.assertGreater(salience.compute(self.con, self.row(m))["fragility"], 0.5)

    def test_repo_wide_memory_has_no_fragility(self):
        m = self.add("correction", anchor="")
        self.add("revert"); self.add("fail_to_fix")
        self.assertEqual(salience.compute(self.con, self.row(m))["fragility"], 0.0)

    def test_old_evidence_decays(self):
        m = self.add("dep_change")
        r = self.add("revert", age_days=28)              # two half-lives
        self.assertAlmostEqual(salience.evidence(self.con, self.row(m))["reverts"], 0.25, places=2)
        old = self.add("fail_to_fix", anchor="z.py", age_days=28)
        new = self.add("fail_to_fix", anchor="z.py")
        self.assertLess(salience.compute(self.con, self.row(old))["surprise"],
                        salience.compute(self.con, self.row(new))["surprise"])
        self.assertTrue(r)

    def test_cap(self):
        m = self.add("fail_to_fix", confidence=1.0)
        for _ in range(10):
            self.add("fail_to_fix"); self.add("revert")
        for i in range(10):
            self.con.execute("INSERT INTO outcomes VALUES(?,?,?,?)", (f"s{i}", m, "failure:repeated", time.time()))
        self.con.commit()
        dims = salience.compute(self.con, self.row(m))
        self.assertTrue(all(v <= salience.CAP for v in dims.values()), dims)
        self.assertLessEqual(salience.score(self.con, self.row(m)), salience.CAP)

    def test_retrieval_count_is_not_an_input(self):
        m = self.add("retry")
        now = time.time()
        before = salience.score(self.con, self.row(m), now)
        for _ in range(20):
            self.con.execute("INSERT INTO retrievals(session,memory_id,ts) VALUES('s',?,?)", (m, time.time()))
        self.con.commit()
        self.assertEqual(salience.score(self.con, self.row(m), now), before)

    def test_explain_names_the_evidence(self):
        m = self.add("retry")
        self.add("fail_to_fix"); self.add("revert", anchor="billing")
        text = salience.explain(self.con, self.row(m))
        self.assertIn("recorded from a retry", text)
        self.assertIn("recurred", text)
        self.assertIn("under billing", text)


class Ordering(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.con = store.connect(self.root)
        self.low = store.add_memory(self.con, "dep_change", "low note", "", None, {})
        time.sleep(0.01)
        self.high = store.add_memory(self.con, "fail_to_fix", "high note", "", None, {})
        time.sleep(0.01)
        self.newest = store.add_memory(self.con, "dep_change", "newest low note", "", None, {})

    def tearDown(self):
        self.con.close()

    def ids(self):
        return [r["id"] for r in pinned._memory_rows(self.con, convention=False)]

    def test_default_order_is_unchanged(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MEMCODE_RANK", None)
            self.assertEqual(self.ids(), [r["id"] for r in pinned._memory_rows_base(self.con, False)])

    def test_flag_orders_by_score(self):
        with mock.patch.dict(os.environ, {"MEMCODE_RANK": "salience"}):
            ids = self.ids()
        self.assertEqual(ids[0], self.high)
        self.assertEqual(ids[1:], [self.newest, self.low])   # tie broken by recency

    def test_rules_keep_chronological_order(self):
        a = store.add_memory(self.con, "correction", "Rule from user correction: A.", "", None, {})
        b = store.add_memory(self.con, "correction", "Rule from user correction: B.", "", None, {})
        os.environ.pop("MEMCODE_RANK", None)
        base = [r["id"] for r in pinned._memory_rows(self.con, convention=True)]
        with mock.patch.dict(os.environ, {"MEMCODE_RANK": "salience"}):
            flagged = [r["id"] for r in pinned._memory_rows(self.con, convention=True)]
        self.assertEqual(base, flagged)
        self.assertEqual(set(flagged), {a, b})


class MapZoom(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.con = store.connect(self.root)
        for d in ("billing", "billing/core", "web"):
            store.upsert_path(self.con, d, "dir")
        for f in ("billing/core/a.py", "billing/core/b.py", "web/v.py"):
            store.upsert_path(self.con, f, "file")
        os.environ.pop("MEMCODE_RANK", None)

    def tearDown(self):
        self.con.close()

    def lines(self, rank):
        env = {"MEMCODE_RANK": "salience"} if rank else {}
        with mock.patch.dict(os.environ, env):
            return [t for t, _ in pinned._tree_lines(self.con)]

    def test_off_by_default_and_no_tags_without_evidence(self):
        self.assertEqual(self.lines(False), ["billing/ (2 files)", "web/ (1 files)"])
        self.assertEqual(self.lines(True), self.lines(False))

    def test_revert_expands_and_tags_only_the_most_specific_path(self):
        store.add_memory(self.con, "revert", "reverted", "billing/core/a.py", None, {})
        off, on = self.lines(False), self.lines(True)
        self.assertNotIn("fragile", "\n".join(off))
        self.assertEqual([t.replace(" [fragile: recent reverts/failures]", "") for t in on], off)
        tagged = [t.strip() for t in on if "fragile" in t]
        self.assertEqual(tagged, ["a.py [fragile: recent reverts/failures]"])   # ancestors expand, untagged

    def test_folder_with_repeated_trouble_is_tagged(self):
        for f in ("billing/core/a.py", "billing/core/a.py", "billing/core/b.py"):
            store.add_memory(self.con, "revert", "reverted", f, None, {})
        tagged = [t.strip() for t in self.lines(True) if "fragile" in t]
        self.assertTrue(tagged and tagged[0].startswith("core/"), tagged)
        self.assertFalse(any(t.startswith("billing/") for t in tagged))

    def test_stale_and_old_evidence_do_not_zoom(self):
        m = store.add_memory(self.con, "revert", "reverted", "web/v.py", None, {})
        self.con.execute("UPDATE memories SET created_at=? WHERE id=?", (time.time() - 120 * DAY, m))
        self.con.commit()
        self.assertFalse(any("fragile" in t for t in self.lines(True)))


class Why(unittest.TestCase):
    def test_why_prints_score_and_reasons(self):
        root = tempfile.mkdtemp()
        con = store.connect(root)
        m = store.add_memory(con, "fail_to_fix", "pytest failed then passed", "a.py", None, {})
        con.close()
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.main(["--root", root, "why", str(m)]), 0)
        text = out.getvalue()
        self.assertIn(f"#{m} salience", text)
        for k in ("surprise", "friction", "fragility", "confidence", "fail-to-fix"):
            self.assertIn(k, text)

    def test_why_unknown_id(self):
        root = tempfile.mkdtemp()
        with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(cli.main(["--root", root, "why", "999"]), 1)


if __name__ == "__main__":
    unittest.main()
