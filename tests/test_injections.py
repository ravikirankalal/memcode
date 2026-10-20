import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from memcode import pinned, store

ROOT = Path(__file__).resolve().parent.parent


def start(root, session):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    return subprocess.run([sys.executable, "-m", "memcode.hook_cli", "SessionStart"], env=env, capture_output=True,
                          input=json.dumps({"session_id": session, "cwd": root}), text=True)


class Injections(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        (Path(self.root) / "a.py").write_text("x = 1\n")
        con = store.connect(self.root)
        self.rule = store.add_memory(con, "correction", "Rule from user correction: Always use tabs.", "", None, {})
        self.note = store.add_memory(con, "fail_to_fix", "pytest failed then passed", "a.py", store.sha1(b"x = 1\n"), {})
        con.close()

    def test_session_start_records_what_each_session_was_shown(self):
        start(self.root, "s1"); start(self.root, "s2")
        con = store.connect(self.root)
        shown = {(r[0], r[1]) for r in con.execute("SELECT session, memory_id FROM injections")}
        self.assertEqual(shown, {("s1", self.rule), ("s1", self.note), ("s2", self.rule), ("s2", self.note)})
        con.close()

    def test_stale_memories_are_not_recorded_as_shown(self):
        (Path(self.root) / "a.py").write_text("x = 2\n")           # file changed -> note stale at start-up
        start(self.root, "s1")
        con = store.connect(self.root)
        ids = {r[0] for r in con.execute("SELECT memory_id FROM injections")}
        self.assertEqual(ids, {self.rule})
        con.close()

    def test_shown_ids_match_rendered_text(self):
        con = store.connect(self.root)
        text = pinned.render_pinned(con, self.root)
        self.assertEqual(sorted(pinned.shown_ids(con, text)), sorted([self.rule, self.note]))
        con.close()

if __name__ == "__main__":
    unittest.main()
