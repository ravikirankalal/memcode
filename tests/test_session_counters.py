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
from memcode.triggers import TriggerEngine

ROOT = Path(__file__).resolve().parent.parent


def correction_flow(con, root, session, text="No - always use tabs. Remember that."):
    out = []
    for e in ({"kind": "prompt", "session": session, "prompt": "write it"},
              {"kind": "tool_use", "session": session, "tool": "Bash", "input": {"command": "make"}},
              {"kind": "prompt", "session": session, "prompt": text}):
        out += TriggerEngine(con, root).handle(dict(e))
    return out


def row(con, s):
    return con.execute("SELECT * FROM session_stats WHERE session=?", (s,)).fetchone()


class Counters(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.con = store.connect(self.root)

    def test_capture_counted_once_and_repeat_counted_next_session(self):
        self.assertEqual(len(correction_flow(self.con, self.root, "s1")), 1)
        self.assertEqual((row(self.con, "s1")["captured"], row(self.con, "s1")["repeated_corrections"]), (1, 0))
        correction_flow(self.con, self.root, "s2")                       # same rule stated again
        r = row(self.con, "s2")
        self.assertEqual((r["captured"], r["repeated_corrections"]), (0, 1))

    def test_replay_does_not_double_count(self):
        correction_flow(self.con, self.root, "s1")
        for _ in range(3):   # later events replay the earlier ones; counters must not move
            TriggerEngine(self.con, self.root).handle({"kind": "prompt", "session": "s1", "prompt": "thanks"})
        self.assertEqual(row(self.con, "s1")["captured"], 1)

    def test_bump_rejects_unknown_field(self):
        with self.assertRaises(ValueError):
            store.bump(self.con, "s", "bogus; DROP TABLE memories")

    def test_count_injected_and_session_start_hook(self):
        store.add_memory(self.con, "correction", "Rule from user correction: Always use tabs.", "", None, {})
        (Path(self.root) / "a.py").write_text("x = 1\n")          # real anchor, so the start-up scan keeps it fresh
        store.add_memory(self.con, "fail_to_fix", "pytest failed then passed", "a.py", store.sha1(b"x = 1\n"), {})
        text = pinned.render_pinned(self.con, self.root)
        self.assertEqual(pinned.count_injected(text), (1, 1))
        self.con.close()
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        subprocess.run([sys.executable, "-m", "memcode.hook_cli", "SessionStart"], env=env, capture_output=True,
                       input=json.dumps({"session_id": "abc12345", "cwd": self.root}), text=True)
        con = store.connect(self.root)
        r = row(con, "abc12345")
        self.assertEqual((r["rules_injected"], r["notes_injected"]), (1, 1))
        con.close()

    def test_cli_sessions_and_stats(self):
        correction_flow(self.con, self.root, "s1"); correction_flow(self.con, self.root, "s2")
        self.con.close()
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.main(["--root", self.root, "sessions"]), 0)
            cli.main(["--root", self.root, "stats"])
        t = out.getvalue()
        self.assertIn("2 sessions: 1 memories captured, 1 corrections repeated", t)
        self.assertIn("repeated corrections: 1", t)


if __name__ == "__main__":
    unittest.main()
