import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from memcode import store
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
        self.assertEqual(m["anchor_path"], "")        # a stated convention is repo-wide
        self.assertIsNone(m["anchor_hash"])
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

    # --- fresh engine per event (hooks run as separate processes)
    def fresh(self, kind, **kw):
        return TriggerEngine(store.connect(self.root), self.root).handle(
            {"kind": kind, "session": "s2", **kw})

    def fresh_cmd(self, cmd, code):
        a = self.fresh("tool_use", tool="Bash", input={"command": cmd})
        return a + self.fresh("tool_result", tool="Bash", input={"command": cmd},
                              exit_code=code, output="boom" if code else "ok")

    def fresh_edit(self, path="src/a.py", old="x=1", new="x=2"):
        return self.fresh("tool_use", tool="Edit",
                          input={"file_path": path, "old_string": old, "new_string": new})

    def test_fresh_fail_to_fix(self):
        self.fresh_cmd("pytest -q", 1)
        self.fresh_edit()
        self.assertEqual(len(self.fresh_cmd("pytest -q", 0)), 1)
        self.assertEqual(len(self.mems("fail_to_fix")), 1)

    def test_fresh_revert(self):
        self.fresh_edit()
        self.assertEqual(len(self.fresh("tool_use", tool="Bash",
                                        input={"command": "cd . && git checkout -- src/a.py; ls"})), 1)
        self.assertEqual(self.mems("revert")[0]["anchor_path"], "src/a.py")

    def test_fresh_revert_edit(self):
        self.fresh_edit()
        self.fresh_edit(old="x=2", new="x=1")
        self.assertEqual(len(self.mems("revert")), 1)

    def test_fresh_correction(self):
        self.fresh_edit()
        self.assertEqual(len(self.fresh("prompt", text="that's wrong, use pathlib instead of os.path")), 1)
        self.assertEqual(self.fresh("prompt", text="that's wrong again"), [])

    def test_fresh_retry_once(self):
        self.fresh_cmd("make build", 1)
        self.fresh_cmd("make build -j1", 0)
        self.fresh_cmd("make build -v", 0)
        self.assertEqual(len(self.mems("retry")), 1)


if __name__ == "__main__":
    unittest.main()


class RevertQuoting(unittest.TestCase):
    """A grep pattern containing 'git revert' once produced a false revert memory (dogfooding, 2026-10-16)."""

    def run_cmds(self, *cmds):
        import tempfile
        from pathlib import Path
        from memcode import engine, store
        d = tempfile.mkdtemp()
        (Path(d) / "a.py").write_text("x = 1\n")
        con = store.connect(d)
        engine.prompt(con, d, "s", "change a.py")
        engine.tool_result(con, d, {"kind": "tool_result", "session": "s", "tool": "Edit",
                                    "input": {"file_path": "a.py", "old_string": "x = 1", "new_string": "x = 2"},
                                    "command": None, "file_path": "a.py", "exit_code": 0, "output": ""})
        for c in cmds:
            engine.tool_result(con, d, {"kind": "tool_result", "session": "s", "tool": "Bash", "input": {"command": c},
                                        "command": c, "file_path": None, "exit_code": 0, "output": ""})
        out = [r[0] for r in con.execute("SELECT trigger FROM memories")]
        con.close()
        return out

    def test_quoted_git_words_are_not_commands(self):
        self.assertEqual(self.run_cmds('grep -n "def _revert\\|git revert\\|restore" triggers.py | head',
                                       "echo 'git reset --hard'", 'git log --grep "git checkout"'), [])

    def test_real_reverts_still_detected(self):
        self.assertEqual(self.run_cmds("pytest -q && git checkout -- a.py"), ["revert"])
        self.assertEqual(self.run_cmds("git reset --hard"), ["revert"])


class ForeignWorktrees(unittest.TestCase):
    """Agent worktrees under .claude/worktrees/ are other checkouts: never anchors, never indexed (dogfooding)."""

    def test_worktree_edits_ignored_and_not_indexed(self):
        import tempfile
        from pathlib import Path
        from memcode import engine, store, tree
        d = tempfile.mkdtemp()
        wt = Path(d, ".claude", "worktrees", "agent-x", "memcode")
        wt.mkdir(parents=True)
        (wt / "scope.py").write_text("x = 1\n")
        (Path(d) / "a.py").write_text("y = 1\n")
        con = store.connect(d)
        tree.scan_repo(con, d)
        self.assertEqual([r[0] for r in con.execute("SELECT path FROM paths WHERE kind='file'")], ["a.py"])
        engine.prompt(con, d, "s", "fix it")
        ev = {"kind": "tool_result", "session": "s", "tool": "Bash", "input": {"command": "pytest -q"},
              "command": "pytest -q", "file_path": None, "exit_code": 1, "output": ""}
        engine.tool_result(con, d, ev)
        p = str(wt / "scope.py")
        engine.tool_result(con, d, {"kind": "tool_result", "session": "s", "tool": "Edit",
                                    "input": {"file_path": p, "old_string": "x = 1", "new_string": "x = 2"},
                                    "command": None, "file_path": p, "exit_code": 0, "output": ""})
        engine.tool_result(con, d, dict(ev, exit_code=0))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM memories").fetchone()[0], 0)
        con.close()


class NowRequest(unittest.TestCase):
    def test_requests_for_now_vs_standing_rules(self):
        from memcode.triggers import now_request
        now = [("Park G16. Start a review subagent on multitenant main, it should keep the backwork compatibility in "
                "mind with rest of the review points. keep in mind develop is still running in a different cluster "
                "and we can not touch it yet."),                                 # issue #33
               "Park G16. Start a review subagent on multitenant main.",
               "For this change only, call the new function temp_square.",
               "[user] okay, merge the branch and deploy to staging"]
        rules = ["Use pnpm, not npm.", "Add type hints to every new function.", "Always run tests before pushing.",
                 "Functions return a (value, error) tuple; they never raise.", "we indent with tabs in this repo",
                 "Keep backward compatibility in mind in reviews.", "Start every task on main."]
        for t in now:
            self.assertIsNotNone(now_request(t), t)
        for t in rules:
            self.assertIsNone(now_request(t), t)
