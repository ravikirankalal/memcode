"""Run the repo's unit tests against a copy of the repo with proposal.diff + proposal_tests.diff applied (the
worktree itself is not edited). proposal_tests.diff only rewrites two test prompts that used bare complaints
("no, that's wrong") as their example of a rule; the tests' intent (replay, dedupe) is unchanged.

  python3 bench/precision/check_proposal_suite.py        # prints the unittest summary of the patched copy
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

with tempfile.TemporaryDirectory() as tmp:
    for d in ("memcode", "tests", "bench", "hooks", "bin"):
        if (ROOT / d).exists():
            shutil.copytree(ROOT / d, Path(tmp) / d, ignore=shutil.ignore_patterns("__pycache__", ".memcode"))
    for f in ROOT.glob("*.md"):
        shutil.copy(f, tmp)
    for diff in ("proposal.diff", "proposal_tests.diff"):    # the code change + two tests whose prompts were junk
        subprocess.run(["patch", "-s", "-p1", "-d", tmp, "-i", str(ROOT / "bench/precision" / diff)], check=True)
    (Path(tmp) / "tests" / "test_precision_bench.py").unlink()  # freezes the CURRENT numbers; meaningless here
    p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=tmp,
                       capture_output=True, text=True)
    out = p.stderr.splitlines()
    fails = [l for l in out if l.startswith(("FAIL:", "ERROR:"))]
    print("\n".join(fails + out[-3:]))
    sys.exit(p.returncode)
