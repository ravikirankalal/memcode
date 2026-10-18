import json
import os
import tempfile
import unittest
from unittest import mock

from memcode import activity, engine, store


class Activity(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.con = store.connect(self.d)
        self.path = os.path.join(self.d, ".memcode", "activity.json")

    def tearDown(self):
        self.con.close()

    def feed(self):
        with open(self.path) as fh:
            return json.load(fh)

    def test_capture_and_injection_events_with_counts(self):
        with mock.patch.dict(os.environ, {"MEMCODE_RETRIEVAL": "1"}):
            engine.prompt(self.con, self.d, "s", "do the thing")
            engine.tool_result(self.con, self.d, {"kind": "tool_result", "session": "s", "tool": "Edit",
                                                  "input": {"file_path": "a.py"}, "command": None,
                                                  "file_path": "a.py", "exit_code": 0, "output": ""})
            engine.prompt(self.con, self.d, "s", "No, always use tabs for indentation in this repo.")
            f = self.feed()
            saved = [e for e in f["events"] if e["kind"] == "saved"]
            self.assertEqual(len(saved), 1)
            self.assertIn("rule: ", saved[0]["text"])
            self.assertEqual((f["counts"]["memories"], f["counts"]["rules"]), (1, 1))
            engine.session_start(self.con, self.d, "s2")
            self.assertEqual(self.feed()["events"][-1]["kind"], "start")
            self.assertIn("1 rule,", self.feed()["events"][-1]["text"])

    def test_bounded_and_never_raises(self):
        for i in range(30):
            activity.note(self.con, "recalled", f"x {i}")
        self.assertEqual(len(self.feed()["events"]), activity.MAX_EVENTS)
        self.assertEqual(self.feed()["events"][-1]["text"], "x 29")
        with open(self.path, "w") as fh:
            fh.write("{not json")
        activity.note(self.con, "recalled", "after corruption")             # rebuilt, no exception
        self.assertEqual([e["text"] for e in self.feed()["events"]], ["after corruption"])
        memdb = tempfile.mkdtemp()
        con = store.connect(memdb)
        os.chmod(os.path.join(memdb, ".memcode"), 0o500)
        try:
            activity.note(con, "saved", "unwritable dir")                   # swallowed
        finally:
            os.chmod(os.path.join(memdb, ".memcode"), 0o700)
            con.close()


if __name__ == "__main__":
    unittest.main()
