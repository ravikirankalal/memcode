"""Recall beyond the prompt: the recent conversation, actions, the memory agent's flags, and a second showing."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memcode import engine, retrieval, store  # noqa: E402
from memcode.agent import curate  # noqa: E402

ON = {"MEMCODE_RETRIEVAL": "1", "MEMCODE_TRANSCRIPT_CAPTURE": "0"}


def bash(cmd, session="s"):
    return {"kind": "tool_result", "session": session, "tool": "Bash", "input": {"command": cmd}, "command": cmd,
            "file_path": None, "exit_code": 0, "output": ""}


class ContextRecall(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.con = store.connect(self.d)
        self.g16 = store.add_memory(self.con, "agent", "G16 (the invoice export) is parked until the billing rewrite "
                                    "lands.", "", None, {}, topic="decision")
        self.tests = store.add_memory(self.con, "agent", "Run the tests with `make check`; plain pytest misses the "
                                      "fixtures in checks/.", "", None, {}, topic="workflow")
        self.other = store.add_memory(self.con, "agent", "The logo is an SVG in assets/brand.", "", None, {})

    def tearDown(self):
        self.con.close()

    def test_the_conversation_brings_back_what_the_prompt_does_not_name(self):
        with mock.patch.dict(os.environ, ON):
            engine.prompt(self.con, self.d, "s", "what is the state of G16, the invoice export?")
            self.con.execute("DELETE FROM injections")                       # as if it had not been shown
            ctx = engine.prompt(self.con, self.d, "s", "ok, start on it then")
        self.assertIn("G16 (the invoice export) is parked", ctx)             # from the earlier prompt
        self.assertNotIn("logo", ctx)

    def test_a_start_block_memory_comes_back_once_when_clearly_relevant(self):
        self.con.execute("INSERT INTO injections(session,memory_id,ts,source) VALUES('s',?,0,'pinned')", (self.tests,))
        with mock.patch.dict(os.environ, ON):
            first = engine.prompt(self.con, self.d, "s", "run the tests with make check, the fixtures in checks/ fail")
            again = engine.prompt(self.con, self.d, "s", "run the tests with make check again")
            weak = engine.prompt(self.con, self.d, "s2", "anything")
        self.assertIn("make check", first)
        self.assertNotIn("make check", again)                                # once
        self.assertEqual(weak, "")

    def test_an_action_brings_back_its_memories(self):
        with mock.patch.dict(os.environ, ON):
            out = engine.tool_result(self.con, self.d, bash("pytest -q checks/ --fixtures"))
            none = engine.tool_result(self.con, self.d, bash("ls -la"))
            store.add_memory(self.con, "agent", "In the tmux test, send Down then Enter at the trust prompt.",
                             "assets/brand", None, {})
            named = engine.tool_result(self.con, self.d, bash("du -sh assets/brand"))   # names the folder only
        self.assertIn("## Memory relevant to what you just did", out)
        self.assertIn("make check", out)
        self.assertEqual(none, "")
        self.assertNotIn("tmux", named)                                     # anchored there, but about something else
        src = [r[0] for r in self.con.execute("SELECT source FROM injections")]
        self.assertEqual(set(src), {"action"})
        with mock.patch.dict(os.environ, {"MEMCODE_RETRIEVAL": "0"}):
            self.assertEqual(engine.tool_result(self.con, self.d, bash("pytest -q checks/", "s3")), "")

    def test_the_memory_agent_flags_a_memory_for_the_next_step(self):
        cond = "[user] let's pick up the invoice export now\n[agent] Starting on the export module."
        recall = {"op": "recall", "target": self.g16, "text": "the user is starting the parked export",
                  "evidence": "pick up the invoice export now"}
        bad = dict(recall, target=self.other, evidence="not in the transcript at all")
        self.assertEqual(curate.store_items(self.con, self.d, "s", [recall, bad], cond, "m"), [])   # not a change
        with mock.patch.dict(os.environ, {"MEMCODE_RETRIEVAL": "0"}):        # delivered with recall off too
            ctx = engine.prompt(self.con, self.d, "s", "go")
            later = engine.prompt(self.con, self.d, "s", "go on")
        self.assertIn("## Memory flagged by memcode's memory agent for what you are doing now", ctx)
        self.assertIn("G16 (the invoice export) is parked", ctx)
        self.assertIn("(why now: the user is starting the parked export)", ctx)
        self.assertNotIn("logo", ctx)
        self.assertEqual(later, "")                                          # once
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM pending_recalls").fetchone()[0], 0)

    def test_a_flag_waits_for_its_own_session_and_dies_with_its_memory(self):
        cond = "[user] let's pick up the invoice export now"
        recall = {"op": "recall", "target": self.g16, "text": "now", "evidence": "pick up the invoice export now"}
        curate.store_items(self.con, self.d, "s", [recall], cond, "m")
        self.assertEqual(retrieval.flagged(self.con, "other"), "")
        store.delete_ids(self.con, [self.g16])
        self.assertEqual(retrieval.flagged(self.con, "s"), "")


if __name__ == "__main__":
    unittest.main()
