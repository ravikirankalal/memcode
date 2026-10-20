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


if __name__ == "__main__":
    unittest.main()
