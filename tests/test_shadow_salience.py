import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from memcode import cli, pinned, store

ROOT = Path(__file__).resolve().parent.parent


def start(root, session):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    return subprocess.run([sys.executable, "-m", "memcode.hook_cli", "SessionStart"], env=env, capture_output=True,
                          input=json.dumps({"session_id": session, "cwd": root}), text=True)


class Shadow(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        (Path(self.root) / "a.py").write_text("x = 1\n")
        con = store.connect(self.root)
        self.rule = store.add_memory(con, "correction", "Rule from user correction: Always use tabs.", "", None, {})
        self.note = store.add_memory(con, "fail_to_fix", "pytest failed then passed", "a.py", store.sha1(b"x = 1\n"), {})
        con.close()

    def test_session_start_logs_salience_and_injections(self):
        start(self.root, "s1"); start(self.root, "s2")
        con = store.connect(self.root)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM salience_log WHERE memory_id=?", (self.rule,)).fetchone()[0], 2)
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

    def test_log_is_bounded_and_scores_never_change_the_rendered_block(self):
        con = store.connect(self.root)
        before = pinned.render_pinned(con, self.root)
        from memcode import salience
        for _ in range(store.SALIENCE_KEEP + 10):
            salience.log_all(con)
        store.prune_salience_log(con)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM salience_log WHERE memory_id=?", (self.rule,)).fetchone()[0],
                         store.SALIENCE_KEEP)
        self.assertEqual(pinned.render_pinned(con, self.root), before)      # shadow mode: no ranking effect
        con.close()

    def test_cli_salience(self):
        start(self.root, "s1")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.main(["--root", self.root, "salience"]), 0)
        self.assertIn("Rule from user", out.getvalue())
        self.assertIn("shown", out.getvalue())


if __name__ == "__main__":
    unittest.main()
