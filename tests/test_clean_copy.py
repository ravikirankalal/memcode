import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from bench.live import run
from memcode import store

ROOT = Path(__file__).resolve().parent.parent


class CleanCopy(unittest.TestCase):
    def test_only_memory_carries_over_and_rules_are_injected(self):
        sc = run.SCENARIOS[0]
        src = run.make_repo(sc)
        (src / "leaked_session1_code.py").write_text("x = 1\n")
        con = store.connect(src)
        store.add_memory(con, "correction", "Rule from user correction: Always use tabs. (context: ops.py)", "", None, {})
        con.close()
        dst = run.fresh_with_memory(sc, src, "memcode")
        self.assertFalse((dst / "leaked_session1_code.py").exists())      # session-1 code does not leak
        self.assertTrue((dst / ".memcode" / "memory.db").exists())        # memory does
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        out = subprocess.run([sys.executable, "-m", "memcode.hook_cli", "SessionStart"],
                             input=json.dumps({"session_id": "x", "cwd": str(dst)}),
                             capture_output=True, text=True, env=env).stdout
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("follow them", ctx)
        self.assertIn("- Always use tabs.", ctx)

    def test_claudemd_carries_over_for_baselines_not_nomem(self):
        sc = run.SCENARIOS[0]
        src = run.make_repo(sc)
        (src / "CLAUDE.md").write_text("Use tabs\n")
        self.assertTrue((run.fresh_with_memory(sc, src, "claudemd") / "CLAUDE.md").exists())
        self.assertFalse((run.fresh_with_memory(sc, src, "nomem") / "CLAUDE.md").exists())


if __name__ == "__main__":
    unittest.main()
