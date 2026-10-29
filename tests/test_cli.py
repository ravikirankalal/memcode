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
        self.a = store.add_memory(con, "correction", "Always use tabs.", "", None, {"s": 1})
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

    def test_edit_corrects_in_place_and_logs_the_old_text(self):
        code, out, _ = run(self.root, "edit", str(self.a), "Always use tabs, except in YAML.", "--topic", "convention")
        self.assertEqual((code, out.strip()), (0, f"edited #{self.a}"))
        con = store.connect(self.root)
        r = con.execute("SELECT * FROM memories WHERE id=?", (self.a,)).fetchone()
        self.assertEqual((r["text"], r["topic"], r["from_user"]), ("Always use tabs, except in YAML.", "convention", 1))
        con.close()
        _, hist, _ = run(self.root, "history", "-n", "1")
        self.assertIn("edit", hist); self.assertIn("was: Always use tabs.", hist)
        self.assertEqual(run(self.root, "edit", str(self.a), "Always use tabs, except in YAML.")[1].strip(),
                         f"#{self.a} unchanged")
        self.assertEqual(run(self.root, "edit", "999", "x")[0], 1)
        self.assertEqual(run(self.root, "edit", str(self.a), "   ")[0], 2)

    def test_edit_restates_a_decision_and_leaves_measured_commands_alone(self):
        import time
        from memcode import facts
        con = store.connect(self.root)
        d = store.add_memory(con, "agent", "G16 is parked.", "", None, {}, topic="decision", expires_at=time.time() + 5)
        facts.ensure(con)
        facts._upsert(con, "cmd:make check", "command", "test", "make check", "observed", ok=1, runs=1)
        cmd = con.execute("SELECT id FROM memories WHERE mkey='cmd:make check'").fetchone()[0]
        con.commit(); con.close()
        self.assertEqual(run(self.root, "edit", str(d), "G16 is parked until December.")[0], 0)
        con = store.connect(self.root)
        self.assertGreater(con.execute("SELECT expires_at FROM memories WHERE id=?", (d,)).fetchone()[0],
                           time.time() + 20 * 86400)
        con.close()
        self.assertEqual(run(self.root, "edit", str(cmd), "make test")[0], 2)

    def test_forget_removes_dependents(self):
        code, out, _ = run(self.root, "forget", str(self.a), "999")
        self.assertEqual(code, 1); self.assertIn("forgot 1 of 2", out)
        con = store.connect(self.root)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM retrievals").fetchone()[0], 0)
        con.close()

    def test_add_confines_path(self):
        code, _, _ = run(self.root, "add", "a note")
        self.assertEqual(code, 0)
        code, _, err = run(self.root, "add", "x", "--path", "../../etc/passwd")
        self.assertEqual(code, 2); self.assertIn("outside repository", err)

    def test_stats_export_prune(self):
        _, out, _ = run(self.root, "stats")
        self.assertIn("memories: 2 (1 from you, 1 stale, 0 links)", out)
        _, out, _ = run(self.root, "export")
        data = json.loads(out)
        self.assertEqual(len(data), 2); self.assertIsInstance(data[0]["provenance"], dict)
        self.assertIn("pruned 1", run(self.root, "prune-stale")[1])
        self.assertIn("memories: 1 (1 from you, 0 stale, 0 links)", run(self.root, "stats")[1])


if __name__ == "__main__":
    unittest.main()
