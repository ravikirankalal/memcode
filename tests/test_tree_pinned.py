import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memcode import pinned, salience, store, tree  # noqa: E402


def git(root, *a):
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t",
                    *a], check=True, capture_output=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        git(self.root, "init", "-q")
        (self.root / ".gitignore").write_text("ignored.txt\n.memcode/\n")
        (self.root / "src").mkdir()
        (self.root / "src/a.py").write_text("print('a')\n" * 20)
        (self.root / "src/b.py").write_text("b = 1\n")
        (self.root / "docs").mkdir()
        (self.root / "docs/x.md").write_text("x\n")
        (self.root / "ignored.txt").write_text("nope")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "init")
        self.con = store.connect(self.root)

    def tearDown(self):
        self.con.close()
        self.td.cleanup()

    def paths(self):
        return {r["path"]: r for r in self.con.execute("SELECT * FROM paths")}


class TestScan(Base):
    def test_scan(self):
        tree.scan_repo(self.con, self.root)
        p = self.paths()
        self.assertIn("src/a.py", p)
        self.assertEqual(p["src"]["kind"], "dir")
        self.assertEqual(p["src/a.py"]["parent"], "src")
        self.assertEqual(p["src/b.py"]["content_hash"], store.sha1("b = 1\n"))
        self.assertNotIn("ignored.txt", p)
        self.assertFalse(any(k.startswith(".memcode") or k.startswith(".git/") for k in p))

    def test_walk_fallback(self):
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules/z.js").write_text("1")
        orig = tree._git
        tree._git = lambda *a, **k: None
        try:
            tree.scan_repo(self.con, self.root)
        finally:
            tree._git = orig
        p = self.paths()
        self.assertIn("src/a.py", p)
        self.assertNotIn("node_modules/z.js", p)

    def test_rename_reanchors(self):
        tree.scan_repo(self.con, self.root)
        h = self.paths()["src/a.py"]["content_hash"]
        mid = store.add_memory(self.con, "correction", "use a", "src/a.py", h)
        git(self.root, "mv", "src/a.py", "src/c.py")
        git(self.root, "commit", "-qam", "mv")
        res = tree.refresh_from_git_diff(self.con, self.root, "HEAD~1")
        self.assertEqual(res["renamed"], 1)
        m = self.con.execute("SELECT * FROM memories WHERE id=?", (mid,)).fetchone()
        self.assertEqual(m["anchor_path"], "src/c.py")
        p = self.paths()
        self.assertNotIn("src/a.py", p)
        self.assertIn("src/c.py", p)
        self.assertEqual(tree.mark_stale(self.con, self.root), 0)

    def test_staleness(self):
        tree.scan_repo(self.con, self.root)
        p = self.paths()
        m1 = store.add_memory(self.con, "manual", "t1", "src/a.py", p["src/a.py"]["content_hash"])
        m2 = store.add_memory(self.con, "manual", "t2", "src/b.py", p["src/b.py"]["content_hash"])
        m3 = store.add_memory(self.con, "manual", "t3", "docs/x.md", p["docs/x.md"]["content_hash"])
        m4 = store.add_memory(self.con, "manual", "nohash", "src/b.py", None)
        self.assertEqual(tree.mark_stale(self.con, self.root), 0)
        (self.root / "src/a.py").write_text("changed")
        os.remove(self.root / "docs/x.md")
        self.assertEqual(tree.mark_stale(self.con, self.root), 2)
        st = {r["id"]: r["stale"] for r in self.con.execute("SELECT id, stale FROM memories")}
        self.assertEqual(st, {m1: 1, m2: 0, m3: 1, m4: 0})
        os.remove(self.root / "src/b.py")
        tree.mark_stale(self.con, self.root)
        st = {r["id"]: r["stale"] for r in self.con.execute("SELECT id, stale FROM memories")}
        self.assertEqual((st[m2], st[m4]), (1, 0))

    def test_refresh_modify_delete_add(self):
        tree.scan_repo(self.con, self.root)
        (self.root / "src/b.py").write_text("b = 2\n")
        os.remove(self.root / "docs/x.md")
        (self.root / "new.py").write_text("n")
        res = tree.refresh_from_git_diff(self.con, self.root)
        p = self.paths()
        self.assertEqual(p["src/b.py"]["content_hash"], store.sha1("b = 2\n"))
        self.assertNotIn("docs/x.md", p)
        self.assertNotIn("docs", p)
        self.assertIn("new.py", p)
        self.assertEqual(res["deleted"], 1)


class TestPinned(Base):
    def seed(self):
        tree.scan_repo(self.con, self.root)
        store.upsert_path(self.con, "src", "dir", annotation="core code")
        store.add_memory(self.con, "correction", "always use pathlib", "src/a.py")
        store.add_memory(self.con, "fail_to_fix", "build breaks without X", "src/b.py")
        s = store.add_memory(self.con, "manual", "stale one", "docs/x.md", "deadbeef")
        self.con.execute("UPDATE memories SET stale=1 WHERE id=?", (s,))
        self.con.commit()

    def test_content_and_stale_excluded(self):
        self.seed()
        out = pinned.render_pinned(self.con, self.root)
        self.assertIn("core code", out)
        self.assertIn("## Conventions", out)
        self.assertIn("always use pathlib", out)
        self.assertIn("build breaks without X", out)
        self.assertNotIn("stale one", out)
        self.assertIn("docs/ (1 files)", out)  # cold dir collapsed

    def test_cap(self):
        self.seed()
        for i in range(200):
            store.add_memory(self.con, "manual", f"memory number {i} " + "word " * 20,
                             f"src/f{i}.py")
        for cap in (50, 200, 500, 1500):
            out = pinned.render_pinned(self.con, self.root, token_cap=cap)
            self.assertLessEqual(len(out) / 4, cap)
        self.assertGreater(len(pinned.render_pinned(self.con, self.root, 1500)), 400)

    def test_deterministic(self):
        self.seed()
        a = pinned.render_pinned(self.con, self.root)
        con2 = store.connect(self.root)
        b = pinned.render_pinned(con2, self.root)
        con2.close()
        self.assertEqual(a, b)
        tree.scan_repo(self.con, self.root)
        self.assertEqual(a, pinned.render_pinned(self.con, self.root))


class TestSalience(Base):
    def test_range_and_decay(self):
        tree.scan_repo(self.con, self.root)
        now = time.time()
        ids = [store.add_memory(self.con, t, "m", "src/a.py", confidence=c)
               for t, c in [("fail_to_fix", 1.7), ("correction", -3), ("revert", 0.5)]]
        for r in self.con.execute("SELECT * FROM memories").fetchall():
            for k, v in salience.compute(self.con, r).items():
                self.assertTrue(0.0 <= v <= 1.0, (k, v))
        rows = {r["trigger"]: r for r in self.con.execute("SELECT * FROM memories")}
        self.assertGreater(salience.compute(self.con, rows["fail_to_fix"])["surprise"],
                           salience.compute(self.con, rows["correction"])["surprise"])
        self.assertGreater(salience.compute(self.con, rows["correction"])["friction"],
                           salience.compute(self.con, rows["fail_to_fix"])["friction"])
        r0 = salience.rollup(self.con, now)
        self.assertIn("src/a.py", r0)
        self.assertIn("src", r0)
        self.assertIn("", r0)
        r14 = salience.rollup(self.con, now + 14 * 86400)
        # one revert: weight 1 -> 0.5 after a half-life
        self.assertAlmostEqual(r14["src"], 1 - (2.718281828459045 ** -0.5), places=3)
        self.assertLess(r14["src"], r0["src"])
        self.assertEqual(salience.log_all(self.con, now), 3)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM salience_log").fetchone()[0], 3)

    def test_reinforce_cap(self):
        mid = store.add_memory(self.con, "manual", "m", "", confidence=0.5)
        prev = 0.5
        for _ in range(100):
            c = salience.reinforce(self.con, mid)
            self.assertGreaterEqual(c, prev)
            prev = c
        self.assertLessEqual(prev, 0.95)
        self.assertAlmostEqual(prev, 0.95)


if __name__ == "__main__":
    unittest.main()
