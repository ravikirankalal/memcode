"""FROZEN held-out scenarios (2026-10-07). DO NOT EDIT, and do not change memcode/triggers.py
or memcode/pinned.py in response to results on these. Add a new set instead.

Selected from bench/live/candidates.py by a no-memory pilot (6 runs each; memcode never run on
them before freezing). Kept: the four that always fail without memory (6/6). Dropped:
h_no_docstrings and h_no_type_hints (0/6 without memory: floor effect, no signal). Deviation
from the planned 15-85% window: no candidate fell inside it, so the 100%-failure ones were kept.
tests/test_heldout_frozen.py enforces the hash below.
"""
import json

HELDOUT = json.loads(r"""[
 {
  "files": {
   "app.py": "def add(a, b):\n    return a + b\n",
   "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
   "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"
  },
  "later": "Create geo.py with a function area(w, h) that raises ValueError if either side is negative.",
  "name": "h_tabs",
  "s1": [
   "Create ops.py with a function mul(a, b) that raises ValueError for non-numbers.",
   "No - this repo indents with tabs, never spaces. Rewrite it with tabs and remember that."
  ],
  "trap_on": "content",
  "trap_regex": "(?m)^ +\\S",
  "tuned_on": false
 },
 {
  "files": {
   "app.py": "def add(a, b):\n    return a + b\n",
   "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
   "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"
  },
  "later": "Create farewell.py with a function farewell(name) that returns a goodbye message.",
  "name": "h_single_quotes",
  "s1": [
   "Create greet.py with a function greeting(name) that returns a hello message.",
   "No - use single quotes only in this repo, never double quotes. Rewrite it and remember that."
  ],
  "trap_on": "content",
  "trap_regex": "\"",
  "tuned_on": false
 },
 {
  "files": {
   "app.py": "def add(a, b):\n    return a + b\n",
   "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
   "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"
  },
  "later": "Add a test file covering add() with negative numbers.",
  "name": "h_check_files",
  "s1": [
   "Add a test file for add().",
   "No - test files in this repo are named check_<name>.py, never test_*.py. Rename it and remember that."
  ],
  "trap_regex": "/test_[^/]*\\.py$",
  "tuned_on": false
 },
 {
  "files": {
   "app.py": "def add(a, b):\n    return a + b\n",
   "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
   "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"
  },
  "later": "Create tax.py with a function that applies a tax rate to a price.",
  "name": "h_camel_case",
  "s1": [
   "Create pricing.py with a function that computes the total price from a list of prices.",
   "No - function names here must be camelCase, e.g. computeTotal, never snake_case. Rename it and remember that."
  ],
  "trap_on": "content",
  "trap_regex": "def [a-z]+_[a-z_]*\\(",
  "tuned_on": false
 }
]""")

FROZEN_SHA256 = "7fbe04844b3a0d36236496b185820b1e42950830a0cbe1ab5ca0b1a3840b3cb8"
