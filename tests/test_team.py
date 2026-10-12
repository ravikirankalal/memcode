import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from memcode import cli, pinned, retrieval, store, team, tree

ROOT = Path(__file__).resolve().parent.parent


def repo():
    d = tempfile.mkdtemp()
    (Path(d) / "billing").mkdir()
    (Path(d) / "billing" / "invoice.py").write_text("def total(items):\n    return sum(items)\n")
    return d


class TwoDevelopers(unittest.TestCase):
    """Alice learns a rule; she shares it; Bob (a clone with no local store) gets it after 'git pull'."""

    def setUp(self):
        self.alice = repo()
        self.bob = repo()
        self.a = store.connect(self.alice)
        self.b = store.connect(self.bob)
        self.rule = store.add_memory(self.a, "correction", "Rule from user correction: Every module under billing/ "
                                     "starts with '# PCI-SCOPE'.", "", None, {"session": "s1"}, 0.6)
        self.note = store.add_memory(self.a, "fail_to_fix", "rounding broke tests until cents were integers",
                                     "billing/invoice.py", store.sha1(b"def total(items):\n    return sum(items)\n"),
                                     {"session": "s1"})

    def tearDown(self):
        self.a.close(); self.b.close()

    def pull(self):
        shutil.copy(team.path(self.alice), team.path(self.bob))

    def test_share_then_pull_imports_once(self):
        tids = team.share(self.a, self.alice, [self.rule, self.note])
        self.assertEqual(len(tids), 2)
        lines = Path(team.path(self.alice)).read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertNotIn("session", lines[0])                   # no session provenance leaves the machine
        self.pull()
        self.assertEqual(team.sync(self.b, self.bob)["added"], 2)
        self.assertEqual(team.sync(self.b, self.bob)["added"], 0)  # idempotent
        texts = {r["text"] for r in self.b.execute("SELECT text FROM memories")}
        self.assertIn("rounding broke tests until cents were integers", texts)
        block = pinned.render_pinned(self.b, self.bob)
        self.assertIn("PCI-SCOPE", block.split(pinned.NOTES_OPEN)[0])   # team rule renders as a rule

    def test_sharer_does_not_get_a_duplicate(self):
        team.share(self.a, self.alice, [self.rule])
        self.assertEqual(team.sync(self.a, self.alice)["added"], 0)
        self.assertEqual(self.a.execute("SELECT COUNT(*) FROM memories").fetchone()[0], 2)

    def test_identical_local_memory_is_linked_not_copied(self):
        store.add_memory(self.b, "correction", "Rule from user correction: Every module under billing/ "
                         "starts with '# PCI-SCOPE'.", "", None, {})
        team.share(self.a, self.alice, [self.rule])
        self.pull()
        self.assertEqual(team.sync(self.b, self.bob)["added"], 0)
        self.assertEqual(self.b.execute("SELECT COUNT(*) FROM memories").fetchone()[0], 1)

    def test_removed_line_removes_imported_copy_but_not_the_authors_memory(self):
        tid = team.share(self.a, self.alice, [self.rule])[0]
        self.pull(); team.sync(self.b, self.bob)
        self.assertEqual(team.unshare(self.a, self.alice, [tid]), 1)
        self.pull()
        self.assertEqual(team.sync(self.b, self.bob)["removed"], 1)
        self.assertEqual(self.b.execute("SELECT COUNT(*) FROM memories").fetchone()[0], 0)
        team.sync(self.a, self.alice)
        self.assertIsNotNone(self.a.execute("SELECT id FROM memories WHERE id=?", (self.rule,)).fetchone())

    def test_unshare_by_local_id(self):
        team.share(self.a, self.alice, [self.rule])
        self.assertEqual(team.unshare(self.a, self.alice, [str(self.rule)]), 1)
        self.assertEqual(team.read(self.alice), [])

    def test_imported_note_goes_stale_when_teammates_file_differs(self):
        team.share(self.a, self.alice, [self.note])
        self.pull()
        (Path(self.bob) / "billing" / "invoice.py").write_text("def total(items):\n    return round(sum(items))\n")
        team.sync(self.b, self.bob)
        tree.scan_repo(self.b, self.bob); tree.mark_stale(self.b, self.bob)
        self.assertEqual(self.b.execute("SELECT stale FROM memories").fetchone()[0], 1)

    def test_retrieval_finds_team_memory(self):
        team.share(self.a, self.alice, [self.rule])
        self.pull(); team.sync(self.b, self.bob)
        os.environ.pop("MEMCODE_RANK", None)
        ids = [r["text"] for _, r in retrieval.score(self.b, self.bob, "s", "Create billing/refunds.py")]
        self.assertTrue(any("PCI-SCOPE" in t for t in ids))

    def test_stale_memory_is_not_shared(self):
        self.a.execute("UPDATE memories SET stale=1 WHERE id=?", (self.note,)); self.a.commit()
        with self.assertRaises(ValueError):
            team.share(self.a, self.alice, [self.note])

    def test_disabled_by_env(self):
        team.share(self.a, self.alice, [self.rule])
        self.pull()
        os.environ["MEMCODE_TEAM"] = "0"
        try:
            self.assertEqual(team.sync(self.b, self.bob)["added"], 0)
        finally:
            del os.environ["MEMCODE_TEAM"]


class UntrustedFile(unittest.TestCase):
    """The team file is repo content: malformed or hostile lines are skipped, secrets are redacted."""

    def test_bad_lines_are_skipped(self):
        d = repo()
        Path(team.path(d)).write_text("\n".join([
            "not json",
            json.dumps({"trigger": "correction", "text": "ok rule", "anchor_path": ""}),
            json.dumps({"trigger": "exec", "text": "bad trigger"}),
            json.dumps({"trigger": "manual", "text": "escape", "anchor_path": "../../etc/passwd"}),
            json.dumps({"trigger": "manual", "text": "token: password=hunter22", "anchor_path": "billing"}),
            json.dumps(["list"]),
        ]) + "\n")
        recs = team.read(d)
        self.assertEqual(len(recs), 2)
        self.assertEqual(recs[0]["text"], "ok rule")
        self.assertNotIn("hunter22", recs[1]["text"]); self.assertIn("[REDACTED]", recs[1]["text"])
        con = store.connect(d)
        self.assertEqual(team.sync(con, d)["added"], 2)
        con.close()

    def test_missing_file_is_fine(self):
        d = repo()
        con = store.connect(d)
        self.assertEqual(team.sync(con, d), {"records": 0, "added": 0, "removed": 0})
        con.close()


class Hook(unittest.TestCase):
    def test_session_start_imports_team_file(self):
        d = repo()
        Path(team.path(d)).write_text(json.dumps({"trigger": "correction", "text":
                                                  "Rule from user correction: Use tabs in billing/.",
                                                  "anchor_path": "", "id": "abc123"}) + "\n")
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        env.pop("CLAUDE_PROJECT_DIR", None)
        p = subprocess.run([sys.executable, "-m", "memcode.hook_cli", "SessionStart"], env=env, text=True,
                           input=json.dumps({"session_id": "s1", "cwd": d}), capture_output=True)
        ctx = json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Use tabs in billing/.", ctx)


class Dashboard(unittest.TestCase):
    def test_team_command_suggests_rules(self):
        d = repo()
        con = store.connect(d)
        mid = store.add_memory(con, "correction", "Rule from user correction: Use tabs.", "", None, {})
        con.close()
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.main(["--root", d, "team"]), 0)
            self.assertEqual(cli.main(["--root", d, "share", str(mid)]), 0)
            self.assertEqual(cli.main(["--root", d, "team"]), 0)
        text = out.getvalue()
        self.assertIn("not created yet", text)
        self.assertIn(f"#{mid}", text)
        self.assertIn("1 shared memories (1 rules)", text)


if __name__ == "__main__":
    unittest.main()
