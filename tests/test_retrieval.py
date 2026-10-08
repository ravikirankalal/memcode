import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from memcode import pinned, retrieval, store

ROOT = Path(__file__).resolve().parent.parent


class Retrieval(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        for f in ("billing/invoice.py", "auth/session.py", "util/dates.py"):
            (Path(self.root) / f).parent.mkdir(parents=True, exist_ok=True)
            (Path(self.root) / f).write_text("x = 1\n")
        self.con = store.connect(self.root)
        add = lambda trig, text, a="", sym=None: store.add_memory(self.con, trig, text, a, None, {}, anchor_symbol=sym)
        self.inv = add("fail_to_fix", "rounding of invoice totals broke tests until cents were integers", "billing/invoice.py", "total_cents")
        self.auth = add("revert", "agent change to session expiry was reverted", "auth/session.py")
        self.dates = add("fail_to_fix", "naive datetimes failed the timezone tests", "util/dates.py")
        self.rule = add("correction", "Rule from user correction: Always store money as integer cents.")
        self.chatter = add("retry", "Command `make lint` needed multiple attempts")

    def ids(self, prompt, session="s"):
        return [r["id"] for _, r in retrieval.score(self.con, self.root, session, prompt)]

    def test_named_file_and_symbol_rank_first(self):
        self.assertEqual(self.ids("fix the bug in invoice.py")[0], self.inv)
        self.assertEqual(self.ids("total_cents returns the wrong value")[0], self.inv)
        self.assertEqual(self.ids("look at auth/session.py expiry handling")[0], self.auth)

    def test_identifier_splitting_and_term_overlap(self):
        self.assertIn(self.dates, self.ids("timezone handling for naive datetime values"))
        self.assertIn(self.rule, self.ids("how should we store money amounts in cents"))

    def test_unrelated_prompt_injects_nothing(self):
        self.assertEqual(self.ids("write a haiku about autumn leaves"), [])
        self.assertEqual(self.ids("thanks, looks good"), [])

    def test_active_files_boost(self):
        store.log_event(self.con, "s", "tool_use", {"kind": "tool_use", "tool": "Edit",
                                                    "input": {"file_path": f"{self.root}/util/dates.py"}})
        self.assertEqual(self.ids("now handle the timezone edge case")[0], self.dates)

    def test_no_repeats_within_a_session_and_stale_excluded(self):
        text = retrieval.for_prompt(self.con, self.root, "s", "fix the bug in invoice.py")
        self.assertIn("rounding of invoice totals", text)
        self.assertNotIn(self.inv, self.ids("invoice.py again please"))                 # already shown
        self.assertIn(self.inv, self.ids("invoice.py again please", session="other"))   # other session: fine
        self.con.execute("UPDATE memories SET stale=1 WHERE id=?", (self.auth,)); self.con.commit()
        self.assertNotIn(self.auth, self.ids("auth/session.py"))
        src = self.con.execute("SELECT source FROM injections WHERE memory_id=?", (self.inv,)).fetchone()[0]
        self.assertEqual(src, "prompt")
        self.assertEqual(self.con.execute("SELECT prompt_injected FROM session_stats WHERE session='s'").fetchone()[0], 1)

    def test_framing_rules_vs_untrusted_notes(self):
        text, _ = retrieval.render(retrieval.score(self.con, self.root, "s", "store money in cents for invoice.py"))
        rules_part, _, notes_part = text.partition(pinned.NOTES_HEADER)
        self.assertIn("follow them", rules_part); self.assertIn("integer cents", rules_part)
        self.assertIn("rounding of invoice", notes_part); self.assertIn(pinned.NOTES_CLOSE, notes_part)

    def test_top_k_and_token_cap(self):
        for i in range(30):
            store.add_memory(self.con, "fail_to_fix", f"invoice rounding variant {i} " + "x" * 300, "billing/invoice.py", None, {})
        text, ids = retrieval.render(retrieval.score(self.con, self.root, "s", "invoice.py rounding"))
        self.assertLessEqual(len(ids), retrieval.TOP_K)
        self.assertLessEqual(len(text) / pinned.TOKEN_DIVISOR, retrieval.TOKEN_CAP + 200)

    def test_rank_is_relevance_only_unless_salience_flag(self):
        base = self.ids("timezone naive datetime invoice rounding")
        with mock.patch.dict(os.environ, {"MEMCODE_RANK": "salience"}):
            self.assertEqual(set(self.ids("timezone naive datetime invoice rounding", session="z")), set(base))

    def test_hook_flag_off_by_default_on_when_enabled(self):
        self.con.close()
        def run(**env):
            e = dict(os.environ, PYTHONPATH=str(ROOT), **env)
            e.pop("MEMCODE_RETRIEVAL", None) if "MEMCODE_RETRIEVAL" not in env else None
            p = subprocess.run([sys.executable, "-m", "memcode.hook_cli", "UserPromptSubmit"], env=e, text=True,
                               capture_output=True, input=json.dumps({"session_id": "h", "cwd": self.root,
                                                                       "prompt": "fix the bug in invoice.py"}))
            return p.stdout
        self.assertEqual(run().strip(), "")
        out = json.loads(run(MEMCODE_RETRIEVAL="1"))
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("rounding of invoice totals", out["hookSpecificOutput"]["additionalContext"])


if __name__ == "__main__":
    unittest.main()


class Terms(unittest.TestCase):
    def test_terms(self):
        for spelling in ("parseItems", "parse_items", "parse items", "ParseItems"):
            self.assertTrue({"parse", "item"} <= retrieval.terms(spelling), spelling)   # all spellings meet
        self.assertIn("always", retrieval.terms("Always store"))                        # no "alway"

    def test_single_shared_word_is_not_relevance(self):
        root = tempfile.mkdtemp(); con = store.connect(root)
        store.add_memory(con, "fail_to_fix", "the cache layer timed out under load", "", None, {})
        self.assertEqual(retrieval.score(con, root, "s", "clear the browser cache please"), [])
        self.assertEqual(len(retrieval.score(con, root, "s", "the cache layer times out under load again")), 1)


class Scope(unittest.TestCase):
    def test_path_tokens(self):
        self.assertEqual(retrieval.path_tokens("Every module under billing/ and util/dates.py, see https://x.io/a"),
                         {"billing/", "util/dates.py"})

    def test_directory_scoped_rule_matches_paths_inside_it_only(self):
        root = tempfile.mkdtemp(); con = store.connect(root)
        rid = store.add_memory(con, "correction", "Rule from user correction: Every new module under billing/ starts with '# PCI'.", "", None, {})
        store.add_memory(con, "correction", "Rule from user correction: Components in frontend/ use named exports.", "", None, {})
        got = [r["id"] for _, r in retrieval.score(con, root, "s", "Create billing/refunds.py with a refund function")]
        self.assertEqual(got, [rid])
        self.assertEqual(retrieval.score(con, root, "s", "Create payments/refunds.py with a refund function"), [])
        self.assertEqual(retrieval.score(con, root, "s", "billingreport.py needs a fix"), [])
