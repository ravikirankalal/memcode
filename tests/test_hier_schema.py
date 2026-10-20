import sqlite3
import tempfile
import unittest

from memcode import store


class Schema(unittest.TestCase):
    def test_columns_defaults_and_old_style_reads(self):
        d = tempfile.mkdtemp()
        con = store.connect(d)
        mid = store.add_memory(con, "fail_to_fix", "note", "a.py", None, {})
        r = con.execute("SELECT * FROM memories WHERE id=?", (mid,)).fetchone()
        self.assertEqual((r["scope_path"], r["scope_kind"], r["parent_id"], r["level"], r["labels"],
                          r["evidence_count"]), ("", "repo", None, 0, "", 1))
        con.close()
        raw = sqlite3.connect(store.db_path(d))            # an older plugin version reading the migrated DB
        self.assertEqual(len(raw.execute("SELECT id, trigger, text, anchor_path FROM memories").fetchall()), 1)
        raw.close()
        store.connect(d).close()                            # migration is idempotent

    def test_scope_chain(self):
        self.assertEqual(store.scope_chain("billing/api/x.py"), ["billing/api/x.py", "billing/api", "billing", ""])
        self.assertEqual(store.scope_chain(""), [""])
        self.assertEqual(store.scope_chain("/a/"), ["a", ""])


class FlatModel(unittest.TestCase):
    def test_old_rows_migrate_to_the_flat_fields(self):
        import json
        d = tempfile.mkdtemp()
        con = store.connect(d)
        rule = store.add_memory(con, "correction", "Rule from user correction: Always use tabs.", "", None, {})
        note = store.add_memory(con, "transcript", "OrderService is central.", "", None,
                                {"category": "component", "importance": 4}, from_user=False)
        dec = store.add_memory(con, "decision", "G16 is parked.", "", None, {}, from_user=False)
        manual = store.add_memory(con, "manual", "deploys need VPN", "", None, {})
        con.execute("UPDATE memories SET from_user=0, topic='', importance=3, expires_at=NULL")   # as before 0.15
        con.commit(); con.close()
        con = store.connect(d)                                                # the upgrade migrates them
        r = {x["id"]: x for x in con.execute("SELECT * FROM memories")}
        self.assertEqual((r[rule]["from_user"], r[rule]["text"]), (1, "Always use tabs."))   # plain text, no prefix
        self.assertEqual((r[rule]["trigger"], r[note]["trigger"], r[dec]["trigger"]), ("correction", "agent", "agent"))
        self.assertEqual((r[note]["from_user"], r[note]["topic"], r[note]["importance"]), (0, "component", 4))
        self.assertEqual(r[dec]["topic"], "decision")
        self.assertAlmostEqual(r[dec]["expires_at"] - r[dec]["updated_at"], 30 * 86400, delta=1)
        self.assertEqual(r[manual]["from_user"], 0)                          # a manual add is information, not an order
        con.execute("INSERT INTO memory_links(src, dst, kind, source, ts) VALUES(?,?,?,?,0)", (rule, note, "related", "auto"))
        store.delete_ids(con, [rule]); con.commit()
        self.assertEqual(con.execute("SELECT COUNT(*) FROM memory_links").fetchone()[0], 0)
        con.close()


if __name__ == "__main__":
    unittest.main()
