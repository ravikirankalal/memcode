import contextlib
import io
import os
import tempfile
import time
import unittest
from unittest import mock

from memcode import budget, cli, consolidate, labels, pinned, retrieval, salience, store

FTF = "`pytest -q tests/test_api.py` failed and passed after editing {f}. Fix was in {f}."


def env(**kw):
    base = {k: v for k, v in os.environ.items() if not k.startswith("MEMCODE_")}
    base.update(kw)
    return mock.patch.dict(os.environ, base, clear=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.con = store.connect(self.d)

    def tearDown(self):
        self.con.close()

    def add(self, trigger, text, anchor="", prov=None, age=0.0):
        mid = store.add_memory(self.con, trigger, text, anchor, None, prov or {})
        if age:
            self.con.execute("UPDATE memories SET created_at=created_at-?, updated_at=updated_at-? WHERE id=?",
                             (age, age, mid))
            self.con.commit()
        return mid

    def ftf(self, n, f="api/handlers.py"):
        return [self.add("fail_to_fix", FTF.format(f=f), f, age=(n - i) * 60) for i in range(n)]

    def parent(self, mid):
        return self.con.execute("SELECT parent_id FROM memories WHERE id=?", (mid,)).fetchone()[0]

    def lessons(self):
        return self.con.execute("SELECT * FROM memories WHERE trigger='lesson'").fetchall()


class Consolidate(Base):
    def test_three_similar_make_one_lesson_two_do_not(self):
        kids = self.ftf(3)
        self.ftf(2, "web/views.py")
        st = consolidate.run(self.con)
        self.assertEqual((st["created"], st["lessons"], st["children"]), (1, 1, 3))
        (les,) = self.lessons()
        self.assertEqual(les["evidence_count"], 3)
        self.assertEqual(les["level"], 1)
        self.assertTrue(les["text"].startswith("3 similar fail_to_fix notes on api/handlers.py: "))
        self.assertEqual({self.parent(k) for k in kids}, {les["id"]})

    def test_signature_normalizes_numbers_and_flags_but_not_quoted_code(self):
        self.assertEqual(consolidate.signature("`pytest -q -k a1` failed 3 times"),
                         consolidate.signature("`pytest -k b2` failed 7 times"))
        a = 'Agent change to x.py was reverted (removed "return 1").'
        b = 'Agent change to x.py was reverted (removed "return None").'
        self.assertNotEqual(consolidate.signature(a), consolidate.signature(b))

    def test_rules_and_different_signatures_never_merge(self):
        for _ in range(3):
            self.add("correction", "Rule from user correction: Always use tabs.")
        for code in ("return 1", "return 2", "return 3"):
            self.add("revert", f'Agent change to b.py was reverted (removed "{code}").', "b.py")
        self.assertEqual(consolidate.run(self.con)["created"], 0)

    def test_idempotent_incremental_and_dissolve(self):
        kids = self.ftf(3)
        consolidate.run(self.con)
        again = consolidate.run(self.con)
        self.assertEqual((again["created"], again["updated"], again["linked"], again["unlinked"]), (0, 0, 0, 0))
        new = self.ftf(1)[0]
        st = consolidate.run(self.con)
        self.assertEqual((st["updated"], st["linked"]), (1, 1))
        self.assertEqual(self.lessons()[0]["evidence_count"], 4)
        self.assertIsNotNone(self.parent(new))
        consolidate.delete_ids(self.con, kids)          # 1 live child left: below MIN_KEEP
        self.con.commit()
        st = consolidate.run(self.con)
        self.assertEqual(st["dissolved"], 1)
        self.assertEqual(self.lessons(), [])
        self.assertTrue(all(r[0] is None for r in self.con.execute("SELECT parent_id FROM memories")))

    def test_stale_child_unlinks(self):
        kids = self.ftf(4)
        consolidate.run(self.con)
        self.con.execute("UPDATE memories SET stale=1 WHERE id=?", (kids[0],)); self.con.commit()
        st = consolidate.run(self.con)
        self.assertEqual(st["unlinked"], 1)
        self.assertEqual(self.lessons()[0]["evidence_count"], 3)

    def test_injection_shows_lesson_only_when_flag_on(self):
        kids = self.ftf(3)
        consolidate.run(self.con)
        lid = self.lessons()[0]["id"]
        with env():
            off = pinned.shown_ids(self.con, pinned.render_pinned(self.con, self.d))
        with env(MEMCODE_CONSOLIDATE="1"):
            on = pinned.shown_ids(self.con, pinned.render_pinned(self.con, self.d))
            ids = [r["id"] for _, r in retrieval.score(self.con, self.d, "s", "pytest tests/test_api.py api/handlers.py")]
        self.assertTrue(set(kids) <= set(off))
        self.assertIn(lid, on)
        self.assertFalse(set(kids) & set(on))
        self.assertFalse(set(kids) & set(ids))

    def test_lesson_salience_counts_children(self):
        self.ftf(4)
        consolidate.run(self.con)
        les = self.lessons()[0]
        ev = salience.evidence(self.con, les)
        self.assertAlmostEqual(ev["recurrences"], 3, delta=0.1)
        idx = salience.Index(self.con)
        self.assertAlmostEqual(salience.score(self.con, les), salience.score(self.con, les, index=idx), places=6)

    def test_undo(self):
        kids = self.ftf(3)
        consolidate.run(self.con)
        self.assertEqual(consolidate.undo(self.con), 1)
        self.assertEqual(self.lessons(), [])
        self.assertEqual({self.parent(k) for k in kids}, {None})


class Budget(Base):
    def test_eviction_order_and_never_evict_set(self):
        rule = self.add("correction", "Rule from user correction: Always use tabs.")
        manual = self.add("manual", "deploys need VPN")
        stale = self.add("revert", "old revert", "gone.py", age=9000)
        self.con.execute("UPDATE memories SET stale=1 WHERE id=?", (stale,)); self.con.commit()
        kids = self.ftf(3)
        consolidate.run(self.con)
        retry = self.add("retry", "Command `make` needed multiple attempts with different flags/fixes: `make -j1`")
        note = self.add("revert", 'Agent change to c.py was reverted (removed "x").', "c.py")
        total = self.con.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        plan = budget.plan(self.con, total - 1)
        self.assertEqual(plan["stale"], [stale])
        plan = budget.plan(self.con, total - 4)
        self.assertEqual(plan["merged"], kids[:3])
        plan = budget.plan(self.con, total - 5)
        self.assertEqual(plan["low_evidence"], [retry])
        st = budget.enforce(self.con, 1)
        self.assertTrue(st["over_cap"])
        self.assertEqual(st["evicted"]["low_salience"], 1)
        left = {r[0] for r in self.con.execute("SELECT id FROM memories")}
        self.assertEqual(left, {rule, manual, self.lessons()[0]["id"]})
        self.assertNotIn(note, left)

    def test_merge_before_evict_keeps_the_count(self):
        self.ftf(3)
        consolidate.run(self.con)
        budget.enforce(self.con, 1)
        (les,) = self.lessons()
        self.assertEqual(consolidate.prov(les)["absorbed"], 3)
        consolidate.run(self.con)                       # absorbed children keep the lesson alive and counted
        (les,) = self.lessons()
        self.assertEqual(les["evidence_count"], 3)
        self.assertAlmostEqual(salience.evidence(self.con, les)["recurrences"], 2, delta=0.1)

    def test_off_by_default(self):
        self.ftf(5)
        with env():
            self.assertIsNone(budget.enforce_if_enabled(self.con))
        with env(MEMCODE_STORE_BUDGET="2"):
            self.assertEqual(budget.enforce_if_enabled(self.con)["after"], 2)


class Labels(Base):
    def test_auto_precision(self):
        cases = [
            ("fail_to_fix", FTF.format(f="api/handlers.py"), "api/handlers.py", ["testing"]),
            ("retry", "Command `npm run build` needed multiple attempts with different flags/fixes: `npm run build`", "",
             ["build"]),
            ("dep_change", "Dependency/config file requirements.txt was changed by the agent.", "requirements.txt",
             ["deps"]),
            ("correction", "Rule from user correction: Use snake_case for function names.", "", ["naming"]),
            ("correction", "Rule from user correction: Indent with tabs, never spaces.", "", ["style"]),
            ("revert", 'Agent change to docs/intro.md was reverted (removed "x").', "docs/intro.md", ["docs"]),
            ("correction", "Rule from user correction: Always ask before deleting anything.", "", []),
        ]
        for trig, text, anchor, want in cases:
            self.assertEqual(labels.auto(trig, text, anchor), want, text)

    def test_backfill_edit_and_none_marker(self):
        a = self.add("correction", "Rule from user correction: Always ask first.")
        b = self.add("correction", "Rule from user correction: Indent with tabs.")
        self.assertEqual(labels.backfill(self.con), 2)
        self.assertEqual(labels.backfill(self.con), 0)                 # NONE marker: never rescanned
        self.assertEqual(self.con.execute("SELECT labels FROM memories WHERE id=?", (a,)).fetchone()[0], labels.NONE)
        self.assertEqual(labels.edit(self.con, b, ["+perf", "-style"]), ["perf"])
        with self.assertRaises(ValueError):
            labels.edit(self.con, b, ["+Bad Label"])

    def test_labels_never_change_injection(self):
        self.ftf(3)
        self.add("correction", "Rule from user correction: Indent with tabs.")
        with env(MEMCODE_RETRIEVAL="1"):
            before = (pinned.render_pinned(self.con, self.d),
                      [r["id"] for _, r in retrieval.score(self.con, self.d, "s", "fix api/handlers.py tests")])
            labels.backfill(self.con)
            self.con.execute("UPDATE memories SET labels='security,perf'"); self.con.commit()
            after = (pinned.render_pinned(self.con, self.d),
                     [r["id"] for _, r in retrieval.score(self.con, self.d, "s", "fix api/handlers.py tests")])
        self.assertEqual(before, after)


class Cli(Base):
    def run_cli(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), env():
            code = cli.main(["--root", self.d, *args])
        return code, buf.getvalue()

    def test_commands(self):
        self.ftf(3)
        rid = self.add("correction", "Rule from user correction: Indent with tabs.")
        self.con.close()
        self.assertIn("would: 1 lessons over 3 notes", self.run_cli("consolidate", "--dry-run")[1])
        self.assertIn("1 lessons over 3 notes", self.run_cli("consolidate")[1])
        self.assertIn(f"#{rid}: perf", self.run_cli("label", str(rid), "+perf", "-style")[1])
        self.assertIn("Indent with tabs", self.run_cli("list", "--label", "perf")[1])
        out = self.run_cli("budget", "2", "--dry-run")[1]
        self.assertIn("would evict: merged 3", out)
        self.assertIn("removed 1 lessons", self.run_cli("consolidate", "--undo")[1])
        self.con = store.connect(self.d)


class Perf(Base):
    def test_20k_rows(self):
        for i in range(20000):
            f = f"pkg{i % 400}/m{i % 7}.py"
            trig = ("fail_to_fix", "retry", "revert", "correction")[i % 4]
            text = (FTF.format(f=f) if trig == "fail_to_fix" else
                    f"Command `make t{i % 9}` needed multiple attempts with different flags/fixes: `make -j{i % 3}`"
                    if trig == "retry" else f'Agent change to {f} was reverted (removed "v{i % 50}").'
                    if trig == "revert" else f"Rule from user correction: rule {i}")
            store.add_memory(self.con, trig, text, "" if trig in ("retry", "correction") else f, None, {},
                             commit=False)
        self.con.commit()
        t = time.perf_counter()
        consolidate.run(self.con)
        labels.backfill(self.con)
        budget.enforce(self.con, 10000)
        took = time.perf_counter() - t
        self.assertLess(took, 6.0)
        t = time.perf_counter()
        consolidate.run(self.con); labels.backfill(self.con); budget.enforce(self.con, 10000)
        self.assertLess(time.perf_counter() - t, 2.0)                  # steady state: nothing to do


if __name__ == "__main__":
    unittest.main()
