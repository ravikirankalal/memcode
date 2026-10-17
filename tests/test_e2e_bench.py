"""e2e1 self-checks (no model calls): every canonical day is healthy, the never-stated execution facts are real
pitfalls, and the judges accept the reference solution of each measured task and reject violations."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bench.live import e2e1_candidates as S
from bench.live import e2e1_project as P
from bench.live import e2e_run as R


def materialize(files: dict) -> Path:
    d = Path(tempfile.mkdtemp(prefix="e2e1-"))
    for n, c in files.items():
        (d / n).parent.mkdir(parents=True, exist_ok=True)
        (d / n).write_text(c)
    return d


def sh(d: Path, cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, cwd=d, capture_output=True, text=True, timeout=120)


class CanonicalDays(unittest.TestCase):
    def test_every_day_passes_its_checks(self):
        for day in range(1, 7):
            d = materialize(P.files_for_day(day))
            r = sh(d, "make check")
            self.assertEqual(r.returncode, 0, f"day {day}: {r.stdout[-400:]}{r.stderr[-400:]}")
            self.assertIn("OK", r.stdout + r.stderr, day)

    @unittest.skipUnless(shutil.which("ruff"), "needs ruff")
    def test_every_day_is_lint_clean(self):
        for day in range(1, 7):
            r = sh(materialize(P.files_for_day(day)), "make lint")
            self.assertEqual(r.returncode, 0, f"day {day}: {r.stdout[-400:]}")

    def test_cli_runs_as_module(self):
        r = sh(materialize(P.files_for_day(4)), f"{sys.executable} -m shelf list")
        self.assertEqual(r.returncode, 0, r.stderr)


class ExecutionFactsArePitfalls(unittest.TestCase):
    """E1/E2 must be real traps: the obvious commands fail or test nothing."""

    def setUp(self):
        self.d = materialize(P.files_for_day(4))

    def test_e1_obvious_test_commands_collect_nothing(self):
        out = sh(self.d, f"{sys.executable} -m unittest 2>&1").stdout
        self.assertRegex(out, S.JUDGE["E1"]["no_tests"])
        if shutil.which("pytest"):
            r = sh(self.d, "pytest -q 2>&1")
            self.assertRegex(r.stdout, r"no tests ran|collected 0 items")
        self.assertIsNone(shutil.which("tox"), "tox must be absent for E1 to be a trap")

    def test_e2_shelf_command_not_installed(self):
        self.assertIsNone(shutil.which("shelf"))


class Judges(unittest.TestCase):
    """judge_files on the reference solution of each feature task = no mistakes; injected violations = mistakes."""

    def judged(self, later, mutate=None, message="shelf: reference solution"):
        start = P.files_for_day(later["day"])
        end = dict(P.files_for_day(later["day"] + 1))
        if mutate:
            mutate(end)
        d = materialize(start)
        g = ["git", "-c", "user.email=a@b", "-c", "user.name=a"]
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        subprocess.run(["git", "add", "."], cwd=d, check=True)
        subprocess.run(g + ["commit", "-qm", "start of day"], cwd=d, check=True)
        for n, c in end.items():
            (d / n).parent.mkdir(parents=True, exist_ok=True)
            (d / n).write_text(c)
        subprocess.run(["git", "add", "."], cwd=d, check=True)
        subprocess.run(g + ["commit", "-qm", message], cwd=d, check=True)
        return R.judge_files(later, d, start, S.JUDGE)

    def feature_tasks(self):
        return [l for l in S.LATER if l["module"]]

    def test_reference_solutions_comply(self):
        for later in self.feature_tasks():
            res = self.judged(later)
            bad = {k: v for k, v in res.items() if k.endswith("_mistake") and v}
            self.assertEqual(bad, {}, (later["name"], res))
            self.assertEqual(res["incomplete"], [], later["name"])
            self.assertTrue(res["checks_pass_end"], later["name"])

    def test_violations_are_caught(self):
        for later in self.feature_tasks():
            mod = later["module"]

            def no_spdx(f):
                f[mod] = f[mod].replace(P.SPDX, "", 1)

            def builtin_error(f):
                f[mod] = f[mod] + "\n\ndef _bad():\n    raise ValueError('x')\n"

            def raw_clock(f):
                f[mod] = f[mod] + "\n\nimport datetime\n_T = datetime.datetime.now()\n"

            def no_changes(f):
                f["CHANGES.md"] = P.files_for_day(later["day"])["CHANGES.md"]

            for rule, mut in (("C1", no_spdx), ("C2", builtin_error), ("C4", raw_clock), ("C3", no_changes)):
                res = self.judged(later, mut)
                self.assertTrue(res[f"{rule}_mistake"], f"{later['name']} {rule}")

            def no_bump(f):
                f.update({k: P.files_for_day(later["day"])[k] for k in ("pyproject.toml", "shelf/__init__.py")})
            self.assertTrue(self.judged(later, no_bump)["P2_mistake"], later["name"])
            self.assertTrue(self.judged(later, message="add recent command")["P3_mistake"], later["name"])


if __name__ == "__main__":
    unittest.main()
