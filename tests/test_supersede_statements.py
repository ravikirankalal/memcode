import tempfile
import time
import unittest

from memcode import pinned, store
from memcode.triggers import TriggerEngine, _imperative


def flow(con, root, prompt, session="s"):
    out = []
    for e in ({"kind": "prompt", "session": session, "prompt": "write it"},
              {"kind": "tool_use", "session": session, "tool": "Bash", "input": {"command": "make"}},
              {"kind": "prompt", "session": session, "prompt": prompt}):
        out += TriggerEngine(con, root).handle(dict(e))
    return out


class RulesOrder(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.con = store.connect(self.root)

    def test_rules_listed_oldest_to_newest_with_override_note(self):
        for i, t in enumerate(["Indent with tabs.", "Indent with exactly 2 spaces."]):
            mid = store.add_memory(self.con, "correction", f"Rule from user correction: {t}", "", None, {})
            self.con.execute("UPDATE memories SET created_at=? WHERE id=?", (1000 + i, mid))
        self.con.commit()
        out = pinned.render_pinned(self.con, self.root)
        self.assertIn(pinned.RULES_NOTE, out)
        self.assertLess(out.index("tabs"), out.index("2 spaces"))
        self.assertEqual(pinned.count_injected(out), (2, 0))      # the note line is not counted as a rule

    def test_cap_keeps_the_newest_rules(self):
        for i in range(pinned.MAX_RULES + 5):
            mid = store.add_memory(self.con, "correction", f"Rule from user correction: Rule number {i}.", "", None, {})
            self.con.execute("UPDATE memories SET created_at=? WHERE id=?", (1000 + i, mid))
        self.con.commit()
        out = pinned.render_pinned(self.con, self.root, token_cap=4000)
        self.assertNotIn("Rule number 4.", out)
        self.assertIn(f"Rule number {pinned.MAX_RULES + 4}.", out)
        self.assertLess(out.index("Rule number 5."), out.index(f"Rule number {pinned.MAX_RULES + 4}."))


class StatementCapture(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.con = store.connect(self.root)

    def test_stated_rules_are_captured_as_imperative(self):
        for prompt, expect in [
            ("Heads up: this team prefers single quotes over double quotes everywhere, so keep to that.",
             "This team prefers single quotes over double quotes everywhere"),
            ("FYI we always squash-merge into main.", "We always squash-merge into main."),
            ("Our convention is snake_case for files.", "Our convention is snake_case for files."),
        ]:
            con = store.connect(tempfile.mkdtemp())
            ids = flow(con, self.root, prompt)
            self.assertEqual(len(ids), 1, prompt)
            self.assertIn(expect, store.list_memories(con)[0]["text"])

    def test_plain_fyis_and_chatter_do_not_become_rules(self):
        for prompt in ["FYI the build is red right now.", "Thanks, looks good.", "note that line 3 is long",
                       "Heads up, I'm out tomorrow."]:
            self.assertEqual(flow(store.connect(tempfile.mkdtemp()), self.root, prompt), [], prompt)

    def test_statement_without_prior_agent_action_is_ignored(self):
        ids = TriggerEngine(self.con, self.root).handle(
            {"kind": "prompt", "session": "z", "prompt": "Heads up: this team prefers tabs."})
        self.assertEqual(ids, [])

    def test_imperative_strips_leading_markers(self):
        self.assertEqual(_imperative("Heads up: we always use tabs."), "We always use tabs.")


if __name__ == "__main__":
    unittest.main()
