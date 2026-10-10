import os
import tempfile
import time
import unittest
from unittest import mock

from memcode import retrieval, store

DAY = 86400.0


class Split(unittest.TestCase):
    """MEMCODE_RANK=split: the relevance top-k is untouched; costly memories outside it get extra slots."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.con = store.connect(self.root)
        now = time.time()
        self.ids = []
        for i in range(8):                       # id order = oldest first; all equally relevant
            mid = store.add_memory(self.con, "correction", f"Rule from user correction: rule {i} for billing/ modules.",
                                   "", None, {})
            ts = now - (40 - i) * DAY
            self.con.execute("UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (ts, ts, mid))
            self.ids.append(mid)
        self.con.commit()
        self.scored = [(1.0, dict(r)) for r in self.con.execute("SELECT * FROM memories ORDER BY updated_at DESC")]

    def tearDown(self):
        self.con.close()

    def restate(self, mid, *ages):
        for j, a in enumerate(ages):
            self.con.execute("INSERT INTO outcomes VALUES(?,?,?,?)", (f"h{mid}-{j}", mid, "failure:repeated",
                                                                     time.time() - a * DAY))
        self.con.commit()

    def chosen(self, rank):
        with mock.patch.dict(os.environ, {"MEMCODE_RANK": rank} if rank else {}):
            os.environ.pop("MEMCODE_RANK", None) if not rank else None
            return [r["id"] for _, r in retrieval.select(self.con, self.scored)]

    def test_default_is_plain_top_k(self):
        self.restate(self.ids[0], 10, 3)
        self.assertEqual(self.chosen(None), [r["id"] for _, r in self.scored[:retrieval.TOP_K]])

    def test_restated_rule_outside_top_k_is_promoted_without_displacing(self):
        self.restate(self.ids[0], 10, 3)
        got = self.chosen("split")
        self.assertEqual(got[:retrieval.TOP_K], [r["id"] for _, r in self.scored[:retrieval.TOP_K]])
        self.assertEqual(got[retrieval.TOP_K:], [self.ids[0]])

    def test_weak_evidence_is_not_promoted(self):
        self.restate(self.ids[0], 30)            # one old restatement: decayed weight ~0.23 < PROMOTE_MIN
        self.assertEqual(len(self.chosen("split")), retrieval.TOP_K)

    def test_at_most_promote_k(self):
        for mid in self.ids[:3]:
            self.restate(mid, 8, 2)
        self.assertEqual(len(self.chosen("split")), retrieval.TOP_K + retrieval.PROMOTE_K)

    def test_render_shows_promoted_rule(self):
        self.restate(self.ids[0], 10, 3)
        with mock.patch.dict(os.environ, {"MEMCODE_RANK": "split"}):
            text, ids = retrieval.render(self.scored, self.con)
        self.assertIn(self.ids[0], ids)
        self.assertIn("rule 0 for billing/", text)
        with mock.patch.dict(os.environ, {"MEMCODE_RANK": "split"}):
            _, ids = retrieval.render(self.scored)        # no connection: no promotions
        self.assertNotIn(self.ids[0], ids)


if __name__ == "__main__":
    unittest.main()
