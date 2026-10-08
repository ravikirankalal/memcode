import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from memcode import cli, store


def run(root, *argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(["--root", root, *argv])
    return code, out.getvalue(), err.getvalue()


class Cli(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        con = store.connect(self.root)
        self.a = store.add_memory(con, "correction", "Rule from user correction: Always use tabs.", "", None, {"s": 1})
        self.b = store.add_memory(con, "fail_to_fix", "pytest failed then passed", "a.py", "h", {})
        con.execute("UPDATE memories SET stale=1 WHERE id=?", (self.b,))
        con.execute("INSERT INTO retrievals(session,memory_id,ts) VALUES('x',?,0)", (self.a,))
        con.commit(); con.close()

    def test_list_hides_stale_unless_all(self):
        _, out, _ = run(self.root, "list")
        self.assertIn("Always use tabs", out); self.assertNotIn("pytest failed", out)
        _, out, _ = run(self.root, "list", "--all")
        self.assertIn("[stale]", out)

    def test_show_and_missing(self):
        code, out, _ = run(self.root, "show", str(self.a))
        self.assertEqual(code, 0); self.assertIn("retrievals=1", out); self.assertIn("(repo-wide)", out)
        self.assertEqual(run(self.root, "show", "999")[0], 1)

    def test_forget_removes_dependents(self):
        code, out, _ = run(self.root, "forget", str(self.a), "999")
        self.assertEqual(code, 1); self.assertIn("forgot 1 of 2", out)
        con = store.connect(self.root)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM retrievals").fetchone()[0], 0)
        con.close()

    def test_add_redacts_and_confines_path(self):
        code, _, _ = run(self.root, "add", "key AKIAIOSFODNN7EXAMPLE here")
        self.assertEqual(code, 0)
        con = store.connect(self.root)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", " ".join(r["text"] for r in store.list_memories(con)))
        con.close()
        code, _, err = run(self.root, "add", "x", "--path", "../../etc/passwd")
        self.assertEqual(code, 2); self.assertIn("outside repository", err)

    def test_stats_export_prune(self):
        _, out, _ = run(self.root, "stats")
        self.assertIn("memories: 2 (1 stale)", out)
        _, out, _ = run(self.root, "export")
        data = json.loads(out)
        self.assertEqual(len(data), 2); self.assertIsInstance(data[0]["provenance"], dict)
        self.assertIn("pruned 1", run(self.root, "prune-stale")[1])
        self.assertIn("memories: 1 (0 stale)", run(self.root, "stats")[1])


if __name__ == "__main__":
    unittest.main()
