"""The fast paths added for runtime performance must give exactly what the slow, obvious versions give."""
import random
import re
import tempfile
import time
import unittest

from memcode import pinned, salience, store

DAY = 86400.0


def random_store(seed):
    rnd = random.Random(seed)
    d = tempfile.mkdtemp()
    con = store.connect(d)
    dirs = ["", "a", "a/b", "a/b/c", "x", "x/y"]
    for p in dirs[1:]:
        store.upsert_path(con, p, "dir", commit=False)
    files = [f"{rnd.choice(dirs)}/f{i}.py".lstrip("/") for i in range(12)]
    for f in files:
        store.upsert_path(con, f, "file", commit=False)
    now = time.time()
    for i in range(160):
        trig = rnd.choice(["revert", "fail_to_fix", "fail_to_fix", "retry", "correction", "dep_change", "manual"])
        anchor = rnd.choice(files + dirs + ["missing/z.py", ""])
        sym = rnd.choice([None, None, "f", "g", "C.m"])
        mid = store.add_memory(con, trig, f"m{i} [REDACTED] tail", anchor, None, {}, rnd.random(), commit=False,
                               anchor_symbol=sym)
        ts = now - rnd.uniform(0, 60) * DAY
        con.execute("UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (ts, ts, mid))
        for j in range(rnd.choice([0, 0, 1, 3])):
            con.execute("INSERT INTO outcomes VALUES(?,?,?,?)", (f"s{i}-{j}", mid,
                        rnd.choice(["failure:repeated", "success:verified", "failure:other"]), now - rnd.uniform(0, 30) * DAY))
    con.commit()
    return con, now


class Equivalence(unittest.TestCase):
    def test_index_evidence_matches_row_by_row(self):
        for seed in range(6):
            con, now = random_store(seed)
            idx = salience.Index(con, now)
            for m in con.execute("SELECT * FROM memories"):
                slow, fast = salience.evidence(con, m, now), idx.evidence(m)
                for k in slow:
                    self.assertAlmostEqual(slow[k], fast[k], places=9, msg=(seed, m["id"], k))
                self.assertAlmostEqual(salience.score(con, m, now), salience.score(con, m, index=idx), places=9)
            con.close()

    def test_shown_ids_matches(self):
        for seed in range(4):
            con, _ = random_store(seed)
            text = pinned.render_pinned(con, None, token_cap=4000)
            shown = pinned.shown_ids(con, text)
            listed = [l for l in text.splitlines() if l.startswith("- ")]     # every rule and memory line, dated
            self.assertEqual(len(shown), len(listed))
            self.assertTrue(all(re.search(r"\d{4}-\d\d-\d\d", l) for l in listed))
            con.close()


class VectorCache(unittest.TestCase):
    def test_cached_scores_equal_fresh_scores_and_edits_refresh(self):
        from memcode import retrieval
        d = tempfile.mkdtemp()
        con = store.connect(d)
        a = store.add_memory(con, "correction", "invoices under billing/ round half up.",
                             "", None, {})
        store.add_memory(con, "fail_to_fix", "parse_items broke the totals until cents were integers",
                         "billing/invoice.py", None, {})
        q = "how do billing invoices round totals in billing/invoice.py"
        first = [(round(s, 9), r["id"]) for s, r in retrieval.score(con, d, "s1", q)]
        self.assertEqual(con.execute("SELECT COUNT(*) FROM memory_vectors").fetchone()[0], 2)   # vectors stored
        second = [(round(s, 9), r["id"]) for s, r in retrieval.score(con, d, "s2", q)]
        self.assertEqual(first, second)
        con.execute("UPDATE memories SET text=? WHERE id=?", ("shipping labels are A6.", a))
        con.commit()
        ids = [r["id"] for _, r in retrieval.score(con, d, "s3", "print shipping labels")]
        self.assertNotIn(a, [r["id"] for _, r in retrieval.score(con, d, "s4", q)])
        self.assertEqual(ids[:1], [a])
        con.close()


if __name__ == "__main__":
    unittest.main()
