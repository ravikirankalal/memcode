"""Acceptance feedback: memories shown next to the work are judged used or unused from the coding agent's replies."""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memcode import engine, feedback, retrieval, store  # noqa: E402
from memcode.agent import conversation  # noqa: E402

ON = {"MEMCODE_RETRIEVAL": "1", "MEMCODE_TRANSCRIPT_CAPTURE": "0"}


class Feedback(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.con = store.connect(self.d)
        from memcode.agent import db
        db.ensure(self.con)                                                  # the memory agent's tables
        self.tests = store.add_memory(self.con, "agent", "Run the tests with `make check`; plain pytest misses the "
                                      "fixtures in checks/.", "", None, {}, topic="workflow")
        self.noise = store.add_memory(self.con, "agent", "The final design excludes docs/salvage and docs/decisions.",
                                      "", None, {}, topic="decision")

    def tearDown(self):
        self.con.close()

    def show(self, session, *ids, source="prompt"):
        self.con.executemany("INSERT INTO injections(session,memory_id,ts,source) VALUES(?,?,?,?)",
                             [(session, i, time.time(), source) for i in ids])
        self.con.commit()

    def test_a_memcode_line_marks_used_the_rest_unused(self):
        self.show("s", self.tests, self.noise)
        self.assertEqual(feedback.judge(self.con, "s", "[user] how do I test?"), ([], []))   # no reply yet: wait
        reply = "[agent] > memcode: tests run with `make check` here, plain pytest misses the fixtures. Run it."
        self.assertEqual(feedback.judge(self.con, "s", reply), ([self.tests], [self.noise]))
        self.assertEqual(feedback.judge(self.con, "s", reply), ([], []))                     # once per session
        self.assertEqual(feedback.counts(self.con), {self.tests: (1, 0), self.noise: (0, 1)})
        lines = feedback.delta_lines(self.con, "s", 0)
        self.assertTrue(lines[0].startswith(f"- used: #{self.tests} (recalled for a prompt; 1 used, 0 unused so far)"))
        self.assertTrue(lines[1].startswith(f"- shown but not used: #{self.noise} (recalled for a prompt; 0 used, 1"))

    def test_the_start_block_is_not_judged(self):
        self.show("s", self.tests, source="pinned")
        self.assertEqual(feedback.judge(self.con, "s", "[agent] done"), ([], []))

    def test_never_used_memories_are_muted_until_they_change(self):
        for s in ("a", "b", "c"):
            self.show(s, self.noise)
            feedback.judge(self.con, s, "[agent] here is the answer")
        self.assertEqual(feedback.muted(self.con), {self.noise})
        with mock.patch.dict(os.environ, ON):
            self.assertNotIn(self.noise, [r["id"] for r in retrieval._candidates(self.con)])
        self.con.execute("UPDATE memories SET updated_at=? WHERE id=?", (time.time() + 1, self.noise))
        self.assertEqual(feedback.muted(self.con), set())                                    # changed: recalled again

    def test_the_memory_agent_hears_it(self):
        self.show("s", self.tests)
        feedback.judge(self.con, "s", "[agent] > memcode: tests run with `make check` here because of the fixtures")
        text = conversation.delta(self.con, "s", 0)
        self.assertIn(f"- used: #{self.tests}", text)

    def test_the_scan_judges_before_the_memory_agent_reads(self):
        from memcode.agent import worker
        import json
        with mock.patch.dict(os.environ, ON):
            engine.prompt(self.con, self.d, "s1", "how do I run the tests with make check and the fixtures?")
        path = os.path.join(self.d, "t.jsonl")
        with open(path, "w") as fh:
            for role, text in (("user", "how do I run the tests with make check and the fixtures?"),
                               ("assistant", "> memcode: tests run with `make check`, pytest misses the fixtures.")):
                content = text if role == "user" else [{"type": "text", "text": text}]
                fh.write(json.dumps({"type": role, "message": {"role": role, "content": content}}) + "\n")
        worker.scan_one(self.con, self.d, "s1", path, 0, lambda text, ctx=None: {"items": [], "model": "f", "cost_usd": 0})
        self.assertEqual(feedback.counts(self.con).get(self.tests), (1, 0))


if __name__ == "__main__":
    unittest.main()
