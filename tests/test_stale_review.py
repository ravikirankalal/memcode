"""Stale memories: the memory agent sees them (with the file as it is now), revives or retires them; the rest are
evicted after STALE_DAYS."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memcode import store, tree  # noqa: E402
from memcode.agent import conversation, curate, db, model  # noqa: E402


class StaleReview(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        Path(self.d, "orders.py").write_text("def total(items):\n    return sum(i.price for i in items)\n")
        self.con = store.connect(self.d)
        db.ensure(self.con)
        h = store.sha1(Path(self.d, "orders.py").read_bytes())
        self.mid = store.add_memory(self.con, "agent", "orders.total sums the item prices.", "orders.py", h, {},
                                    topic="component")
        Path(self.d, "orders.py").write_text("def total(items, tax):\n    return sum(i.price for i in items) * tax\n")
        tree.mark_stale(self.con, self.d)
        self.con.commit()

    def tearDown(self):
        self.con.close()

    def test_the_agent_sees_stale_memories_with_the_file_as_it_is_now(self):
        brief = model.briefing(self.con, self.d, "s")
        self.assertIn("Stale (the file each is about changed", brief)
        self.assertIn(f"- #{self.mid} component, ", brief)
        self.assertIn("orders.py now begins: def total(items, tax):", brief)
        self.assertIn(f"went stale (its file changed): #{self.mid}", conversation.delta(self.con, "s", 0, self.d))

    def test_an_update_revives_it_on_the_file_as_it_is_now(self):
        upd = {"op": "update", "target": self.mid, "text": "orders.total(items, tax) sums the item prices times tax.",
               "evidence": "def total(items, tax):"}                         # quoted from the file, not the log
        self.assertEqual(curate.change(self.con, "s", upd, "[agent] looked at orders", self.d), self.mid)
        r = self.con.execute("SELECT * FROM memories WHERE id=?", (self.mid,)).fetchone()
        self.assertEqual((r["stale"], r["text"]), (0, "orders.total(items, tax) sums the item prices times tax."))
        tree.mark_stale(self.con, self.d)
        self.assertEqual(self.con.execute("SELECT stale FROM memories WHERE id=?", (self.mid,)).fetchone()[0], 0)

    def test_a_retire_may_quote_the_file_and_made_up_evidence_is_refused(self):
        bad = {"op": "retire", "target": self.mid, "text": "no longer true", "evidence": "nothing like this anywhere"}
        self.assertIsNone(curate.change(self.con, "s", bad, "[agent] hi", self.d))
        ok = dict(bad, evidence="return sum(i.price for i in items) * tax")
        self.assertEqual(curate.change(self.con, "s", ok, "[agent] hi", self.d), self.mid)
        self.assertIsNone(self.con.execute("SELECT 1 FROM memories WHERE id=?", (self.mid,)).fetchone())

    def test_stale_too_long_is_evicted_and_logged(self):
        self.assertEqual(curate.evict_stale(self.con), 0)                     # just went stale: kept
        self.con.execute("UPDATE memories SET updated_at=? WHERE id=?", (time.time() - 15 * 86400, self.mid))
        self.assertEqual(curate.evict_stale(self.con), 1)
        self.assertIsNone(self.con.execute("SELECT 1 FROM memories WHERE id=?", (self.mid,)).fetchone())
        self.assertEqual(self.con.execute("SELECT op FROM memory_log").fetchall()[-1][0], "evict")


if __name__ == "__main__":
    unittest.main()
