import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from memcode import store
from memcode.redact import redact
from memcode.triggers import TriggerEngine


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.root = self.d.name
        os.makedirs(os.path.join(self.root, "src"))
        for f, c in {"src/a.py": "x=1\n", "package.json": "{}\n"}.items():
            with open(os.path.join(self.root, f), "w") as fh:
                fh.write(c)
        self.con = store.connect(self.root)
        self.e = TriggerEngine(self.con, self.root)

    def tearDown(self):
        self.con.close()
        self.d.cleanup()

    def ev(self, kind, **kw):
        return self.e.handle({"kind": kind, "session": "s1", **kw})

    def edit(self, path="src/a.py", old="x=1", new="x=2"):
        return self.ev("tool_use", tool="Edit",
                       input={"file_path": path, "old_string": old, "new_string": new})

    def run_cmd(self, cmd, code):
        out = self.ev("tool_use", tool="Bash", input={"command": cmd})
        return out + self.ev("tool_result", tool="Bash", input={"command": cmd},
                             exit_code=code, output="boom" if code else "ok")

    def mems(self, trig=None):
        return [m for m in store.list_memories(self.con) if trig in (None, m["trigger"])]

    def test_correction(self):
        self.edit()
        ids = self.ev("prompt", text="No, don't use x=2 instead use x=3")
        self.assertEqual(len(ids), 1)
        m = self.mems("correction")[0]
        self.assertEqual(m["anchor_path"], "src/a.py")
        self.assertEqual(m["anchor_hash"], store.sha1(b"x=1\n"))
        self.assertIn("s1", m["provenance"])

    def test_no_correction_without_edit(self):
        self.assertEqual(self.ev("prompt", text="No, don't do that"), [])
        self.edit()
        self.assertEqual(self.ev("prompt", text="looks good, now add tests"), [])

    def test_revert_git(self):
        self.edit()
        ids = self.ev("tool_use", tool="Bash", input={"command": "git checkout -- src/a.py"})
        self.assertEqual(len(ids), 1)
        self.assertEqual(self.mems("revert")[0]["anchor_path"], "src/a.py")

    def test_revert_by_edit(self):
        self.edit()
        ids = self.edit(old="x=2", new="x=1")
        self.assertEqual(len(self.mems("revert")), 1)
        self.assertTrue(ids)

    def test_fail_to_fix(self):
        self.run_cmd("pytest tests", 1)
        self.edit()
        ids = self.run_cmd("pytest tests", 0)
        self.assertEqual(len(ids), 1)
        m = self.mems("fail_to_fix")[0]
        self.assertEqual(m["anchor_path"], "src/a.py")

    def test_no_fix_without_edit(self):
        self.run_cmd("pytest tests", 1)
        self.assertEqual(self.run_cmd("pytest tests", 0), [])

    def test_retry(self):
        self.run_cmd("make build", 1)
        ids = self.run_cmd("make build -j1 --verbose", 0)
        self.assertEqual(len(self.mems("retry")), 1)
        self.assertTrue(ids)

    def test_dep_change(self):
        self.edit("package.json", "{}", '{"dependencies":{"left-pad":"1"}}')
        m = self.mems("dep_change")
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]["anchor_path"], "package.json")
        self.assertIsNotNone(m[0]["anchor_hash"])

    def test_no_false_positive(self):
        self.ev("prompt", text="please add a function")
        self.edit()
        self.run_cmd("ls", 0)
        self.run_cmd("ls -la", 0)
        self.run_cmd("pytest", 0)
        self.run_cmd("pytest", 0)
        self.ev("prompt", text="great, thanks")
        self.assertEqual(self.mems(), [])

    def test_redaction(self):
        s = ("AKIAABCDEFGHIJKLMNOP ghp_" + "a" * 30 + " sk-" + "b" * 24 + " xoxb-1234567890-abc\n"
             "API_TOKEN=hunter2 password='p w' Authorization: Bearer abcdef123456\n"
             "https://user:pw@example.com/x\n-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----")
        r = redact(s)
        for bad in ("AKIA", "ghp_", "sk-b", "xoxb", "hunter2", "p w", "abcdef123456", "user:pw", "MIIE"):
            self.assertNotIn(bad, r)
        self.assertIn("[REDACTED]", r)
        self.assertEqual(redact("plain text, nothing here"), "plain text, nothing here")

    def test_redacted_before_storage(self):
        self.edit()
        self.ev("prompt", text="no, that's wrong, API_KEY=sekret123 is leaked")
        m = self.mems("correction")[0]
        self.assertNotIn("sekret123", m["text"])
        payloads = " ".join(r["payload"] for r in self.con.execute("SELECT payload FROM events"))
        self.assertNotIn("sekret123", payloads)


if __name__ == "__main__":
    unittest.main()
