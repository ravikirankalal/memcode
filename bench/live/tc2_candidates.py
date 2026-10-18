"""Candidates for tc2: an untuned confirmation set for opt-in transcript capture (memcode/transcript_capture.py),
written after Run 16's fixes and before any memcode_tc run on it. Same two-session shape as the heldout sets
(bench/live/run.py: session 1 = the `s1` turns, then two fresh later sessions with the carried memory).

Shapes:
  G1-G3  gain: a convention the user states only as DESCRIPTION, which the pattern triggers do not capture
  D1-D2  gain: a pitfall nobody states; the agent discovers it in session 1 (a test runner, a required env var)
  K1     control: a rule the pattern triggers DO capture; memcode_tc must not do worse than memcode
  K2     harm control: a one-off instruction ("for this change only"); it must NOT come back later. Without memory
         the trap never fires (no pilot gain expected); any later hit is a memory that should not exist
Arms: memcode (MEMCODE_RETRIEVAL=1) vs memcode_tc (+ MEMCODE_TRANSCRIPT_CAPTURE=1, Haiku). Hierarchy pinned off.
"""
from __future__ import annotations

BASE = {
    "calc.py": "def add(a, b):\n    return a + b\n",
    "README.md": "Small utilities.\n",
}

QA_REPO = {   # D1: pytest/unittest find nothing (checks are verify_*.py); README says pytest; tools/ci/verify.sh runs them
    "calc.py": "def add(a, b):\n    return a + b\n",
    "README.md": "Small utilities. Run the tests with pytest.\n",
    "checks/__init__.py": "",
    "checks/verify_calc.py": ("import unittest\n\nfrom calc import add\n\n\nclass Add(unittest.TestCase):\n"
                              "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n"),
    "tools/ci/verify.sh": "#!/bin/sh\nexec python3 -m unittest discover -s checks -p 'verify_*.py' -t . \"$@\"\n",
}

TALLY_REPO = {   # D2: the CLI exits with an error unless TALLY_DATA points at the data folder
    "README.md": "tally: sums expense files. Usage: python3 -m tally report [MONTH]\n",
    "tally/__init__.py": "",
    "tally/paths.py": ("import os\nimport sys\n\n\ndef data_root():\n"
                       "    root = os.environ.get('TALLY_DATA')\n"
                       "    if not root:\n        sys.exit('tally: nothing to report')\n    return root\n"),
    "tally/__main__.py": (
        "import json\nimport sys\nfrom pathlib import Path\n\nfrom tally.paths import data_root\n\n\n"
        "def main(argv):\n"
        "    month = argv[2] if len(argv) > 2 else None\n"
        "    total = 0\n"
        "    for f in sorted(Path(data_root()).glob('*.json')):\n"
        "        if month is None or f.stem.startswith(month):\n"
        "            total += sum(e['cents'] for e in json.loads(f.read_text()))\n"
        "    print(f'total: {total / 100:.2f}')\n\n\n"
        "if __name__ == '__main__':\n    main(sys.argv)\n"),
    "ledger/2026-02.json": "[{\"cents\": 1250}, {\"cents\": 830}]\n",
    "ledger/2026-03.json": "[{\"cents\": 4100}, {\"cents\": 999}, {\"cents\": 51}]\n",
}

CANDIDATES = [
    {"name": "g_prefix", "shape": "descriptive_rule", "files": dict(BASE),
     "s1": ["Add a function sub(a, b) to calc.py.",
            "For context, in this project every public function name starts with the team prefix qx_."],
     "later": "Create geo.py with a function that returns the area of a rectangle from its width and height.",
     "trap_regex": r"def (?!qx_|_)\w+\(", "trap_on": "content", "trap_path": r"(^|/)geo\.py$",
     "oracle": "Rule: every public function name starts with the prefix qx_."},
    {"name": "g_result_tuple", "shape": "descriptive_rule", "files": dict(BASE),
     "s1": ["Add a function div(a, b) to calc.py.",
            "Worth knowing: functions in this codebase report problems by returning a (value, error) tuple; "
            "they do not raise."],
     "later": "Create parse.py with a function parse_age(text) that turns a string like '42' into an int age "
              "between 0 and 150.",
     "trap_regex": r"\braise\b", "trap_on": "content", "trap_path": r"(^|/)parse\.py$",
     "oracle": "Rule: functions report problems by returning a (value, error) tuple; they never raise."},
    {"name": "g_owner_line", "shape": "descriptive_rule", "files": dict(BASE),
     "s1": ["Add a function mul(a, b) to calc.py.",
            "The way this repo works, each module's docstring includes a line that reads 'Owner: platform'."],
     "later": "Create text.py with a function shout(s) that returns s in upper case with an exclamation mark.",
     "trap_regex": r"\A(?![\s\S]*Owner: platform)", "trap_on": "content", "trap_path": r"(^|/)text\.py$",
     "oracle": "Rule: each module's docstring includes the line 'Owner: platform'."},
    {"name": "d_qa_runner", "shape": "discovered_pitfall", "files": dict(QA_REPO),
     "s1": ["Add a function mul(a, b) to calc.py with a check for it, and make sure the checks pass."],
     "later": "Add a function sub(a, b) to calc.py with a check for it, and run the checks.",
     "trap_regex": r"(?:^|[;&|(]\s*)(?:python3? -m )?(?:pytest|py\.test)\b|python3? -m unittest(?! discover -s checks)",
     "trap_on": "cmd_path",
     "oracle": "Note: the checks run only with sh tools/ci/verify.sh (they are checks/verify_*.py; plain pytest or unittest finds none)."},
    {"name": "d_tally_env", "shape": "discovered_pitfall", "files": dict(TALLY_REPO),
     "s1": ["Run the tally report for 2026-02 and tell me the total."],
     "later": "Run the tally report for 2026-03 and tell me the total.",
     "trap_regex": r"(?:^|[;&|]\s*)python3? -m tally\b", "trap_on": "cmd_path",
     "oracle": "Note: the tally CLI needs TALLY_DATA=ledger set, e.g. TALLY_DATA=ledger python3 -m tally report 2026-03."},
    {"name": "k_pattern_rule", "shape": "control_pattern_rule", "control": True, "files": dict(BASE),
     "s1": ["Add a function neg(a) to calc.py.",
            "No - always add type hints to every new function in this repo. Fix neg."],
     "later": "Create geo.py with a function that returns the area of a rectangle from its width and height.",
     "trap_regex": r"def \w+\((?![^)]*:)[^)]*\)", "trap_on": "content", "trap_path": r"(^|/)geo\.py$",
     "oracle": "Rule: add type hints to every new function."},
    {"name": "k_one_off", "shape": "control_one_off", "control": True, "files": dict(BASE),
     "s1": ["For this change only, call the new function temp_square: add temp_square(x) to calc.py that returns "
            "x squared. We will rename it next week."],
     "later": "Create geo.py with a function that returns the area of a rectangle from its width and height.",
     "trap_regex": r"def temp_\w*\(", "trap_on": "content", "trap_path": r"(^|/)geo\.py$",
     "oracle": ""},
]
