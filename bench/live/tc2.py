"""FROZEN tc2 set (2026-10-18): untuned confirmation gate for opt-in transcript capture, written after the Run 16
fixes and before any memcode_tc run on it. DO NOT EDIT (tests/test_tc2_bench.py checks the hash); add a new set.

Built from bench/live/tc2_candidates.py. Pilots (Haiku), no memory arm involved: without memory 6/6 traps in g_prefix,
g_result_tuple, g_owner_line, d_qa_runner, k_pattern_rule, 5/6 in d_tally_env, 0/6 in k_one_off (a harm control:
nothing should carry); with the needed memory in the prompt 0/4 everywhere. Pilot-driven fixes before freezing: the
two discovered-pitfall repos hid their answer one level deeper (2/6 and 3/6 traps at first).

Offline (memcode/triggers.py at this commit): the pattern triggers capture only k_pattern_rule's rule.

Pre-registered predictions (later sessions, 6 per cell):
  memcode     g_* ~6/6 (nothing captured); d_qa_runner ~nomem; d_tally_env ~nomem or worse (the facts table records
              the working command WITHOUT its TALLY_DATA= prefix); k_pattern_rule ~0; k_one_off 0.
  memcode_tc  g_* ~0-1 (stated in the user's words: stored as rules); d_* ~0-2 (notes from what session 1 found);
              k_pattern_rule ~0; k_one_off 0 (one-off requests are excluded).
Gate (all must hold), memcode_tc vs memcode, same run:
  1. gain scenarios (g_*, d_*): memcode_tc total mistakes lower, Wilson 95% intervals not overlapping;
  2. k_pattern_rule: memcode_tc at most memcode + 1/6; k_one_off: memcode_tc at most 1/6;
  3. precision: every memory transcript capture stored is listed in RESULTS; >= 80% correct, none contradicting the
     user's rules or the repo (env facts listed separately);
  4. capture cost <= $0.01 per teaching session.
"""
import json

TC2 = json.loads(r"""[
 {
  "files": {
   "README.md": "Small utilities.\n",
   "calc.py": "def add(a, b):\n    return a + b\n"
  },
  "later": "Create geo.py with a function that returns the area of a rectangle from its width and height.",
  "name": "g_prefix",
  "oracle": "Rule: every public function name starts with the prefix qx_.",
  "s1": [
   "Add a function sub(a, b) to calc.py.",
   "For context, in this project every public function name starts with the team prefix qx_."
  ],
  "shape": "descriptive_rule",
  "trap_on": "content",
  "trap_path": "(^|/)geo\\.py$",
  "trap_regex": "def (?!qx_|_)\\w+\\(",
  "tuned_on": false
 },
 {
  "files": {
   "README.md": "Small utilities.\n",
   "calc.py": "def add(a, b):\n    return a + b\n"
  },
  "later": "Create parse.py with a function parse_age(text) that turns a string like '42' into an int age between 0 and 150.",
  "name": "g_result_tuple",
  "oracle": "Rule: functions report problems by returning a (value, error) tuple; they never raise.",
  "s1": [
   "Add a function div(a, b) to calc.py.",
   "Worth knowing: functions in this codebase report problems by returning a (value, error) tuple; they do not raise."
  ],
  "shape": "descriptive_rule",
  "trap_on": "content",
  "trap_path": "(^|/)parse\\.py$",
  "trap_regex": "\\braise\\b",
  "tuned_on": false
 },
 {
  "files": {
   "README.md": "Small utilities.\n",
   "calc.py": "def add(a, b):\n    return a + b\n"
  },
  "later": "Create text.py with a function shout(s) that returns s in upper case with an exclamation mark.",
  "name": "g_owner_line",
  "oracle": "Rule: each module's docstring includes the line 'Owner: platform'.",
  "s1": [
   "Add a function mul(a, b) to calc.py.",
   "The way this repo works, each module's docstring includes a line that reads 'Owner: platform'."
  ],
  "shape": "descriptive_rule",
  "trap_on": "content",
  "trap_path": "(^|/)text\\.py$",
  "trap_regex": "\\A(?![\\s\\S]*Owner: platform)",
  "tuned_on": false
 },
 {
  "files": {
   "README.md": "Small utilities. Run the tests with pytest.\n",
   "calc.py": "def add(a, b):\n    return a + b\n",
   "checks/__init__.py": "",
   "checks/verify_calc.py": "import unittest\n\nfrom calc import add\n\n\nclass Add(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n",
   "tools/ci/verify.sh": "#!/bin/sh\nexec python3 -m unittest discover -s checks -p 'verify_*.py' -t . \"$@\"\n"
  },
  "later": "Add a function sub(a, b) to calc.py with a check for it, and run the checks.",
  "name": "d_qa_runner",
  "oracle": "Note: the checks run only with sh tools/ci/verify.sh (they are checks/verify_*.py; plain pytest or unittest finds none).",
  "s1": [
   "Add a function mul(a, b) to calc.py with a check for it, and make sure the checks pass."
  ],
  "shape": "discovered_pitfall",
  "trap_on": "cmd_path",
  "trap_regex": "(?:^|[;&|(]\\s*)(?:python3? -m )?(?:pytest|py\\.test)\\b|python3? -m unittest(?! discover -s checks)",
  "tuned_on": false
 },
 {
  "files": {
   "README.md": "tally: sums expense files. Usage: python3 -m tally report [MONTH]\n",
   "ledger/2026-02.json": "[{\"cents\": 1250}, {\"cents\": 830}]\n",
   "ledger/2026-03.json": "[{\"cents\": 4100}, {\"cents\": 999}, {\"cents\": 51}]\n",
   "tally/__init__.py": "",
   "tally/__main__.py": "import json\nimport sys\nfrom pathlib import Path\n\nfrom tally.paths import data_root\n\n\ndef main(argv):\n    month = argv[2] if len(argv) > 2 else None\n    total = 0\n    for f in sorted(Path(data_root()).glob('*.json')):\n        if month is None or f.stem.startswith(month):\n            total += sum(e['cents'] for e in json.loads(f.read_text()))\n    print(f'total: {total / 100:.2f}')\n\n\nif __name__ == '__main__':\n    main(sys.argv)\n",
   "tally/paths.py": "import os\nimport sys\n\n\ndef data_root():\n    root = os.environ.get('TALLY_DATA')\n    if not root:\n        sys.exit('tally: nothing to report')\n    return root\n"
  },
  "later": "Run the tally report for 2026-03 and tell me the total.",
  "name": "d_tally_env",
  "oracle": "Note: the tally CLI needs TALLY_DATA=ledger set, e.g. TALLY_DATA=ledger python3 -m tally report 2026-03.",
  "s1": [
   "Run the tally report for 2026-02 and tell me the total."
  ],
  "shape": "discovered_pitfall",
  "trap_on": "cmd_path",
  "trap_regex": "(?:^|[;&|]\\s*)python3? -m tally\\b",
  "tuned_on": false
 },
 {
  "control": true,
  "files": {
   "README.md": "Small utilities.\n",
   "calc.py": "def add(a, b):\n    return a + b\n"
  },
  "later": "Create geo.py with a function that returns the area of a rectangle from its width and height.",
  "name": "k_pattern_rule",
  "oracle": "Rule: add type hints to every new function.",
  "s1": [
   "Add a function neg(a) to calc.py.",
   "No - always add type hints to every new function in this repo. Fix neg."
  ],
  "shape": "control_pattern_rule",
  "trap_on": "content",
  "trap_path": "(^|/)geo\\.py$",
  "trap_regex": "def \\w+\\((?![^)]*:)[^)]*\\)",
  "tuned_on": false
 },
 {
  "control": true,
  "files": {
   "README.md": "Small utilities.\n",
   "calc.py": "def add(a, b):\n    return a + b\n"
  },
  "later": "Create geo.py with a function that returns the area of a rectangle from its width and height.",
  "name": "k_one_off",
  "oracle": "",
  "s1": [
   "For this change only, call the new function temp_square: add temp_square(x) to calc.py that returns x squared. We will rename it next week."
  ],
  "shape": "control_one_off",
  "trap_on": "content",
  "trap_path": "(^|/)geo\\.py$",
  "trap_regex": "def temp_\\w*\\(",
  "tuned_on": false
 }
]""")
FROZEN_SHA256 = "00e21b7d134d20b2cbd384b337bb06230f57d50abf037dd166d19cc6e47ac02d"
