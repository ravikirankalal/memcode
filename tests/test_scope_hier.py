import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from memcode import pinned, retrieval, scope, store, tree

RULE = "Rule from user correction: "


def repo(files=("billing/invoice.py", "billing/api/refunds.py", "web/views.py", "README.md")):
    d = tempfile.mkdtemp()
    for f in files:
        (Path(d) / f).parent.mkdir(parents=True, exist_ok=True)
        (Path(d) / f).write_text("x = 1\n")
    con = store.connect(d)
    tree.scan_repo(con, d)
    return d, con


def env(**kw):
    base = {k: v for k, v in os.environ.items() if not k.startswith("MEMCODE_")}
    base.update(kw)
    return mock.patch.dict(os.environ, base, clear=True)


class Assign(unittest.TestCase):
    def setUp(self):
        self.d, self.con = repo()

    def tearDown(self):
        self.con.close()

    def a(self, text, trigger="correction", anchor="", sym=None):
        return scope.assign(self.con, trigger, (RULE + text) if trigger == "correction" else text, anchor, sym)

    def test_rules(self):
        self.assertEqual(self.a("Every module under billing/ starts with # PCI-SCOPE."), ("billing", "dir"))
        self.assertEqual(self.a("Handlers in billing/api/ return dicts."), ("billing/api", "dir"))
        self.assertEqual(self.a("billing/invoice.py rounds half up."), ("billing", "dir"))      # file -> its dir
        self.assertEqual(self.a("billing/api/ and billing/ share errors."), ("billing", "dir"))  # common ancestor
        self.assertEqual(self.a("billing/ and web/ log via utils."), ("", "repo"))                # ancestor is repo
        self.assertEqual(self.a("Always use tabs."), ("", "repo"))
        self.assertEqual(self.a("Code under payments/ is frozen."), ("", "repo"))                 # no such dir

    def test_notes(self):
        self.assertEqual(self.a("failed then passed", "fail_to_fix", "billing/invoice.py"), ("billing/invoice.py", "file"))
        self.assertEqual(self.a("x", "fail_to_fix", "billing/invoice.py", "total"), ("billing/invoice.py", "symbol"))
        self.assertEqual(self.a("x", "revert", "billing"), ("billing", "dir"))
        self.assertEqual(self.a("make build needed attempts", "retry"), ("", "repo"))

    def test_rescope_new_is_idempotent_and_assigns(self):
        mid = store.add_memory(self.con, "correction", RULE + "Every module under web/ uses jinja.", "", None, {})
        self.assertEqual(scope.rescope_new(self.con, self.d)["updated"], 1)
        self.assertEqual(scope.rescope_new(self.con, self.d)["updated"], 0)
        r = self.con.execute("SELECT scope_path, scope_kind FROM memories WHERE id=?", (mid,)).fetchone()
        self.assertEqual(tuple(r), ("web", "dir"))


class Seeded(unittest.TestCase):
    def setUp(self):
        self.d, self.con = repo()
        add = lambda t, trig="correction", a="": store.add_memory(  # noqa: E731
            self.con, trig, (RULE + t) if trig == "correction" else t, a, None, {})
        self.repo_rule = add("Always use tabs for indentation.")
        self.billing_rule = add("Every module under billing/ starts with the line # PCI-SCOPE.")
        self.api_rule = add("Handlers in billing/api/ return plain dicts, never Response objects.")
        self.web_rule = add("Views in web/ render templates with jinja, never f-strings.")
        self.note = add("tests failed until rounding used integer cents", "fail_to_fix", "billing/invoice.py")
        scope.rescope_new(self.con, self.d)

    def tearDown(self):
        self.con.close()

    def ids(self, prompt, session="s"):
        return [r["id"] for _, r in retrieval.score(self.con, self.d, session, prompt)]

    def test_flag_off_ignores_scope_columns(self):
        prompts = ["Add a refund endpoint in billing/api/refunds.py", "Fix the web/views.py template", "tabs or spaces?"]
        with env(MEMCODE_RETRIEVAL="1"):
            scoped = [self.ids(p) for p in prompts] + [pinned.render_pinned(self.con, self.d)]
            self.con.execute("UPDATE memories SET scope_path='', scope_kind='repo'"); self.con.commit()
            flat = [self.ids(p) for p in prompts] + [pinned.render_pinned(self.con, self.d)]
        self.assertEqual(scoped, flat)

    def test_hier_eligibility_and_nearest_first(self):
        with env(MEMCODE_RETRIEVAL="1", MEMCODE_HIER="1"):
            got = self.ids("Add a refund endpoint in billing/api/refunds.py that returns the refund")
        self.assertNotIn(self.web_rule, got)                       # off-chain directory
        self.assertIn(self.api_rule, got); self.assertIn(self.billing_rule, got)
        self.assertLess(got.index(self.api_rule), got.index(self.billing_rule))   # deeper scope first

    def test_bare_directory_word_names_the_scope(self):
        with env(MEMCODE_RETRIEVAL="1", MEMCODE_HIER="1"):
            self.assertIn(self.web_rule, self.ids("change how web views render their templates"))

    def test_start_block_splits_rules_and_marks_map(self):
        with env(MEMCODE_RETRIEVAL="1", MEMCODE_HIER="1"):
            text = pinned.render_pinned(self.con, self.d)
        rules_part = text.split(pinned.NOTES_OPEN)[0]
        self.assertIn("tabs", rules_part)
        self.assertNotIn("PCI-SCOPE", rules_part)
        self.assertIn("[1 rule]", text)
        self.assertIn(pinned.MAP_TITLE_MARKED, text)
        self.assertIn(self.repo_rule, pinned.shown_ids(self.con, text))
        self.assertNotIn(self.billing_rule, pinned.shown_ids(self.con, text))
        with env(MEMCODE_HIER="1", MEMCODE_RETRIEVAL="0"):         # retrieval off: never hide scoped rules
            self.assertIn("PCI-SCOPE", pinned.render_pinned(self.con, self.d).split(pinned.NOTES_OPEN)[0])

    def test_rules_for_path_once_nearest_first_and_flag_off(self):
        with env():
            self.assertEqual(scope.rules_for_path(self.con, "s", "billing/api/refunds.py", self.d), ("", []))
        with env(MEMCODE_HIER="1"):
            text, ids = scope.rules_for_path(self.con, "s", os.path.join(self.d, "billing/api/refunds.py"), self.d)
            self.assertEqual(ids[:2], [self.api_rule, self.billing_rule])
            self.assertNotIn(self.repo_rule, ids); self.assertNotIn(self.web_rule, ids)
            self.assertIn("Project rules for billing/api/refunds.py", text)
            self.assertEqual(scope.rules_for_path(self.con, "s", "billing/api/refunds.py", self.d), ("", []))
            self.assertNotIn(self.api_rule, self.ids("billing/api/refunds.py handlers return dicts"))  # skip shown
            t2, ids2 = scope.rules_for_path(self.con, "s", "billing/invoice.py", self.d)
            self.assertEqual(ids2, [self.note])                       # rules already shown; the file note is new
            self.assertIn(pinned.NOTES_OPEN, t2)

    def test_pinned_file_note_resurfaces_when_prompt_names_its_file(self):
        with env(MEMCODE_RETRIEVAL="1", MEMCODE_HIER="1"):
            self.con.execute("INSERT INTO injections(session,memory_id,ts,source) VALUES('s',?,0,'pinned')", (self.note,))
            self.assertIn(self.note, self.ids("Fix rounding in billing/invoice.py"))        # named: shown again
            self.assertNotIn(self.note, self.ids("change billing totals"))                 # not named: stays shown
        with env(MEMCODE_RETRIEVAL="1"):
            self.assertNotIn(self.note, self.ids("Fix rounding in billing/invoice.py"))    # flag off: unchanged

    def test_touch_cap(self):
        for i in range(40):
            store.add_memory(self.con, "correction", RULE + f"Rule {i}: modules under web/ follow convention {i} "
                             "with a fairly long explanation of what that means.", "", None, {})
        scope.rescope_new(self.con, self.d)
        with env(MEMCODE_HIER="1"):
            text, ids = scope.rules_for_path(self.con, "s", "web/views.py", self.d, token_cap=150)
        self.assertLess(len(ids), 41)
        self.assertLessEqual(len(text) / pinned.TOKEN_DIVISOR, 150 + 60)


class FirstTouchHook(unittest.TestCase):
    """The real hook: PostToolUse on Read/Edit injects scoped rules once (MEMCODE_HIER), reads never feed capture."""

    def hook(self, d, payload, _event="PostToolUse", **flags):
        import json, subprocess, sys
        root = str(Path(__file__).resolve().parent.parent)
        e = {k: v for k, v in os.environ.items() if not k.startswith("MEMCODE_") and k != "CLAUDE_PROJECT_DIR"}
        e.update(PYTHONPATH=root, **flags)
        p = subprocess.run([sys.executable, "-m", "memcode.hook_cli", _event], env=e, text=True,
                           capture_output=True, input=json.dumps(dict(payload, cwd=d)))
        return json.loads(p.stdout) if p.stdout.strip() else None

    def test_read_triggers_touch_once(self):
        d, con = repo()
        rid = store.add_memory(con, "correction", RULE + "Every module under billing/ starts with # PCI-SCOPE.", "",
                               None, {})
        scope.rescope_new(con, d)
        con.close()
        read = {"session_id": "s1", "tool_name": "Read", "tool_input": {"file_path": os.path.join(d, "billing/invoice.py")},
                "tool_response": {"content": "x"}}
        self.assertIsNone(self.hook(d, read))                                     # flag off: nothing, fast path
        out = self.hook(d, read, MEMCODE_HIER="1")
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertIn("PCI-SCOPE", out["hookSpecificOutput"]["additionalContext"])
        self.assertIsNone(self.hook(d, read, MEMCODE_HIER="1"))                   # once per session
        con = store.connect(d)
        self.assertEqual(con.execute("SELECT source FROM injections WHERE memory_id=?", (rid,)).fetchone()[0], "touch")
        con.close()

    def test_first_write_refused_once_with_the_rules(self):
        d, con = repo()
        store.add_memory(con, "correction", RULE + "Every module under billing/ starts with # PCI-SCOPE.", "", None, {})
        store.add_memory(con, "correction", RULE + "Views in web/ use jinja.", "", None, {})
        scope.rescope_new(con, d)
        con.close()
        write = {"session_id": "s1", "tool_name": "Write",
                 "tool_input": {"file_path": os.path.join(d, "billing/new.py"), "content": "x = 1\n"}}
        self.assertIsNone(self.hook(d, write, _event="PreToolUse"))              # flag off: never refuses
        out = self.hook(d, write, _event="PreToolUse", MEMCODE_HIER="1")["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("PCI-SCOPE", out["permissionDecisionReason"])
        self.assertNotIn("jinja", out["permissionDecisionReason"])            # another directory's rule
        self.assertIsNone(self.hook(d, write, _event="PreToolUse", MEMCODE_HIER="1"))   # shown now: allowed
        read = {"session_id": "s2", "tool_name": "Read", "tool_input": {"file_path": os.path.join(d, "billing/invoice.py")}}
        self.hook(d, read, MEMCODE_HIER="1")                                    # read first: rules arrive, no refusal
        self.assertIsNone(self.hook(d, dict(write, session_id="s2"), _event="PreToolUse", MEMCODE_HIER="1"))
        top = dict(write, session_id="s3", tool_input={"file_path": os.path.join(d, "setup.py"), "content": ""})
        self.assertIsNone(self.hook(d, top, _event="PreToolUse", MEMCODE_HIER="1"))     # repo scope: start block has it

    def test_reads_never_reach_capture(self):
        from memcode import engine
        d, con = repo()
        engine.prompt(con, d, "s", "look at the billing code")
        with env(MEMCODE_HIER="1"):
            engine.tool_result(con, d, {"kind": "tool_result", "session": "s", "tool": "Read",
                                        "input": {"file_path": "billing/invoice.py"}, "command": None,
                                        "file_path": "billing/invoice.py", "exit_code": 0, "output": ""})
        engine.prompt(con, d, "s", "No, always use tabs here.")       # agent only read: not a correction context
        self.assertEqual(con.execute("SELECT COUNT(*) FROM memories").fetchone()[0], 0)
        con.close()


class Perf(unittest.TestCase):
    def test_rescope_new_linear(self):
        d, con = repo()
        for i in range(5000):
            store.add_memory(con, "correction" if i % 3 == 0 else "fail_to_fix",
                             RULE + f"Rule {i} for billing/ modules." if i % 3 == 0 else f"note {i}",
                             "" if i % 3 == 0 else "billing/invoice.py", None, {}, commit=False)
        con.commit()
        t = time.perf_counter()
        scope.rescope_new(con, d)
        first = time.perf_counter() - t
        t = time.perf_counter()
        scope.rescope_new(con, d)
        second = time.perf_counter() - t
        self.assertLess(first, 3.0); self.assertLess(second, 1.5)
        con.close()


if __name__ == "__main__":
    unittest.main()
