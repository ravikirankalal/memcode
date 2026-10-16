import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from memcode import adapters, store

ROOT = Path(__file__).resolve().parent.parent


def hook(root, event, payload, agent=None):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    env.pop("CLAUDE_PROJECT_DIR", None)
    env = {k: v for k, v in env.items() if not k.startswith("MEMCODE_")}
    argv = [sys.executable, "-m", "memcode.hook_cli", event] + ([agent] if agent else [])
    p = subprocess.run(argv, env=env, text=True, capture_output=True, input=json.dumps(dict(payload, cwd=root)))
    return json.loads(p.stdout) if p.stdout.strip() else None


class Normalize(unittest.TestCase):
    def test_codex_shell_has_no_exit_code(self):
        # shape from codex-rs unified_exec post_tool_use_payload: tool_response is the output string
        act, evs = adapters.normalize("codex", "PostToolUse", {
            "session_id": "s", "tool_name": "Bash", "tool_input": {"command": "pytest -q"},
            "tool_response": "1 failed", "tool_use_id": "c1", "turn_id": "t"})
        self.assertEqual(act, "tool")
        self.assertEqual(evs[0]["command"], "pytest -q")
        self.assertIsNone(evs[0]["exit_code"])

    def test_codex_apply_patch_becomes_one_edit_per_file(self):
        patch = ("*** Begin Patch\n*** Update File: src/a.py\n@@\n-x\n+y\n*** Add File: src/b.py\n+z\n"
                 "*** Update File: src/a.py\n*** End Patch\n")
        act, evs = adapters.normalize("codex", "PostToolUse", {
            "session_id": "s", "tool_name": "apply_patch", "tool_input": {"command": patch}, "tool_response": "ok"})
        self.assertEqual([(e["tool"], e["file_path"]) for e in evs], [("Edit", "src/a.py"), ("Edit", "src/b.py")])

    def test_gemini_events(self):
        self.assertEqual(adapters.normalize("gemini", "BeforeAgent", {"prompt": "hi"}), ("prompt", "hi"))
        self.assertEqual(adapters.normalize("gemini", "PreCompress", {})[0], "prepare")
        _, evs = adapters.normalize("gemini", "AfterTool", {
            "tool_name": "run_shell_command", "tool_input": {"command": "make"},
            "tool_response": {"llmContent": "Command: make\nExit Code: 2\nOutput: boom"}})
        self.assertEqual((evs[0]["tool"], evs[0]["exit_code"]), ("Bash", 2))
        _, evs = adapters.normalize("gemini", "AfterTool", {
            "tool_name": "run_shell_command", "tool_input": {"command": "make"}, "tool_response": {"llmContent": "ok"}})
        self.assertIsNone(evs[0]["exit_code"])                  # unknown, not guessed
        _, evs = adapters.normalize("gemini", "AfterTool", {
            "tool_name": "replace", "tool_input": {"file_path": "a.py"}, "tool_response": {}})
        self.assertEqual((evs[0]["tool"], evs[0]["file_path"]), ("Edit", "a.py"))

    def test_unknown_event_is_ignored(self):
        self.assertEqual(adapters.normalize("codex", "Stop", {}), ("none", None))
        self.assertEqual(adapters.normalize("claude", "BeforeAgent", {}), ("none", None))

    def test_claude_unchanged(self):
        _, evs = adapters.normalize("claude", "PostToolUseFailure", {
            "tool_name": "Bash", "tool_input": {"command": "pytest"}, "error": "Exit code 3\nboom"})
        self.assertEqual(evs[0]["exit_code"], 3)


class EndToEnd(unittest.TestCase):
    """A rule stated in one agent's prompt comes back at that agent's next session start."""

    def check(self, agent, prompt_event, tool_event, edit):
        d = tempfile.mkdtemp()
        (Path(d) / "app.py").write_text("x = 1\n")
        hook(d, "SessionStart", {"session_id": "s1", "source": "startup"}, agent)
        hook(d, prompt_event, {"session_id": "s1", "prompt": "Add a helper to app.py"}, agent)
        hook(d, tool_event, dict(edit, session_id="s1"), agent)      # the agent acts (in its own tool format)
        hook(d, prompt_event, {"session_id": "s1", "prompt": "No, always use tabs for indentation in this repo."},
             agent)
        out = hook(d, "SessionStart", {"session_id": "s2", "source": "startup"}, agent)
        self.assertIsNotNone(out, agent)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("tabs", out["hookSpecificOutput"]["additionalContext"])

    def test_codex(self):
        self.check("codex", "UserPromptSubmit", "PostToolUse", {
            "tool_name": "apply_patch", "tool_response": "Success",
            "tool_input": {"command": "*** Begin Patch\n*** Update File: app.py\n@@\n-x = 1\n+x = 2\n*** End Patch\n"}})

    def test_gemini(self):
        self.check("gemini", "BeforeAgent", "AfterTool", {
            "tool_name": "replace", "tool_input": {"file_path": "app.py", "old_string": "x = 1", "new_string": "x = 2"},
            "tool_response": {"llmContent": "ok"}})

    def test_codex_failed_output_is_not_mistaken_for_success_or_failure(self):
        d = tempfile.mkdtemp()
        for out in ("FAILED test_a", "passed"):
            hook(d, "PostToolUse", {"session_id": "s", "tool_name": "Bash", "tool_input": {"command": "pytest"},
                                    "tool_response": out}, "codex")
        con = store.connect(d)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM memories").fetchone()[0], 0)
        con.close()


if __name__ == "__main__":
    unittest.main()


class Setup(unittest.TestCase):
    def test_codex_config_is_valid_toml_with_codex_shape(self):
        import tomllib
        from memcode import setup
        cfg = tomllib.loads(setup.render("codex"))
        self.assertEqual(cfg["mcp_servers"]["memcode"]["args"][-1], "mcp")
        for event in ("SessionStart", "UserPromptSubmit", "PostToolUse", "PreCompact"):
            h = cfg["hooks"][event][0]["hooks"][0]
            self.assertEqual(h["type"], "command")
            self.assertTrue(h["command"].endswith(f"hook {event} codex"))
        self.assertEqual(cfg["hooks"]["PostToolUse"][0]["matcher"], "Bash|apply_patch")

    def test_gemini_config_is_valid_json(self):
        from memcode import setup
        text = setup.render("gemini")
        cfg = json.loads(text.split("\n", 1)[1])
        self.assertEqual(sorted(cfg["hooks"]), ["AfterTool", "BeforeAgent", "PreCompress", "SessionStart"])
        self.assertEqual(cfg["hooks"]["SessionStart"][0]["hooks"][0]["timeout"], 30000)

    def test_unknown_agent(self):
        from memcode import setup
        with self.assertRaises(ValueError):
            setup.render("cursor")

    def test_launcher_runs_hook_and_mcp(self):
        d = tempfile.mkdtemp()
        env = {k: v for k, v in os.environ.items() if not k.startswith("MEMCODE_") and k != "CLAUDE_PROJECT_DIR"}
        env.pop("PYTHONPATH", None)
        launcher = str(ROOT / "bin" / "memcode")
        p = subprocess.run([sys.executable, launcher, "hook", "SessionStart", "codex"], env=env, text=True,
                           capture_output=True, input=json.dumps({"session_id": "s", "cwd": d}), cwd=d)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((Path(d) / ".memcode" / "memory.db").exists())
        p = subprocess.run([sys.executable, launcher, "mcp"], env=dict(env, CLAUDE_PROJECT_DIR=d), text=True,
                           capture_output=True, cwd=d,
                           input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n")
        self.assertIn("memory_search", p.stdout)
