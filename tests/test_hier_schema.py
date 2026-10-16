import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from memcode import maintenance, pinned, retrieval, store


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


class Injectable(unittest.TestCase):
    def test_children_hidden_only_with_consolidation_flag(self):
        d = tempfile.mkdtemp()
        con = store.connect(d)
        lesson = store.add_memory(con, "lesson", "3 similar retry notes", "", None, {})
        child = store.add_memory(con, "retry", "Command `make x` needed multiple attempts", "", None, {})
        con.execute("UPDATE memories SET parent_id=? WHERE id=?", (lesson, child)); con.commit()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MEMCODE_CONSOLIDATE", None)
            self.assertEqual(store.injectable_sql(), "")
            self.assertIn(child, [r["id"] for r in pinned._memory_rows_base(con, False)])
        with mock.patch.dict(os.environ, {"MEMCODE_CONSOLIDATE": "1"}):
            ids = [r["id"] for r in pinned._memory_rows_base(con, False)]
            self.assertIn(lesson, ids); self.assertNotIn(child, ids)
            scored = [r["id"] for _, r in retrieval.score(con, d, "s", "make x needed multiple attempts retry")]
            self.assertNotIn(child, scored)
        con.close()


class Maintenance(unittest.TestCase):
    def test_missing_modules_are_skipped(self):
        d = tempfile.mkdtemp()
        con = store.connect(d)
        self.assertIsInstance(maintenance.run(con, d), dict)
        con.close()


if __name__ == "__main__":
    unittest.main()
