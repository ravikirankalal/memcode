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

    def test_only_showings_since_the_previous_judging_are_judged(self):
        now = time.time()
        self.con.executemany("INSERT INTO injections(session,memory_id,ts,source) VALUES('s',?,?,'prompt')",
                             [(self.tests, now - 100), (self.noise, now)])   # the first answered in text read long ago
        self.assertEqual(feedback.judge(self.con, "s", "[agent] about the docs", since=now - 50), ([], [self.noise]))
        self.assertNotIn(self.tests, feedback.counts(self.con))

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
        worker.enqueue(self.con, "s1", path)
        worker.scan_one(self.con, self.d, "s1", path, 0, lambda text, ctx=None: {"items": [], "model": "f", "cost_usd": 0})
        self.assertEqual(feedback.counts(self.con).get(self.tests), (1, 0))

    def test_judging_keeps_working_scan_after_scan(self):
        from memcode.agent import worker
        import json
        path = os.path.join(self.d, "t3.jsonl")
        fake = lambda text, ctx=None: {"items": [], "model": "f", "cost_usd": 0}   # noqa: E731

        def turn(user_text, reply):
            with open(path, "a") as fh:
                fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": user_text}}) + "\n")
                fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                    {"type": "text", "text": reply}]}}) + "\n")
            worker.enqueue(self.con, "s3", path)
            worker.run_worker(self.d, fake)

        turn("first question " * 30, "a first answer " * 30)                     # the clock starts
        self.show("s3", self.tests)
        turn("how do I run the tests? " * 10, "> memcode: tests run with `make check` here, pytest misses the fixtures.")
        self.show("s3", self.noise)
        turn("and the docs? " * 20, "they are in docs/ " * 20)
        self.assertEqual(feedback.counts(self.con), {self.tests: (1, 0), self.noise: (0, 1)})

    def test_a_session_read_before_judging_existed_starts_the_clock_first(self):
        from memcode.agent import worker
        import json
        self.show("s2", self.tests)                                          # shown before the upgrade
        path = os.path.join(self.d, "t2.jsonl")
        with open(path, "w") as fh:
            for i in range(3):
                fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": f"turn {i} " * 40}}) + "\n")
            fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "an answer that names nothing " * 20}]}}) + "\n")
        worker.enqueue(self.con, "s2", path)
        worker.scan_one(self.con, self.d, "s2", path, 1, lambda text, ctx=None: {"items": [], "model": "f", "cost_usd": 0})
        self.assertEqual(feedback.counts(self.con), {})                     # not judged against the wrong replies


if __name__ == "__main__":
    unittest.main()


class ProposalFeedback(unittest.TestCase):
    """What memcode did not keep of the memory agent's proposals, and why, is told back to it."""

    def setUp(self):
        from memcode.agent import db
        self.d = tempfile.mkdtemp()
        self.con = store.connect(self.d)
        db.ensure(self.con)
        self.cond = "[user] please always run make check before pushing\n[ran] `make check` -> ok | 12 passed"

    def tearDown(self):
        self.con.close()

    def item(self, **kw):
        base = {"op": "add", "target": 0, "from_user": False, "topic": "workflow", "subject": "", "importance": 4,
                "text": "Run make check before pushing.", "evidence": "12 passed", "path": "", "links": [],
                "unusual": False, "conflicts": False}
        return dict(base, **kw)

    def test_each_refusal_is_told_with_its_reason(self):
        from memcode.agent import curate
        items = [self.item(importance=2, text="A minor thing about the build output."),
                 self.item(text="Tests print a summary line.", evidence="not in the transcript"),
                 self.item(from_user=True, topic="process", text="Run make check before every push.",
                           evidence="12 passed"),
                 self.item(op="retire", target=999, text="gone", evidence="12 passed"),
                 self.item(op="recall", target=999, text="now", evidence="12 passed")]
        curate.store_items(self.con, self.d, "s", items, self.cond, "m")
        text = conversation.delta(self.con, "s", 0)
        self.assertIn('- not kept, your add "A minor thing about the build output." (evidence "12 passed"): rated 2; this '
                      'kind is kept from 4', text)
        self.assertIn('"Tests print a summary line." (evidence "not in the transcript"): the evidence is not an exact '
                      'quote of the transcript', text)
        self.assertIn("from_user needs the user's own words as evidence", text)
        self.assertIn('- not kept, your retire #999 "gone" (evidence "12 passed"): there is no memory #999', text)
        self.assertIn("- not kept, your recall #999", text)

    def test_the_briefing_has_today_and_how_memories_were_taken(self):
        from memcode.agent import model
        mid = store.add_memory(self.con, "agent", "The final design excludes docs/salvage.", "", None, {})
        for s in ("a", "b", "c"):
            self.con.execute("INSERT INTO injections(session,memory_id,ts,source) VALUES(?,?,?, 'prompt')",
                             (s, mid, time.time()))
            self.con.commit()
            feedback.judge(self.con, s, "[agent] an answer")
        brief = model.briefing(self.con, self.d, "s")
        self.assertIn(f"Today: {time.strftime('%Y-%m-%d')}", brief)
        self.assertIn(f"#{mid} note", brief)
        self.assertIn("(shown 3x, never used: no longer recalled until changed)", brief)
