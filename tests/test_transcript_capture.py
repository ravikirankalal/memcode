import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from memcode import store, transcript_capture as tc

ROOT = Path(__file__).resolve().parent.parent


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def agent(*blocks):
    return {"type": "assistant", "message": {"role": "assistant", "content": list(blocks)}}


def bash(i, cmd):
    return {"type": "tool_use", "id": i, "name": "Bash", "input": {"command": cmd}}


def result(i, text, err=False):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": i, "content": text, "is_error": err}]}}


SESSION = [
    user("Add a recent command to the CLI. Every module in this repo starts with the SPDX header line."),
    user("<task-notification>background job finished</task-notification>"),
    agent({"type": "text", "text": "Let me run the tests first."}, bash("t1", "python3 -m unittest")),
    result("t1", "Ran 0 tests in 0.000s\n\nNO TESTS RAN", err=True),
    agent({"type": "text", "text": "unittest finds nothing here; the Makefile has a check target."},
          bash("t2", "make check")),
    result("t2", "checks/check_cli.py ... ok\nOK"),
    agent({"type": "tool_use", "id": "w1", "name": "Write",
           "input": {"file_path": "/r/shelf/recent.py", "content": "# SPDX-License-Identifier: MIT\n"}}),
    agent({"type": "text", "text": "Done. The tests in this repo run with make check (plain unittest finds no tests)."}),
]


def write_transcript(entries) -> str:
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    f.write("\n".join(json.dumps(e) for e in entries) + "\n")
    f.close()
    return f.name


class Condense(unittest.TestCase):
    def test_shape(self):
        text = tc.condense([json.dumps(e) for e in SESSION])
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("[user] Add a recent command"))
        self.assertNotIn("task-notification", text)                     # harness turns are not the user's words
        self.assertIn("[ran] `python3 -m unittest` -> failed | Ran 0 tests in 0.000s NO TESTS RAN", text)
        self.assertIn("[ran] `make check` -> ok", text)
        self.assertIn("[wrote] /r/shelf/recent.py", text)
        self.assertIn("[agent] Done. The tests in this repo run with make check", text)


class Checks(unittest.TestCase):
    condensed = tc.condense([json.dumps(e) for e in SESSION])

    def test_evidence_decides_rule_or_note(self):
        rule = {"kind": "rule", "text": "Every module starts with the SPDX header line.",
                "evidence": "Every module in this repo starts with the SPDX header line", "path": ""}
        self.assertEqual(tc.verified(rule, self.condensed), "rule")
        claimed = dict(rule, evidence="The tests in this repo run with make check")   # agent's words: a note
        self.assertEqual(tc.verified(claimed, self.condensed), "note")
        made_up = dict(rule, evidence="always run tox before committing")
        self.assertIsNone(tc.verified(made_up, self.condensed))
        self.assertIsNone(tc.verified(dict(rule, evidence="SPDX"), self.condensed))           # too short


class Store(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.d, "shelf"))
        Path(self.d, "Makefile").write_text("check:\n\tpython3 -m checks\n")
        self.con = store.connect(self.d)
        self.condensed = tc.condense([json.dumps(e) for e in SESSION])

    def tearDown(self):
        self.con.close()

    def items(self):
        return [{"kind": "note", "text": "Run the tests with `make check`; plain unittest finds no tests.",
                 "evidence": "unittest finds nothing here; the Makefile has a check target", "path": "Makefile"},
                {"kind": "rule", "text": "Every module starts with the SPDX header line.",
                 "evidence": "Every module in this repo starts with the SPDX header line", "path": ""},
                {"kind": "note", "text": "The project uses a database migration tool.",
                 "evidence": "not anywhere in the transcript", "path": ""}]

    def test_stores_verified_items_as_rule_and_note(self):
        ids = tc.store_items(self.con, self.d, "s", self.items(), self.condensed, "m")
        self.assertEqual(len(ids), 2)                                   # the unverified one is dropped
        rows = {r["trigger"]: r for r in self.con.execute("SELECT * FROM memories")}
        self.assertEqual(rows["transcript"]["anchor_path"], "Makefile")
        self.assertTrue(rows["correction"]["text"].startswith("Rule from user correction: Every module"))
        self.assertEqual(json.loads(rows["transcript"]["provenance"])["source"], "transcript")
        again = tc.store_items(self.con, self.d, "s2", self.items(), self.condensed, "m")
        self.assertEqual(again, [])                                     # repeats of live memories are skipped

    def test_task_request_is_never_a_rule(self):
        # issue #33: a request for now, quoted as the user's words, must not become a standing rule
        msg = ("Park G16. Start a review subagent on multitenant main, it should keep the backwork compatibility in "
               "mind with rest of the review points. keep in mind develop is still running in a different cluster "
               "and we can not touch it yet.")
        condensed = tc.condense([json.dumps(user(msg)), json.dumps(agent({"type": "text", "text": "On it."}))])
        items = [{"kind": "rule", "text": msg[:120], "evidence": "Park G16. Start a review subagent", "path": ""},
                 {"kind": "rule", "text": "Keep backward compatibility in mind in reviews.",
                  "evidence": "keep the backwork compatibility in mind", "path": ""}]
        self.assertEqual(tc.store_items(self.con, self.d, "s", items, condensed, "m"), [])
        rid = store.add_memory(self.con, "correction", "Rule from user correction: Indent with tabs.", "", None, {})
        upd = {"op": "update", "target": rid, "kind": "rule", "text": "Start a review subagent on main.",
               "evidence": "Park G16. Start a review subagent", "path": ""}
        self.assertIsNone(tc.change(self.con, "s", upd, condensed))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM memories WHERE trigger='correction'").fetchone()[0], 1)

    def test_env_items_become_env_facts_and_conflicts_are_dropped(self):
        items = [{"kind": "env", "text": "Chained shell commands need approval here; run them one at a time.",
                  "evidence": "Ran 0 tests in 0.000s NO TESTS RAN", "path": "", "conflicts": False},
                 {"kind": "note", "text": "storage.load raises ValueError on bad JSON and was left unchanged.",
                  "evidence": "unittest finds nothing here; the Makefile has a check target", "path": "",
                  "conflicts": True},
                 {"kind": "note", "text": "Writing rules to memcode memory was declined in this environment.",
                  "evidence": "unittest finds nothing here; the Makefile has a check target", "path": "",
                  "conflicts": False}]
        self.assertEqual(tc.store_items(self.con, self.d, "s", items, self.condensed, "m"), [])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM memories").fetchone()[0], 0)
        from memcode import facts
        env = [r["value"] for r in facts.list_facts(self.con) if r["category"] == "env"]
        self.assertEqual(env, ["Chained shell commands need approval here; run them one at a time."])
        self.assertIn("- Chained shell commands need approval here", "\n".join(facts.lines(self.con)))

    def test_short_user_turn_is_scanned_and_small_ones_wait(self):
        seen = []
        fake = lambda text, rules=None: seen.append((text, rules)) or {"items": [], "model": "f", "cost_usd": 0}  # noqa: E731
        store.add_memory(self.con, "correction", "Rule from user correction: Indent with tabs.", "", None, {})
        path = write_transcript([agent({"type": "text", "text": "ok"})])
        tc.enqueue(self.con, "s1", path)
        tc.run_worker(self.d, fake)
        self.assertEqual(seen, [])                                      # tiny, no user words: waits, offset kept
        self.assertEqual(self.con.execute("SELECT offset FROM transcript_scans").fetchone()[0], 0)
        with open(path, "a") as fh:
            fh.write(json.dumps(user("By the way, our API returns cents as int.")) + "\n")
        tc.enqueue(self.con, "s1", path)
        tc.run_worker(self.d, fake)
        self.assertEqual(len(seen), 1)
        self.assertIn("[agent] ok", seen[0][0])                         # the held-back part is included
        brief = seen[0][1]                                              # the model is briefed as the repo's memory agent
        self.assertIn("Session: s1", brief)
        self.assertRegex(brief, r"- #\d+ rule \[repo\]: Indent with tabs\.")

    def test_update_and_retire_follow_the_evidence_rules(self):
        cond = tc.condense([json.dumps(e) for e in SESSION] + [json.dumps(user(
            "Actually we dropped the SPDX header requirement last week, new files do not need it anymore."))])
        rule = store.add_memory(self.con, "correction", "Rule from user correction: Every module starts with SPDX.",
                                "", None, {})
        note = store.add_memory(self.con, "transcript", "Run the tests with pytest.", "", None, {})
        agent_ev = "unittest finds nothing here; the Makefile has a check target"
        user_ev = "we dropped the SPDX header requirement last week"
        ops = [{"op": "update", "target": note, "kind": "note", "text": "Run the tests with `make check`.",
                "evidence": agent_ev, "path": "", "conflicts": False},
               {"op": "retire", "target": rule, "kind": "rule", "text": "The user dropped the SPDX header rule.",
                "evidence": agent_ev, "path": "", "conflicts": False}]                # agent's words: refused
        self.assertEqual(tc.store_items(self.con, self.d, "s", ops, cond), [note])
        self.assertEqual(self.con.execute("SELECT text FROM memories WHERE id=?", (note,)).fetchone()[0],
                         "Run the tests with `make check`.")
        self.assertIsNotNone(self.con.execute("SELECT id FROM memories WHERE id=?", (rule,)).fetchone())
        ops[1]["evidence"] = user_ev                                               # the user's own words: retired
        self.assertEqual(tc.store_items(self.con, self.d, "s", ops[1:], cond), [rule])
        self.assertIsNone(self.con.execute("SELECT id FROM memories WHERE id=?", (rule,)).fetchone())
        log = self.con.execute("SELECT op, memory_id, before FROM memory_log ORDER BY id").fetchall()
        self.assertEqual([(r[0], r[1]) for r in log], [("update", note), ("retire", rule)])
        self.assertIn("Every module starts with SPDX", json.loads(log[1][2])["text"])   # the old row is kept
        bad = {"op": "retire", "target": 9999, "kind": "note", "text": "x" * 10, "evidence": user_ev, "path": "",
               "conflicts": False}
        self.assertEqual(tc.store_items(self.con, self.d, "s", [bad], cond), [])  # unknown target: nothing

    def test_memories_in_the_agents_context_are_not_relearned(self):
        rule = store.add_memory(self.con, "correction",
                                "Rule from user correction: New code gets the date from shelf.clock, never datetime.",
                                "", None, {})
        self.con.execute("INSERT INTO injections(session, memory_id, ts, source) VALUES('s', ?, 0, 'pinned')", (rule,))
        self.con.commit()
        self.assertIn(f"#{rule} rule [repo] (in the agent's context):", tc.briefing(self.con, self.d, "s"))
        self.assertNotIn("(in the agent's context)", tc.briefing(self.con, self.d, "other-session"))
        cond = ("[agent] Per the project rule, new code gets the date from shelf.clock and never from datetime, "
                "so importers.py uses clock.today().\n[user] Thanks. Our importers always skip blank rows silently.")
        echo = {"op": "add", "target": 0, "kind": "note", "conflicts": False, "path": "",
                "text": "importers.py gets the current date through clock.today().",
                "evidence": "new code gets the date from shelf.clock and never from datetime"}
        fresh = {"op": "add", "target": 0, "kind": "rule", "conflicts": False, "path": "",
                 "text": "Importers skip blank rows silently.", "evidence": "Our importers always skip blank rows silently"}
        self.assertEqual(len(tc.store_items(self.con, self.d, "s", [echo, fresh], cond)), 1)   # only the new one
        texts = [r[0] for r in self.con.execute("SELECT text FROM memories")]
        self.assertIn("Rule from user correction: Importers skip blank rows silently.", texts)
        self.assertEqual(len(tc.store_items(self.con, self.d, "other", [echo], cond)), 1)      # not shown there

    def test_short_fact_is_not_a_repeat(self):                          # tc1 (Run 16): a fact "shelf" ate a rule
        from memcode import facts
        facts.ensure(self.con)
        self.con.execute("INSERT INTO facts(key,category,role,value,source,runs,ok,fail,first_seen,last_seen) "
                         "VALUES('repo:pkg','repo','pkg','shelf','f',0,0,0,0,0)")
        self.assertFalse(tc.is_repeat(self.con, "Errors that reach the user are ShelfError from shelf/errors.py, "
                                                "never ValueError."))
        store.add_memory(self.con, "transcript", "Errors that reach the user are ShelfError from shelf/errors.py.",
                         "", None, {})
        self.assertTrue(tc.is_repeat(self.con, "Errors reaching the user are ShelfError (shelf/errors.py)."))

    def test_worker_scans_only_new_lines(self):
        path = write_transcript(SESSION)
        calls = []

        def fake(text, rules=None):
            calls.append(text)
            return {"items": self.items()[:1], "model": "fake", "cost_usd": 0.01}
        tc.enqueue(self.con, "s1", path)
        self.assertEqual(tc.run_worker(self.d, fake), 1)
        self.assertEqual(len(calls), 1)
        tc.enqueue(self.con, "s1", path)                                # next Stop, nothing new
        self.assertEqual(tc.run_worker(self.d, fake), 0)
        self.assertEqual(len(calls), 1)
        with open(path, "a") as fh:
            fh.write(json.dumps(user("Note that all CLI output in this repo goes through shelf.ui.echo, "
                                     "never print; this is the convention everywhere in the codebase.")) + "\n")
            fh.write(json.dumps(agent({"type": "text", "text": "Understood. " * 40})) + "\n")
        tc.enqueue(self.con, "s1", path)
        tc.run_worker(self.d, fake)
        self.assertEqual(len(calls), 2)
        self.assertNotIn("make check", calls[1])                        # only the new part is sent
        row = self.con.execute("SELECT status, cost_usd FROM transcript_scans WHERE session='s1'").fetchone()
        self.assertEqual((row[0], round(row[1], 2)), ("idle", 0.02))
        self.assertEqual(tc.pending(self.con), 0)

    def test_session_budget_stops_scanning(self):
        path = write_transcript(SESSION)
        calls = []
        fake = lambda text, ctx=None: calls.append(1) or {"items": [], "model": "f", "cost_usd": 0.06}  # noqa: E731
        tc.enqueue(self.con, "s1", path)
        tc.run_worker(self.d, fake)
        for i in range(3):                                              # more turns, each over the line again
            with open(path, "a") as fh:
                fh.write(json.dumps(user(f"Turn {i}: please keep going with the next part of the work.")) + "\n")
            tc.enqueue(self.con, "s1", path)
            tc.run_worker(self.d, fake)
        self.assertEqual(len(calls), 2)                                 # $0.06 + $0.06 >= $0.10: stops
        self.assertEqual(tc.pending(self.con), 0)

    def test_env_facts_are_capped(self):
        words = ["docker", "kubectl", "terraform", "ansible", "helm", "gcloud", "aws", "az", "psql", "redis",
                 "mongo", "nginx", "systemctl", "brew", "apt", "snap", "flatpak", "podman", "vagrant", "packer"]
        cond = "\n".join(f"[ran] `{w} status` -> failed | {w} blocked by sandbox policy" for w in words)
        items = [{"op": "add", "target": 0, "kind": "env", "conflicts": False, "path": "",
                  "text": f"The {w} CLI is blocked in this sandbox.", "evidence": f"{w} blocked by sandbox policy"}
                 for w in words]
        with mock.patch.object(tc, "is_repeat", lambda con, text: False):   # the cap, not dedupe, is under test
            for chunk in range(0, 20, 5):
                tc.store_items(self.con, self.d, "s", items[chunk:chunk + 5], cond)
        n = self.con.execute("SELECT COUNT(*) FROM facts WHERE key LIKE 'env:obs:%'").fetchone()[0]
        self.assertEqual(n, tc.MAX_ENV_FACTS)

    def test_model_failure_retries_then_errors(self):
        path = write_transcript(SESSION)
        tc.enqueue(self.con, "s1", path)
        tc.run_worker(self.d, lambda text, rules=None: None)
        self.assertEqual(self.con.execute("SELECT status FROM transcript_scans").fetchone()[0], "error")

    def test_failure_is_shown_with_its_reason_and_cleared_on_recovery(self):
        # issue #34: a failing memory agent shows in `memcode stats` and the status feed, until a scan succeeds
        from memcode import activity
        path = write_transcript(SESSION)
        tc.enqueue(self.con, "s1", path)
        why = tc.why_failed('{"is_error": true, "result": "OAuth session expired and could not be refreshed"}', "m")
        tc.run_worker(self.d, lambda text, ctx=None: {"error": why})
        self.assertIn("FAILING", tc.health(self.con))
        self.assertIn("/login", tc.health(self.con))
        feed = json.loads(Path(self.d, ".memcode", activity.FILE).read_text())
        self.assertIn("/login", feed["problems"]["capture"])
        self.assertEqual(self.con.execute("SELECT offset FROM transcript_scans").fetchone()[0], 0)   # nothing lost
        tc.enqueue(self.con, "s1", path)
        tc.run_worker(self.d, lambda text, ctx=None: {"items": [], "model": "f", "cost_usd": 0.01})
        self.assertIsNone(tc.health(self.con))
        feed = json.loads(Path(self.d, ".memcode", activity.FILE).read_text())
        self.assertNotIn("problems", feed)

    def test_new_transcript_path_or_shorter_file_scans_from_the_top(self):
        # found in a live check: a stale offset from another transcript file skipped every line of the new one
        sent = []
        fake = lambda text, ctx=None: sent.append(text) or {"items": [], "model": "f", "cost_usd": 0}  # noqa: E731
        tc.enqueue(self.con, "s1", write_transcript(SESSION))
        tc.run_worker(self.d, fake)
        self.con.execute("UPDATE transcript_scans SET offset=9539"); self.con.commit()
        tc.enqueue(self.con, "s1", write_transcript(SESSION))           # same session id, another file
        tc.run_worker(self.d, fake)
        self.assertEqual(len(sent), 2)
        path = write_transcript(SESSION)
        tc.enqueue(self.con, "s2", path)
        tc.run_worker(self.d, fake)
        self.con.execute("UPDATE transcript_scans SET offset=9539 WHERE session='s2'"); self.con.commit()
        tc.enqueue(self.con, "s2", path)                                 # same file, now shorter than the offset
        tc.run_worker(self.d, fake)
        self.assertEqual(len(sent), 4)

    def test_budget_grows_with_the_transcript(self):
        with mock.patch.dict(os.environ, {"MEMCODE_CAPTURE_BUDGET_USD": ""}):
            self.assertEqual(tc.session_budget(500), 0.10)
            self.assertAlmostEqual(tc.session_budget(10_000), 0.30)
            self.assertEqual(tc.session_budget(100_000), 0.50)
        with mock.patch.dict(os.environ, {"MEMCODE_CAPTURE_BUDGET_USD": "2"}):
            self.assertEqual(tc.session_budget(100_000), 2.0)

    def test_only_notes_on_code_behaviour_pin_the_file_content(self):
        self.assertTrue(tc.pins_content("resolve_root maps a linked git worktree to the main working tree.",
                                        "memcode/store.py"))
        self.assertFalse(tc.pins_content("Run bench/live/x.py as a module: `python3 -m bench.live.x`.", "bench/live/x.py"))
        self.assertFalse(tc.pins_content("Validate the plugin manifests with `claude plugin validate`.",
                                         ".claude-plugin/plugin.json"))
        self.assertFalse(tc.pins_content("The manifest lists both plugins.", ".claude-plugin/marketplace.json"))
        self.assertFalse(tc.pins_content("When auditing trap hits, treat leading spaces as a snippet.", "bench/m.py"))
        self.assertTrue(tc.pins_content("If the cache is cold, load() reads the whole store.", "memcode/store.py"))
        Path(self.d, "plugin.json").write_text('{"version": "1"}')
        items = [{"kind": "note", "text": "Validate plugin.json with `claude plugin validate plugin.json --strict`.",
                  "evidence": "unittest finds nothing here; the Makefile has a check target", "path": "plugin.json"}]
        (mid,) = tc.store_items(self.con, self.d, "s", items, self.condensed, "m")
        Path(self.d, "plugin.json").write_text('{"version": "2"}')                  # a release bump
        from memcode import tree
        tree.mark_stale(self.con, self.d)
        self.assertEqual(self.con.execute("SELECT stale FROM memories WHERE id=?", (mid,)).fetchone()[0], 0)

    def test_old_pinned_howtos_are_unpinned_and_revive(self):
        from memcode import tree
        Path(self.d, "plugin.json").write_text('{"version": "2"}')
        mid = store.add_memory(self.con, "transcript", "Validate plugin.json before merging.", "plugin.json",
                               "oldhash", {})
        code = store.add_memory(self.con, "transcript", "f returns 1.", "Makefile", "oldhash", {})
        tree.mark_stale(self.con, self.d)
        self.assertEqual(tc.unpin_howtos(self.con), 2)                    # both: Makefile is not a code file
        tree.mark_stale(self.con, self.d)
        stale = dict(self.con.execute("SELECT id, stale FROM memories").fetchall())
        self.assertEqual((stale[mid], stale[code]), (0, 0))

    def test_quotes_match_without_markdown_marks(self):
        cond = "[agent] The bar shows the **💸 BUDGET** badge on a `yellow` background (colour 220)."
        item = {"kind": "note", "text": "The budget badge is yellow.", "path": "",
                "evidence": "The bar shows the 💸 BUDGET badge on a yellow background"}
        self.assertEqual(tc.verified(item, cond), "note")

    def test_why_failed_names_the_fix(self):
        self.assertIn("claude update", tc.why_failed("API Error [claude-code:unrecognized_model] no such model", "m"))
        self.assertIn("/login", tc.why_failed("Not logged in · Please run /login", "m"))
        self.assertIn("usage", tc.why_failed('{"is_error":true,"result":"Claude AI usage limit reached"}', "m"))
        self.assertTrue(tc.why_failed("", "m").startswith("the model call failed"))

    def test_long_backlog_is_scanned_in_chunks_oldest_first(self):
        # issue #34: after an outage, every unscanned line is sent (in MAX_CHARS pieces), not only the newest tail
        turns = []
        for i in range(12):
            turns += [user(f"Turn {i}: " + "word " * 60), agent({"type": "text", "text": f"Done {i}. " + "ok " * 100})]
        path = write_transcript(turns)
        sent = []
        fake = lambda text, ctx=None: sent.append(text) or {"items": [], "model": "f", "cost_usd": 0.001}  # noqa: E731
        tc.enqueue(self.con, "s1", path)
        with mock.patch.object(tc, "MAX_CHARS", 1500):
            tc.run_worker(self.d, fake)
        self.assertGreater(len(sent), 3)
        self.assertTrue(all(len(t) <= 1500 for t in sent))
        joined = "\n".join(sent)
        self.assertTrue(all(f"Turn {i}:" in joined for i in range(12)))
        self.assertLess(joined.index("Turn 0:"), joined.index("Turn 11:"))
        self.assertEqual(self.con.execute("SELECT offset FROM transcript_scans").fetchone()[0], len(turns))

    def test_failure_mid_backlog_keeps_the_rest(self):
        turns = []
        for i in range(8):
            turns += [user(f"Turn {i}: " + "word " * 60), agent({"type": "text", "text": "ok " * 100})]
        path = write_transcript(turns)
        n = []

        def flaky(text, ctx=None):
            n.append(text)
            return {"items": [], "model": "f", "cost_usd": 0.001} if len(n) <= 2 else None
        tc.enqueue(self.con, "s1", path)
        with mock.patch.object(tc, "MAX_CHARS", 1500):
            tc.run_worker(self.d, flaky)
        off = self.con.execute("SELECT offset FROM transcript_scans").fetchone()[0]
        self.assertTrue(0 < off < len(turns))                          # past the two pieces sent, no further
        sent = []
        tc.enqueue(self.con, "s1", path)
        with mock.patch.object(tc, "MAX_CHARS", 1500):
            tc.run_worker(self.d, lambda text, ctx=None: sent.append(text) or {"items": [], "model": "f", "cost_usd": 0})
        self.assertIn("Turn 7:", "\n".join(sent))
        self.assertNotIn("Turn 0:", "\n".join(sent))

    def test_budget_running_out_mid_backlog_is_reported(self):
        turns = []
        for i in range(8):
            turns += [user(f"Turn {i}: " + "word " * 60), agent({"type": "text", "text": "ok " * 100})]
        path = write_transcript(turns)
        tc.enqueue(self.con, "s1", path)
        with mock.patch.object(tc, "MAX_CHARS", 1500):
            tc.run_worker(self.d, lambda text, ctx=None: {"items": [], "model": "f", "cost_usd": 0.06})
        self.assertIn("not scanned", tc.health(self.con))
        from memcode import activity
        feed = lambda: json.loads(Path(self.d, ".memcode", activity.FILE).read_text())  # noqa: E731
        self.assertIn("budget is spent", feed()["problems"]["budget"])            # on the status bar too
        n = feed()["problems"]["budget"]
        with open(path, "a") as fh:                                             # a later turn: still over budget
            fh.write(json.dumps(user("Turn 9: " + "word " * 60)) + "\n")
        tc.enqueue(self.con, "s1", path)
        tc.run_worker(self.d, lambda text, ctx=None: {"items": [], "model": "f", "cost_usd": 0.06})
        self.assertNotEqual(feed()["problems"]["budget"], n)                     # the count grows
        tc.enqueue(self.con, "s2", write_transcript(SESSION))                  # a session within budget clears it
        tc.run_worker(self.d, lambda text, ctx=None: {"items": [], "model": "f", "cost_usd": 0.01})
        self.assertNotIn("problems", feed())


class Hook(unittest.TestCase):
    def run_hook(self, d, payload, **env):
        e = {k: v for k, v in os.environ.items() if not k.startswith("MEMCODE_") and k != "CLAUDE_PROJECT_DIR"}
        e.update(PYTHONPATH=str(ROOT), **env)
        return subprocess.run([sys.executable, "-m", "memcode.hook_cli", "Stop"], env=e, text=True,
                              capture_output=True, input=json.dumps(dict(payload, cwd=d)))

    def test_opt_out_and_on_by_default(self):
        d = tempfile.mkdtemp()
        missing = os.path.join(d, "no-such-transcript.jsonl")         # the worker finds nothing: no model call
        self.run_hook(d, {"session_id": "s1", "transcript_path": missing}, MEMCODE_TRANSCRIPT_CAPTURE="0")
        self.assertFalse(os.path.exists(os.path.join(d, ".memcode")))   # off: the store is not even opened
        self.run_hook(d, {"session_id": "s1", "transcript_path": missing}, MEMCODE_TRANSCRIPT_CAPTURE="1")
        con = store.connect(d)
        for _ in range(50):                                             # the detached worker drains the queue
            if tc.pending(con) == 0:
                break
            time.sleep(0.1)
        self.assertEqual(con.execute("SELECT session, status FROM transcript_scans").fetchall()[0][:], ("s1", "idle"))
        con.close()

    def test_default_on_config_off_and_needs_claude(self):
        d = tempfile.mkdtemp()
        clean = {k: v for k, v in os.environ.items() if not k.startswith("MEMCODE_")}
        with mock.patch.dict(os.environ, clean, clear=True):
            with mock.patch("shutil.which", lambda name: "/usr/bin/" + name):
                self.assertTrue(tc.enabled(d))                          # default since 0.9.0
                from memcode.model_capture import write_config
                write_config(d, transcript_capture=False)
                self.assertFalse(tc.enabled(d))                         # `memcode config transcript-capture off`
                os.environ["MEMCODE_TRANSCRIPT_CAPTURE"] = "1"
                self.assertTrue(tc.enabled(d))                          # env beats config
                os.environ["MEMCODE_TRANSCRIPT_CAPTURE"] = "0"
                self.assertFalse(tc.enabled(d))
            os.environ.pop("MEMCODE_TRANSCRIPT_CAPTURE")
            write_config(d, transcript_capture=True)
            with mock.patch("shutil.which", lambda name: None):
                self.assertFalse(tc.enabled(d))                         # no claude CLI: nothing to call


if __name__ == "__main__":
    unittest.main()
