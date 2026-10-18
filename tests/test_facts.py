import json
import os
import tempfile
import unittest
from pathlib import Path

from memcode import facts, mcp_server, pinned, store, tree


def bash(cmd, code=0):
    return {"kind": "tool_result", "session": "s", "tool": "Bash", "input": {"command": cmd}, "command": cmd,
            "file_path": None, "exit_code": code, "output": ""}


class Splitting(unittest.TestCase):
    def test_fd_redirects_are_not_operators(self):
        self.assertEqual(facts.split_ops("python3 -m unittest discover -s tests 2>&1 | tail -3"),
                         [("python3 -m unittest discover -s tests", "|"), ("tail -3", "")])

    def test_operators_and_quotes(self):
        self.assertEqual(facts.split_ops('a && b || c; grep "x|y;z" f'),
                         [("a", "&&"), ("b", "||"), ("c", ";"), ("grep x|y;z f", "")])

    def test_normalize_rejects_non_reusable(self):
        for seg in ("1", "-d $S/x", "python3 -c 'print(1)'", "python3 -", "ls -la", "git status",
                    "python3 /tmp/x/prof.py", "echo $HOME", "for x in a b", "git..."):
            self.assertIsNone(facts.normalize(seg), seg)
        self.assertEqual(facts.normalize("FOO=1 timeout 60 npm test >out.txt"), "FOO=1 npm test")
        self.assertEqual(facts.normalize("NO_COLOR=1 CI=true npm test"), "npm test")          # cosmetic: dropped
        self.assertIsNone(facts.normalize("API_TOKEN=[REDACTED] npm test"))                   # secret: not reusable
        self.assertIsNone(facts.normalize("DATA=$HOME/x npm test"))
        self.assertEqual(facts.normalize("TALLY_DATA=/r/ledger python3 -m tally", "/r"), "TALLY_DATA=ledger python3 -m tally")
        self.assertIsNone(facts.normalize("TALLY_DATA=/tmp/x python3 -m tally", "/r"))       # outside the repo

    def test_roles(self):
        cases = {"python3 -m pytest -q": "test", "python3 -m unittest discover -s tests": "test", "npm test": "test",
                 "go test ./...": "test", "cargo build": "build", "npm run build": "build", "make": "build",
                 "ruff check .": "lint", "npx eslint src": "lint", "mypy .": "typecheck", "npx tsc --noEmit": "typecheck",
                 "black .": "format", "pip install -r requirements.txt": "install", "npm ci": "install",
                 "npm run dev": "run", "python3 -m memcode.cli list": "run", "docker compose up": None}
        for cmd, role in cases.items():
            self.assertEqual(facts.role_of(cmd), role, cmd)


class Observe(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.con = store.connect(self.d)

    def tearDown(self):
        self.con.close()

    def row(self, key):
        if key.startswith("cmd:"):
            key = "cmd:" + facts.cmd_key(key[4:])
        return self.con.execute("SELECT * FROM facts WHERE key=?", (key,)).fetchone()

    def test_success_failure_and_attribution(self):
        facts.observe(self.con, self.d, bash("cd sub && python3 -m pytest -q"))
        facts.observe(self.con, self.d, bash("python3 -m pytest -q", 1))
        facts.observe(self.con, self.d, bash("npm run build && python3 -m pytest -q", 1))  # 2 commands: not attributable
        r = self.row("cmd:python3 -m pytest -q")
        self.assertEqual((r["runs"], r["ok"], r["fail"], r["role"]), (2, 1, 1, "test"))
        self.assertIsNone(self.row("cmd:npm run build"))

    def test_pipes_and_fallbacks_do_not_prove_success(self):
        facts.observe(self.con, self.d, bash("python3 -m unittest discover -s tests 2>&1 | tail -3"))
        facts.observe(self.con, self.d, bash("python3 -m pyflakes x.py 2>/dev/null || python3 -m py_compile x.py"))
        r = self.row("cmd:python3 -m unittest discover -s tests")
        self.assertEqual((r["runs"], r["ok"]), (1, 0))
        self.assertIsNone(self.row("cmd:python3 -m pyflakes x.py"))          # had a fallback: weak evidence
        self.assertEqual(self.row("cmd:python3 -m py_compile x.py")["ok"], 1)
        self.assertIsNone(self.row("cmd:1"))

    def test_piped_runs_use_the_summary_line(self):
        def run(cmd, out):
            ev = bash(cmd); ev["output"] = out
            facts.observe(self.con, self.d, ev)
        run("python3 -m unittest discover -s tests 2>&1 | tail -3", "Ran 290 tests in 41.2s\n\nOK")
        run("python3 -m unittest discover -s tests 2>&1 | tail -3", "Ran 290 tests in 41.2s\n\nOK (skipped=2)")
        run("python3 -m unittest discover -s tests 2>&1 | tail -3", "Ran 290 tests\n\nFAILED (failures=1)")
        run("python3 -m unittest discover -s tests 2>&1 | tail -3", "Ran 290 tests")      # summary cut: unknown
        r = self.row("cmd:python3 -m unittest discover -s tests")
        self.assertEqual((r["runs"], r["ok"], r["fail"]), (4, 2, 1))
        run("python3 -m pytest -q 2>&1 | head -5", "....\n5 passed in 0.12s")          # head may cut failures
        run("python3 -m pytest -q | grep -v warn", "1 failed, 4 passed in 0.3s")       # failure seen through grep
        run("python3 -m pytest -q | tail -1", "===== 5 passed, 1 skipped in 0.12s =====")
        r = self.row("cmd:python3 -m pytest -q")
        self.assertEqual((r["runs"], r["ok"], r["fail"]), (3, 1, 1))
        run("go test ./... 2>&1 | tail", "ok  \texample.com/a\t0.1s\n--- FAIL: TestX (0.0s)\nFAIL")
        self.assertEqual(self.row("cmd:go test ./...")["fail"], 1)
        run("ruff check . | tail -2", "All checks passed!")
        run("npm run build && npm test | tail", "Tests:       3 passed, 3 total")     # not a lone command
        self.assertEqual(self.row("cmd:ruff check .")["ok"], 1)
        self.assertEqual(self.row("cmd:npm test")["ok"], 0)
        run("python3 -m unittest 2>&1 | tail -1", "OK" + "x" * 10 + "...")             # stored-event truncation
        self.assertEqual(self.row("cmd:python3 -m unittest")["ok"], 0)
        run("python3 -m ruff --version", "ruff 0.6.0")                               # probes are not facts
        self.assertIsNone(self.row("cmd:python3 -m ruff --version"))

    def test_commands_outside_repo_and_unknown_exit(self):
        facts.observe(self.con, self.d, bash("cd /tmp/scratch && python3 prof.py"))
        facts.observe(self.con, self.d, bash("cd $S && python3 prof_wt.py"))
        ev = bash("npm test"); ev["exit_code"] = None                         # e.g. Codex
        facts.observe(self.con, self.d, ev)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM facts").fetchone()[0], 0)

    def test_missing_tool_from_path_not_output(self):
        facts.observe(self.con, self.d, bash("sqlite3-nonexistent-xyz db.sqlite 'select 1'", 127))
        facts.observe(self.con, self.d, bash("python3 -m nothing", 127))      # python3 exists: not reported
        keys = [r[0] for r in self.con.execute("SELECT key FROM facts WHERE category='env'")]
        self.assertEqual(keys, ["env:missing:sqlite3-nonexistent-xyz"])

    def test_missing_tool_fact_clears_once_installed(self):
        facts.observe(self.con, self.d, bash("sqlite3-nonexistent-xyz db 'select 1'", 127))
        self.assertIsNotNone(self.row("env:missing:sqlite3-nonexistent-xyz"))
        facts.observe(self.con, self.d, bash("sqlite3-nonexistent-xyz db 'select 1'"))     # ran fine this time
        self.assertIsNone(self.row("env:missing:sqlite3-nonexistent-xyz"))
        facts.observe(self.con, self.d, bash("sqlite3-nonexistent-xyz db", 127))
        from unittest import mock
        with mock.patch.object(facts.shutil, "which", lambda w: "/usr/bin/" + w):          # installed meanwhile
            facts.infer(self.con)
        self.assertIsNone(self.row("env:missing:sqlite3-nonexistent-xyz"))

    def test_required_env_prefix_is_kept_in_the_shown_command(self):     # tc2 d_tally_env (Run 17)
        facts.observe(self.con, self.d, bash("python3 -m tally report 2026-02", 1))
        facts.observe(self.con, self.d, bash("TALLY_DATA=ledger python3 -m tally report 2026-02"))
        r = self.row("cmd:TALLY_DATA=ledger python3 -m tally report 2026-02")
        self.assertEqual((r["role"], r["ok"]), ("run", 1))
        self.assertIn("run: `TALLY_DATA=ledger python3 -m tally report 2026-02`", "\n".join(facts.lines(self.con)))

    def test_redaction(self):
        facts.observe(self.con, self.d, bash("deploy --token=abcd1234secret9876 --env prod"))
        for (v,) in self.con.execute("SELECT value FROM facts"):
            self.assertNotIn("abcd1234secret9876", v)


class RepoScan(unittest.TestCase):
    def test_manifests_refresh_on_change_and_vanish(self):
        d = tempfile.mkdtemp()
        Path(d, "package.json").write_text(json.dumps({"scripts": {"build": "vite build", "test": "vitest",
                                                                   "dev": "vite"}}))
        Path(d, "Makefile").write_text("lint:\n\truff check .\n.PHONY: lint\n")
        Path(d, "tests").mkdir(); Path(d, "tests", "test_a.py").write_text("")
        con = store.connect(d)
        tree.scan_repo(con, d)
        facts.scan_repo(con, d)
        vals = {r["key"]: (r["role"], r["value"]) for r in facts.list_facts(con)}
        self.assertEqual(vals["repo:npm:build"], ("build", "npm run build"))
        self.assertEqual(vals["repo:npm:test"], ("test", "npm test"))
        self.assertEqual(vals["repo:npm:dev"], ("run", "npm run dev"))
        self.assertEqual(vals["repo:make:lint"], ("lint", "make lint"))
        self.assertIn("tests/", vals["repo:tests_dir"][1])
        self.assertEqual(facts.scan_repo(con, d), 0)                          # unchanged: nothing rewritten
        Path(d, "package.json").write_text(json.dumps({"scripts": {"start": "node server.js"}}))
        facts.scan_repo(con, d)
        keys = {r["key"] for r in facts.list_facts(con)}
        self.assertIn("repo:npm:start", keys); self.assertNotIn("repo:npm:build", keys)
        os.remove(Path(d, "Makefile"))
        facts.scan_repo(con, d)
        self.assertNotIn("repo:make:lint", {r["key"] for r in facts.list_facts(con)})
        con.close()


class Noise(unittest.TestCase):
    """issue #36: pieces of compound commands and one-off actions are not repo command facts"""
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.con = store.connect(self.d)

    def tearDown(self):
        self.con.close()

    def commands(self):
        return sorted(r[0] for r in self.con.execute("SELECT value FROM facts WHERE category='command'"))

    def test_compound_calls_leave_no_pieces(self):
        for cmd in ("for c in b8dcf40 34302cd dde5424 d005c97; do git show --stat $c; done",
                    "for c in \\\n  b8dcf40 34302cd\ndo copy h-dev develop-08858f6.keys-off $c\ndone",
                    "echo $(git rev-parse HEAD)", "V=$(mvn -v) && echo $V",
                    "find . -name x | xargs grep -l y; diff <(git merge-base origin/develop origin/main) z",
                    "f() { make build; }; f", "(cd jobs-core && mvn -q test)", "make build\nmake test"):
            facts.observe(self.con, self.d, bash(cmd))
        self.assertEqual(self.commands(), [])

    def test_one_off_actions_are_not_facts(self):
        for cmd in ("glab mr close 326", "glab mr view 326 -F json", "glab mr view 328 -F json",
                    "gh repo view ravikirankalal/memcode --json name", "claude plugin update memcode@memcode",
                    "claude plugin --help", "kubectl -n jobs exec deploy/worker -- wget -qO- http://localhost/api/v1/jobs",
                    "kubectl -n jobs exec deploy/worker -- wget -S -qO- http://localhost/api/v1/jobs",
                    "mvn help", "npm view react version", "git show b8dcf40"):
            facts.observe(self.con, self.d, bash(cmd))
        self.assertEqual(self.commands(), [])
        for cmd in ("claude plugin test mods/memcode-status", "claude plugin validate .claude-plugin/plugin.json --strict"):
            facts.observe(self.con, self.d, bash(cmd))                  # a plugin repo's own checks are workflows
        self.assertEqual(self.commands(), ["claude plugin test mods/memcode-status",
                                           "claude plugin validate .claude-plugin/plugin.json --strict"])

    def test_variants_merge_and_show_the_newest_passing_one(self):
        facts.observe(self.con, self.d, bash("python3 -m pytest -q"))
        facts.observe(self.con, self.d, bash("python3 -m pytest -x --tb short"))
        facts.observe(self.con, self.d, bash("python3 -m pytest -k slow", 1))
        (r,) = self.con.execute("SELECT * FROM facts WHERE category='command'").fetchall()
        self.assertEqual((r["runs"], r["ok"], r["fail"], r["value"]), (3, 2, 1, "python3 -m pytest -x --tb short"))

    def test_chains_keep_role_commands_only(self):
        facts.observe(self.con, self.d, bash("npm run build && npm test"))
        facts.observe(self.con, self.d, bash("make deploy-check && notify-team done"))
        self.assertEqual(self.commands(), ["npm run build", "npm test"])

    def test_unconfirmed_commands_are_not_shown_at_session_start(self):
        facts.observe(self.con, self.d, bash("mvn -q test | tail -5"))       # piped, no summary: unknown
        facts.observe(self.con, self.d, bash("./gradlew build | tail -3"))
        self.assertEqual(len(self.commands()), 2)
        self.assertEqual([l for l in facts.lines(self.con) if "`" in l], [])
        for _ in range(2):
            facts.observe(self.con, self.d, bash("./gradlew build"))
        self.assertIn("build: `./gradlew build` (ran 3x, 2 confirmed ok)", "\n".join(facts.lines(self.con)))

    def test_old_store_is_cleaned_once(self):
        now = 1.0
        facts.ensure(self.con)
        for v, ok in (("b8dcf40 34302cd dde5424 d005c97", 0), ("mvn -v)", 0), ("glab mr view 326 -F json", 1),
                      ("claude plugin --help", 1), ("python3 -m pytest -q", 2), ("python3 -m pytest -x", 1)):
            self.con.execute("INSERT INTO facts(key,category,role,value,source,runs,ok,fail,first_seen,last_seen) "
                             "VALUES(?,?,?,?,?,?,?,?,?,?)", (f"cmd:{v}", "command", facts.role_of(v), v, "observed",
                                                            ok, ok, 0, now, now))
        self.con.execute("DELETE FROM facts_meta"); self.con.commit()
        facts.ensure(self.con)
        rows = self.con.execute("SELECT key, runs, ok FROM facts WHERE category='command'").fetchall()
        self.assertEqual([tuple(r) for r in rows], [("cmd:python3 -m pytest", 3, 3)])
        facts.ensure(self.con)                                                 # once: version recorded
        self.assertEqual(self.con.execute("SELECT v FROM facts_meta").fetchone()[0], facts.FACTS_VERSION)


class InferUserRender(unittest.TestCase):
    def test_lines_prefer_confirmed_commands_and_include_everything(self):
        d = tempfile.mkdtemp()
        con = store.connect(d)
        Path(d, "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
        facts.scan_repo(con, d)
        for _ in range(2):
            facts.observe(con, d, bash("npx jest --ci"))
        facts.observe(con, d, bash("missing-tool-qq x", 127))
        for _ in range(2):
            facts.observe(con, d, bash("make deploy", 2))
        store.add_memory(con, "revert", "reverted", "billing/x.py", None, {})
        store.add_memory(con, "revert", "reverted", "billing/y.py", None, {})
        facts.infer(con)
        facts.set_user(con, "deploy", "Deploys only from release/* branches")
        out = "\n".join(facts.lines(con))
        self.assertIn("test: `npx jest --ci` (ran 2x, 2 confirmed ok)", out)   # observed beats declared npm test
        self.assertIn("Deploys only from release/* branches", out)
        self.assertIn("`missing-tool-qq` is not installed", out)
        self.assertIn("`make deploy` has failed 2x and never passed", out)
        self.assertIn("billing is fragile", out)
        block = pinned.render_pinned(con, d)
        self.assertIn("## Facts", block.split(pinned.NOTES_OPEN)[1])           # inside the untrusted wrapper
        self.assertEqual(facts.remove(con, "deploy"), 1)
        con.close()

    def test_backfill_guard_and_mcp(self):
        d = tempfile.mkdtemp()
        con = store.connect(d)
        store.log_event(con, "s", "tool_result", bash("cargo test"))
        self.assertEqual(facts.backfill(con, d), 1)
        with self.assertRaises(ValueError):
            facts.backfill(con, d)                                            # would double-count
        facts.backfill(con, d, force=True)
        self.assertEqual(con.execute("SELECT runs FROM facts WHERE key='cmd:cargo test'").fetchone()[0], 1)
        con.close()
        out = mcp_server.call_tool(d, "memory_facts", {"role": "test"})
        self.assertIn("cargo test", out)


if __name__ == "__main__":
    unittest.main()
