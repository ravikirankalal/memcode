import json
import unittest

from bench.live import metrics


def ev(*cmds):
    return [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": c}} for c in cmds]}},
        {"type": "result", "session_id": "s", "total_cost_usd": 0.01}]


class T(unittest.TestCase):
    def test_metrics(self):
        m = metrics.metrics(ev("ls", "python -m unittest", "pytest -q"), r"unittest")
        self.assertTrue(m["trap_hit"])
        self.assertEqual((m["explore_calls"], m["bash_calls"], m["session_id"]), (1, 3, "s"))

    def test_clean_and_parse(self):
        text = "\n".join(json.dumps(e) for e in ev("pytest -q")) + "\nnoise"
        m = metrics.metrics(metrics.parse_stream(text), r"unittest")
        self.assertFalse(m["trap_hit"])
        self.assertEqual(metrics.summarize([m])["trap_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()


class Heredoc(unittest.TestCase):
    def test_multiline_commit_with_prefix_is_not_a_trap(self):
        cmd = "git add x && git commit -F - <<'EOF'\nPROJ-101: msg\nEOF"
        m = metrics.metrics(ev(cmd), r"git commit(?!.*PROJ-\d+:)")
        self.assertFalse(m["trap_hit"])
        bad = metrics.metrics(ev("git commit -m 'oops'"), r"git commit(?!.*PROJ-\d+:)")
        self.assertTrue(bad["trap_hit"])
        self.assertIn("git commit", bad["evidence"])


def wr(name, **inp):
    return [{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}},
            {"type": "result", "session_id": "s", "total_cost_usd": 0}]


class Fragments(unittest.TestCase):
    RX = r"\A(?!# Copyright Acme)|\bimport os\b"

    def test_header_clause_ignores_edit_fragments_but_judges_whole_files(self):
        self.assertFalse(metrics.metrics(wr("Edit", new_string="    path = Path(root) / name"), self.RX, "content")["trap_hit"])
        self.assertTrue(metrics.metrics(wr("Write", content="def f():\n  pass\n"), self.RX, "content")["trap_hit"])
        self.assertFalse(metrics.metrics(wr("Write", content="# Copyright Acme\ndef f():\n  pass\n"), self.RX, "content")["trap_hit"])

    def test_non_anchored_clauses_still_judge_fragments(self):
        m = metrics.metrics(wr("Edit", new_string="import os\n"), self.RX, "content")
        self.assertTrue(m["trap_hit"]); self.assertIn("import os", m["evidence"])


class TrapPath(unittest.TestCase):
    def test_only_files_under_the_path_are_judged(self):
        ev = [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Write", "input": {"file_path": "/r/tests/test_refunds.py", "content": "def t(): pass\n"}},
            {"type": "tool_use", "name": "Write", "input": {"file_path": "/r/billing/refunds.py", "content": "# PCI-SCOPE\nx = 1\n"}}]}},
            {"type": "result", "session_id": "s", "total_cost_usd": 0}]
        rx = r"\A(?!# PCI-SCOPE)"
        self.assertTrue(metrics.metrics(ev, rx, "content")["trap_hit"])                          # test file lacks header
        self.assertFalse(metrics.metrics(ev, rx, "content", trap_path=r"(^|/)billing/")["trap_hit"])  # only billing/ judged


class ArmEnv(unittest.TestCase):
    def test_arms_do_not_inherit_memcode_flags(self):
        import os
        from unittest import mock
        from bench.live import run
        seen = {}
        def fake_run(cmd, cwd=None, capture_output=None, text=None, timeout=None, env=None):
            seen.update(env)
            class P: stdout = ""
            return P()
        with mock.patch.dict(os.environ, {"MEMCODE_RETRIEVAL": "1", "MEMCODE_RANK": "salience"}), \
             mock.patch.object(run.subprocess, "run", fake_run):
            run.claude(run.Path("/tmp"), "x", "haiku", "memcode")
        self.assertNotIn("MEMCODE_RETRIEVAL", seen); self.assertNotIn("MEMCODE_RANK", seen)
