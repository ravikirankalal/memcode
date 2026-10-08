import tempfile
import unittest

from memcode import store
from memcode.triggers import TriggerEngine


class Session:
    def __init__(self):
        self.root = tempfile.mkdtemp()
        self.con = store.connect(self.root)
        self.n = 0

    def say(self, prompt):
        return TriggerEngine(self.con, self.root).handle({"kind": "prompt", "session": "s", "prompt": prompt})

    def act(self, cmd="make"):
        self.n += 1
        TriggerEngine(self.con, self.root).handle(
            {"kind": "tool_use", "session": "s", "tool": "Bash", "input": {"command": f"{cmd} {self.n}"}})

    def rules(self):
        return [r["text"] for r in store.list_memories(self.con) if r["trigger"] == "correction"]


class Relaxed(unittest.TestCase):
    def test_correction_after_text_only_turns_is_captured(self):
        s = Session()
        s.say("create ops.py"); s.act()
        s.say("What does mul do? Just explain.")          # agent answers with text only: no tool use
        s.say("And why is it public?")                     # a second text-only turn
        self.assertEqual(len(s.say("Also: every new module must end with a __main__ demo block. Remember that.")), 1)
        self.assertIn("__main__", s.rules()[0])

    def test_bare_complaint_after_text_only_gap_is_not_a_rule(self):
        s = Session()
        s.say("create ops.py"); s.act()
        s.say("What does mul do?")
        for p in ["that's wrong", "No, not like that", "Don't do that", "stop"]:
            self.assertEqual(s.say(p), [], p)             # needs an explicit rule once the agent has not just acted

    def test_first_prompt_of_a_session_is_never_a_rule(self):
        s = Session()
        self.assertEqual(s.say("Always use tabs. Remember that."), [])
        self.assertEqual(s.rules(), [])

    def test_benign_chatter_after_activity_does_not_become_a_rule(self):
        s = Session()
        s.say("fix the bug"); s.act()
        for p in ["Don't forget to add tests", "No problem, thanks!", "never mind, carry on", "Looks good, merge it",
                  "Can you explain the diff?", "FYI the build is red right now.", "Heads up, I'm out tomorrow.",
                  "Always happy to help", "thanks!", "what is the all-time best approach here?"]:
            self.assertEqual(s.say(p), [], p)
        self.assertEqual(s.rules(), [])

    def test_state_survives_fresh_engines_per_event(self):
        s = Session()                                      # every call above already builds a new engine; assert replay
        s.say("task"); s.act(); s.say("explain"); 
        self.assertEqual(len(s.say("No - always use tabs here. Remember that.")), 1)


if __name__ == "__main__":
    unittest.main()
