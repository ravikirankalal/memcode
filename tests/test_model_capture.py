import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from memcode import cli, model_capture as mc, store

ROOT = Path(__file__).resolve().parent.parent


def hook(root, name, payload, **env):
    e = dict(os.environ, PYTHONPATH=str(ROOT), **env)
    return subprocess.run([sys.executable, "-m", "memcode.hook_cli", name], env=e, capture_output=True, text=True,
                          input=json.dumps(dict(payload, cwd=root)))


class ModelCapture(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.con = store.connect(self.root)
        os.environ.pop("MEMCODE_MODEL_CAPTURE", None)

    def act(self, sess="s"):
        store.log_event(self.con, sess, "tool_use", {"kind": "tool_use", "tool": "Bash", "input": {"command": "make"}})

    def test_off_by_default_and_switchable(self):
        self.assertFalse(mc.enabled(self.root))
        with redirect_stdout(io.StringIO()):
            cli.main(["--root", self.root, "config", "model-capture", "on"])
        self.assertTrue(mc.enabled(self.root))
        with mock.patch.dict(os.environ, {"MEMCODE_MODEL_CAPTURE": "0"}):
            self.assertFalse(mc.enabled(self.root))          # env can force it off

    def test_gate(self):
        msg = "FYI, in this repo we indent with tabs rather than spaces."
        self.assertFalse(mc.should_queue(self.con, "s", msg))                       # agent has not acted yet
        self.act()
        self.assertTrue(mc.should_queue(self.con, "s", msg))
        self.assertFalse(mc.should_queue(self.con, "s", "ok"))                      # too short
        self.assertFalse(mc.should_queue(self.con, "s", "Why did you pick that name?"))   # question
        self.assertFalse(mc.should_queue(self.con, "s", "No - always use tabs. Remember that."))  # regex owns it

    def test_worker_stores_rule_dedupes_and_skips_non_rules(self):
        self.act()
        for t in ("we indent with tabs here", "we indent with tabs in this repo", "thanks, looks fine now"):
            mc.enqueue(self.con, "s", t)
        fake = lambda t: ({"is_rule": True, "rule": "Indent with tabs.", "model": "fake"} if "tabs" in t
                          else {"is_rule": False, "rule": "", "model": "fake"})
        self.assertEqual(mc.run_worker(self.root, classify_fn=fake), 1)             # second "tabs" deduped
        rules = [r for r in store.list_memories(self.con) if r["trigger"] == "correction"]
        self.assertEqual([r["text"] for r in rules], ["Rule from user correction: Indent with tabs."])
        self.assertEqual(json.loads(rules[0]["provenance"])["source"], "model")
        self.assertEqual(mc.pending(self.con), 0)

    def test_failures_retry_then_error_and_never_raise(self):
        self.act(); mc.enqueue(self.con, "s", "we indent with tabs here")
        self.assertEqual(mc.run_worker(self.root, classify_fn=lambda t: None), 0)
        self.assertEqual(self.con.execute("SELECT status, attempts FROM capture_queue").fetchone()[:], ("error", 2))

    def test_queued_text_is_redacted(self):
        self.act(); mc.enqueue(self.con, "s", "we deploy with token ghp_abcdefghijklmnopqrstuvwxyz0123456789 always")
        self.assertNotIn("ghp_", self.con.execute("SELECT text FROM capture_queue").fetchone()[0])

    def test_hook_queues_only_when_enabled_and_recursion_guard(self):
        p = {"session_id": "s", "prompt": "FYI, in this repo we indent with tabs rather than spaces."}
        hook(self.root, "PostToolUse", {"session_id": "s", "tool_name": "Bash", "tool_input": {"command": "make"},
                                         "tool_response": {"stdout": ""}})
        hook(self.root, "UserPromptSubmit", p)                                          # disabled: nothing queued
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM capture_queue").fetchone()[0], 0)
        hook(self.root, "UserPromptSubmit", p, MEMCODE_MODEL_CAPTURE="1", MEMCODE_DISABLE="1")   # guard: no-op
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM capture_queue").fetchone()[0], 0)
        # enabled: queued (the spawned worker will fail fast here: `claude` gets MEMCODE_DISABLE and no test creds)
        hook(self.root, "UserPromptSubmit", p, MEMCODE_MODEL_CAPTURE="1", PATH="/nonexistent")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM capture_queue").fetchone()[0], 1)

    def test_classify_handles_missing_cli(self):
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
            self.assertIsNone(mc.classify("we indent with tabs"))


if __name__ == "__main__":
    unittest.main()
