"""Day one: the memory agent reads the repository's key files once (agent/bootstrap.py)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memcode import store  # noqa: E402
from memcode.agent import bootstrap  # noqa: E402


class Bootstrap(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", "-b", "develop", self.d], check=True)
        Path(self.d, "README.md").write_text("# Shop\nCheckout service. Release steps: docs/RELEASING.md\n")
        Path(self.d, "CLAUDE.md").write_text("Always use tabs.\n")
        Path(self.d, ".github", "workflows").mkdir(parents=True)
        Path(self.d, ".github", "workflows", "deploy.yml").write_text("on:\n  push:\n    tags: ['v*']\n")
        Path(self.d, "docs").mkdir()
        Path(self.d, "docs", "RELEASING.md").write_text("Run scripts/release.sh VERSION.\n")
        subprocess.run(["git", "-C", self.d, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.d, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm",
                        "feat(checkout): first cut"], check=True)

    def test_gather_reads_the_key_files_but_not_claude_md(self):
        text = bootstrap.gather(self.d)
        self.assertIn("[read] README.md | # Shop Checkout service.", text)
        self.assertIn("[read] .github/workflows/deploy.yml | on: push: tags: ['v*']", text)
        self.assertIn("[read] docs/RELEASING.md | Run scripts/release.sh VERSION.", text)
        self.assertNotIn("Always use tabs", text)                           # Claude Code already gives it
        self.assertIn("[ran] `git branch -a` -> ok | develop", text)
        self.assertIn("feat(checkout): first cut", text)
        self.assertTrue(all(len(l) < 2000 for l in text.splitlines()))

    def test_run_stores_the_profile_and_says_so(self):
        seen = {}

        def fake(text, ctx):
            seen["ctx"] = ctx
            return {"items": [{"op": "add", "target": 0, "from_user": False, "topic": "deployment", "subject": "",
                               "importance": 4, "text": "Tags v* trigger .github/workflows/deploy.yml.",
                               "evidence": "on: push: tags: ['v*']", "path": "", "links": [], "unusual": False,
                               "conflicts": False},
                              {"op": "add", "target": 0, "from_user": True, "topic": "convention", "subject": "",
                               "importance": 5, "text": "Always use tabs.", "evidence": "first cut", "path": "",
                               "links": [], "unusual": False, "conflicts": False}],
                    "model": "fake", "cost_usd": 0.002}
        ids = bootstrap.run(self.d, fake)
        self.assertEqual(len(ids), 1)                                        # nothing is from_user without [user] lines
        self.assertIn("not a session transcript", seen["ctx"])
        con = store.connect(self.d)
        r = con.execute("SELECT * FROM memories WHERE id=?", (ids[0],)).fetchone()
        self.assertEqual((r["topic"], r["from_user"]), ("deployment", 0))
        con.close()
        feed = json.loads(Path(self.d, ".memcode", "activity.json").read_text())
        self.assertEqual(feed["events"][-1]["text"], "read the repository: 2 candidates, kept 1")


if __name__ == "__main__":
    unittest.main()
