import json
import tempfile
import time
import unittest
from pathlib import Path

from memcode import outcomes, pinned, store
from memcode.triggers import TriggerEngine

OLD = time.time() - 2 * outcomes.QUIET_S          # a session that ended long ago


class Outcomes(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        (Path(self.root) / "a.py").write_text("x = 1\n")
        self.con = store.connect(self.root)
        self.note = store.add_memory(self.con, "fail_to_fix", "pytest failed until a.py fixed", "a.py",
                                     store.sha1(b"x = 1\n"), {"session": "old"}, confidence=0.5)
        self.rule = store.add_memory(self.con, "correction", "Rule from user correction: Always use tabs.", "", None,
                                     {"session": "old"}, confidence=0.5)

    def shown(self, sess, *ids, ts=OLD):
        self.con.executemany("INSERT INTO injections(session,memory_id,ts) VALUES(?,?,?)", [(sess, i, ts) for i in ids])
        self.con.commit()

    def ev(self, sess, payload, ts=OLD):
        self.con.execute("INSERT INTO events(session,kind,payload,ts) VALUES(?,?,?,?)",
                         (sess, payload["kind"], json.dumps(payload), ts))
        self.con.commit()

    def edit(self, sess, path="a.py"):
        self.ev(sess, {"kind": "tool_use", "tool": "Edit", "input": {"file_path": f"{self.root}/{path}"}})

    def run_cmd(self, sess, cmd="python3 -m pytest -q", code=0):
        self.ev(sess, {"kind": "tool_result", "tool": "Bash", "input": {"command": cmd}, "exit_code": code})

    def conf(self, mid):
        return self.con.execute("SELECT confidence FROM memories WHERE id=?", (mid,)).fetchone()[0]

    def outcome(self, sess, mid):
        r = self.con.execute("SELECT outcome FROM outcomes WHERE session=? AND memory_id=?", (sess, mid)).fetchone()
        return r[0] if r else None

    def test_success_needs_edit_of_anchor_then_passing_tests(self):
        self.shown("s", self.note); self.edit("s"); self.run_cmd("s")
        outcomes.score_finished_sessions(self.con, self.root)
        self.assertEqual(self.outcome("s", self.note), "success:tests_passed")
        self.assertGreater(self.conf(self.note), 0.5)

    def test_tests_before_the_edit_do_not_count(self):
        self.shown("s", self.note); self.run_cmd("s"); self.edit("s")
        outcomes.score_finished_sessions(self.con, self.root)
        self.assertEqual(self.outcome("s", self.note), "exposed")
        self.assertEqual(self.conf(self.note), 0.5)

    def test_untouched_anchor_is_irrelevant_even_if_tests_pass(self):
        self.shown("s", self.note); self.edit("s", "other.py"); self.run_cmd("s")
        outcomes.score_finished_sessions(self.con, self.root)
        self.assertEqual(self.outcome("s", self.note), "irrelevant")
        self.assertEqual(self.conf(self.note), 0.5)

    def test_failed_tests_and_non_test_commands_are_not_success(self):
        self.shown("s", self.note); self.edit("s"); self.run_cmd("s", code=1); self.run_cmd("s", cmd="ls -la")
        outcomes.score_finished_sessions(self.con, self.root)
        self.assertEqual(self.outcome("s", self.note), "exposed")

    def test_recurrence_on_same_anchor_is_failure(self):
        self.shown("s", self.note); self.edit("s"); self.run_cmd("s")
        store.add_memory(self.con, "fail_to_fix", "it broke again", "a.py", None, {"session": "s"})
        outcomes.score_finished_sessions(self.con, self.root)
        self.assertEqual(self.outcome("s", self.note), "failure:recurred")
        self.assertLess(self.conf(self.note), 0.5)

    def test_rules_are_never_positively_reinforced(self):
        self.shown("s", self.rule); self.edit("s"); self.run_cmd("s")
        outcomes.score_finished_sessions(self.con, self.root)
        self.assertEqual(self.outcome("s", self.rule), "exposed")
        self.assertEqual(self.conf(self.rule), 0.5)

    def test_repeated_rule_is_failure_at_detection_time(self):
        root = tempfile.mkdtemp(); con = store.connect(root)
        for sess in ("s1", "s2"):
            for e in ({"kind": "prompt", "session": sess, "prompt": "do it"},
                      {"kind": "tool_use", "session": sess, "tool": "Bash", "input": {"command": "make"}},
                      {"kind": "prompt", "session": sess, "prompt": "No - always use tabs. Remember that."}):
                TriggerEngine(con, root).handle(dict(e))
        rid = store.list_memories(con)[0]["id"]
        self.assertEqual(con.execute("SELECT outcome FROM outcomes WHERE session='s2' AND memory_id=?", (rid,)).fetchone()[0],
                         "failure:repeated")
        self.assertLess(con.execute("SELECT confidence FROM memories WHERE id=?", (rid,)).fetchone()[0], 0.7)

    def test_current_and_recent_sessions_are_not_scored_and_scoring_is_idempotent(self):
        self.shown("cur", self.note); self.edit("cur"); self.run_cmd("cur")
        self.shown("live", self.note, ts=time.time()); self.edit("live")
        self.ev("live", {"kind": "tool_use", "tool": "Bash", "input": {"command": "x"}}, ts=time.time())
        self.assertEqual(outcomes.score_finished_sessions(self.con, self.root, current_session="cur"), 0)
        self.assertIsNone(self.outcome("cur", self.note)); self.assertIsNone(self.outcome("live", self.note))
        self.assertEqual(outcomes.score_finished_sessions(self.con, self.root), 1)      # "cur" now, not "live"
        before = self.conf(self.note)
        self.assertEqual(outcomes.score_finished_sessions(self.con, self.root), 0)      # never twice
        self.assertEqual(self.conf(self.note), before)

    def test_shadow_mode_scoring_never_changes_the_pinned_block(self):
        before = pinned.render_pinned(self.con, self.root)
        self.shown("s", self.note, self.rule); self.edit("s"); self.run_cmd("s")
        outcomes.score_finished_sessions(self.con, self.root)
        self.assertEqual(pinned.render_pinned(self.con, self.root), before)

    def test_confidence_is_bounded(self):
        for i in range(40):
            outcomes.record(self.con, f"s{i}", self.note, "success:x")
        self.assertLessEqual(self.conf(self.note), outcomes.CAP)
        for i in range(40):
            outcomes.record(self.con, f"f{i}", self.note, "failure:x")
        self.assertGreaterEqual(self.conf(self.note), outcomes.FLOOR)

    def test_test_command_patterns(self):
        for c in ["pytest -q", "python3 -m pytest", "npm test", "npm run test", "go test ./...", "cargo test",
                  "make test", "./qa", "cd x && pytest"]:
            self.assertTrue(outcomes.TEST_CMD.search(c), c)
        for c in ["ls", "cat pytest.ini", "git commit -m 'add test'", "echo testing", "make build",
                  "echo npm test", "vim tests/test_a.py", "pytest.ini"]:
            self.assertFalse(outcomes.TEST_CMD.search(c), c)


if __name__ == "__main__":
    unittest.main()
