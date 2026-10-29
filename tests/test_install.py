"""Installation robustness: the launcher keeps the user's repository off the import path; an old Python says so."""
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "bin" / "memcode"


def launcher_module():
    loader = importlib.machinery.SourceFileLoader("memcode_launcher", str(LAUNCHER))
    spec = importlib.util.spec_from_loader("memcode_launcher", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Launcher(unittest.TestCase):
    def test_a_repo_cannot_shadow_memcodes_imports(self):
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", d], check=True)
        Path(d, "json.py").write_text("raise SystemExit('the repo shadowed json')\n")     # would break `-m`
        Path(d, "memcode").mkdir()
        Path(d, "memcode", "__init__.py").write_text("raise SystemExit('the repo shadowed memcode')\n")
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env.update(MEMCODE_TRANSCRIPT_CAPTURE="0", CLAUDE_PROJECT_DIR=d)
        p = subprocess.run([sys.executable, str(LAUNCHER), "hook", "SessionStart"], cwd=d, env=env, text=True,
                           input=json.dumps({"session_id": "s1", "cwd": d}), capture_output=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("shadowed", p.stdout + p.stderr)
        self.assertTrue(Path(d, ".memcode", "memory.db").exists())
        q = subprocess.run([sys.executable, str(LAUNCHER), "--root", d, "stats"], cwd=d, env=env, text=True,
                           capture_output=True, timeout=60)
        self.assertEqual(q.returncode, 0, q.stderr)

    def test_hooks_and_mcp_start_through_the_launcher(self):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
        for event, entries in hooks.items():
            for h in entries[0]["hooks"]:
                self.assertEqual(h["command"], f'python3 "${{CLAUDE_PLUGIN_ROOT}}/bin/memcode" hook {event}')
        mcp = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["mcpServers"]["memcode"]
        self.assertEqual(mcp, {"command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/bin/memcode", "mcp"]})

    def test_an_old_python_gets_one_clear_message(self):
        mod = launcher_module()
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(mod._too_old(["hook", "SessionStart"]), 0)
        msg = json.loads(out.getvalue())["systemMessage"]
        self.assertIn("memcode needs Python %d.%d or newer" % mod.MIN_PYTHON, msg)
        self.assertEqual(mod._too_old(["hook", "Stop"]), 0)                  # silent: never break the agent
        self.assertEqual(mod._too_old(["mcp"]), 0)


if __name__ == "__main__":
    unittest.main()


class Doctor(unittest.TestCase):
    def setUp(self):
        from memcode import store
        self.d = tempfile.mkdtemp()
        self.con = store.connect(self.d)

    def tearDown(self):
        self.con.close()

    def test_welcome_once_then_quiet(self):
        from unittest import mock
        from memcode import doctor
        with mock.patch.dict(os.environ, {"MEMCODE_TRANSCRIPT_CAPTURE": "0"}):
            first = doctor.at_start(self.con, self.d)
            second = doctor.at_start(self.con, self.d)
        self.assertEqual(first, [doctor.WELCOME])
        self.assertIn("/plugin install memcode-status@memcode", first[0])
        self.assertEqual(second, [])

    def test_a_missing_claude_cli_and_new_errors_are_told_once(self):
        from unittest import mock
        from memcode import doctor, store
        from memcode.config import write
        write(self.d, welcomed=True)
        Path(store.memdir(self.d), "error.log").write_text("2026-10-29 10:00:00 OSError: disk full\n")
        with mock.patch.dict(os.environ, {"MEMCODE_TRANSCRIPT_CAPTURE": "1"}), \
                mock.patch("shutil.which", lambda name: None):
            msgs = doctor.at_start(self.con, self.d)
            again = doctor.at_start(self.con, self.d)
        self.assertTrue(any("`claude` CLI is not on PATH" in m for m in msgs))
        self.assertTrue(any("logged 1 error since the last session (newest: 2026-10-29 10:00:00 OSError: disk full)"
                            in m for m in msgs))
        self.assertFalse(any("logged" in m for m in again))                  # each error is told once

    def test_the_session_start_hook_shows_the_user_a_message(self):
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env.update(MEMCODE_TRANSCRIPT_CAPTURE="0")
        run = lambda: subprocess.run([sys.executable, str(LAUNCHER), "hook", "SessionStart"], env=env, text=True,
                                     input=json.dumps({"session_id": "s1", "cwd": self.d}), capture_output=True,
                                     timeout=60).stdout
        out = json.loads(run())
        self.assertIn("memcode is on for this repository", out["systemMessage"])
        later = run().strip()
        self.assertNotIn("systemMessage", json.loads(later) if later else {})

    def test_doctor_command(self):
        from unittest import mock
        from memcode import cli
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.dict(os.environ, {"MEMCODE_TRANSCRIPT_CAPTURE": "0"}):
            code = cli.main(["--root", self.d, "doctor"])
        self.assertEqual(code, 0)
        self.assertRegex(out.getvalue(), r"ok\s+sqlite\s+\S+ with JSON")
        self.assertIn("recall        on", out.getvalue())
        self.assertIn("no session start recorded", out.getvalue())
