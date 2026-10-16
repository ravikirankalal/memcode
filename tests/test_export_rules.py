import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from memcode import export_rules as er
from memcode import store


class Block(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, "AGENTS.md")

    def test_append_replace_remove_keep_user_text(self):
        Path(self.p).write_text("# Team notes\n\nUse uv.\n")
        self.assertTrue(er.write_block(self.p, "rule one"))
        t = Path(self.p).read_text()
        self.assertTrue(t.startswith("# Team notes\n\nUse uv.\n\n" + er.START))
        self.assertIn("rule one", t)
        self.assertTrue(er.write_block(self.p, "rule two"))
        t = Path(self.p).read_text()
        self.assertNotIn("rule one", t); self.assertIn("rule two", t)
        self.assertEqual(t.count(er.START), 1)
        self.assertFalse(er.write_block(self.p, "rule two"))         # unchanged -> no write
        self.assertTrue(er.write_block(self.p, ""))                 # empty store removes the block
        self.assertEqual(Path(self.p).read_text(), "# Team notes\n\nUse uv.\n\n")

    def test_text_after_block_survives(self):
        Path(self.p).write_text(f"intro\n\n{er.START}\nold\n{er.END}\n\noutro\n")
        er.write_block(self.p, "new")
        t = Path(self.p).read_text()
        self.assertTrue(t.startswith("intro\n\n")); self.assertTrue(t.endswith("outro\n")); self.assertIn("new", t)

    def test_file_created_and_deleted_when_only_memcode(self):
        self.assertTrue(er.write_block(self.p, "x"))
        self.assertTrue(os.path.exists(self.p))
        self.assertTrue(er.write_block(self.p, ""))
        self.assertFalse(os.path.exists(self.p))


class OwnedFile(unittest.TestCase):
    def test_write_and_exclude(self):
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", d], check=True)
        p = os.path.join(d, ".x", "memcode.md")
        self.assertTrue(er.write_file(p, "body", "---\nh\n---\n"))
        self.assertEqual(Path(p).read_text(), "---\nh\n---\nbody\n")
        er.git_exclude(d, ".x/memcode.md"); er.git_exclude(d, ".x/memcode.md")
        excl = Path(d, ".git", "info", "exclude").read_text()
        self.assertEqual(excl.count("/.x/memcode.md"), 1)
        self.assertTrue(er.write_file(p, ""))
        self.assertFalse(os.path.exists(p))


class Sync(unittest.TestCase):
    def test_sync_agents_md_renders_rules(self):
        d = tempfile.mkdtemp()
        con = store.connect(d)
        store.add_memory(con, "correction", "Rule from user correction: Use tabs.", "", None, {})
        self.assertEqual(er.sync(con, d, ["agents"]), {"agents": True})
        t = Path(d, "AGENTS.md").read_text()
        self.assertIn("Use tabs.", t); self.assertIn(er.START, t)
        with self.assertRaises(ValueError):
            er.sync(con, d, ["nope"])
        con.close()


if __name__ == "__main__":
    unittest.main()
