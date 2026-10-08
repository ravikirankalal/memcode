"""FROZEN fourth held-out set (2026-10-08), built to VALIDATE the capture changes made after heldout3:
statement capture (rules stated as information) and the text-only-gap tier. DO NOT EDIT; do not change
memcode/ in response to its results (add a new set instead).

Pre-registered predictions for memcode (written before it was ever run on this set; checked offline against
memcode/triggers.py at commit ff8a4c3):
  n_info_header, n_text_gap_main, n_text_gap_two_rules, n_mixed: every rule turn is captured -> expect 0 failures.
  n_info_tabs: "FYI, in this repo we indent with tabs rather than spaces." has no normative word, so the
    statement pattern does NOT match -> expect nothing stored and 10/10 failures. It is kept on purpose as an
    out-of-distribution test of whether the pattern generalises beyond the phrasing it was designed from.
Pilots (no memcode/claudemd involved): no memory failed 6/6 on every scenario; with the rules stated in the
prompt (oracle) 0/4 on every scenario. tests/test_heldout_frozen.py enforces the hash below.
"""
import json

HELDOUT4 = json.loads(r"""[
 {
  "files": {
   "app.py": "def add(a, b):\n    return a + b\n",
   "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
   "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"
  },
  "later": "Create geo.py with a function area(w, h) that raises ValueError if either side is negative.",
  "name": "n_info_tabs",
  "oracle": "Rule: indent with tabs (never spaces).",
  "s1": [
   "Create ops.py with a function mul(a, b) that raises ValueError for non-numbers.",
   "FYI, in this repo we indent with tabs rather than spaces."
  ],
  "trap_on": "content",
  "trap_regex": "def [^\\n]*:\\n(?!\\t)",
  "tuned_on": false
 },
 {
  "files": {
   "app.py": "def add(a, b):\n    return a + b\n",
   "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
   "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"
  },
  "later": "Create geo.py with a function area(w, h).",
  "name": "n_info_header",
  "oracle": "Rule: every new file starts with the exact line '# Copyright Acme'.",
  "s1": [
   "Create ops.py with a function mul(a, b).",
   "Just so you know, our standard is that every new file starts with the exact line '# Copyright Acme'."
  ],
  "trap_on": "content",
  "trap_regex": "\\A(?!# Copyright Acme)",
  "tuned_on": false
 },
 {
  "files": {
   "app.py": "def add(a, b):\n    return a + b\n",
   "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
   "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"
  },
  "later": "Create geo.py with a function area(w, h).",
  "name": "n_text_gap_main",
  "oracle": "Rule: every new module ends with an `if __name__ == '__main__':` demo block.",
  "s1": [
   "Create ops.py with a function mul(a, b).",
   "What does mul return if I pass it two strings? Just explain, do not change anything.",
   "Also: every new module must end with an `if __name__ == '__main__':` demo block. Remember that."
  ],
  "trap_on": "content",
  "trap_regex": "\\A(?!.*__main__)",
  "tuned_on": false
 },
 {
  "files": {
   "app.py": "def add(a, b):\n    return a + b\n",
   "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
   "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"
  },
  "later": "Create geo.py with a function area(w, h) that raises ValueError if either side is negative.",
  "name": "n_text_gap_two_rules",
  "oracle": "Rules: indent with tabs (never spaces); start every new file with the exact line '# Copyright Acme'.",
  "s1": [
   "Create ops.py with a function mul(a, b).",
   "Is mul safe to call with negative numbers? Just answer.",
   "From now on, indent with tabs, never spaces.",
   "Why did you choose those parameter names? Just answer.",
   "Always start every new file with the exact line '# Copyright Acme'."
  ],
  "trap_on": "content",
  "trap_regex": "def [^\\n]*:\\n(?!\\t)|\\A(?!# Copyright Acme)",
  "tuned_on": false
 },
 {
  "files": {
   "app.py": "def add(a, b):\n    return a + b\n",
   "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
   "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"
  },
  "later": "Create storage.py with a function logFile(root, name) that returns the full path of a log file inside root, with a message string describing it.",
  "name": "n_mixed",
  "oracle": "Rules: single quotes only (never double quotes anywhere); never use os or os.path (use pathlib); every new file starts with the exact line '# Copyright Acme'.",
  "s1": [
   "Create paths.py with a function dataFile(root, filename) that returns the full path of a file inside root.",
   "Note that we only use single quotes in this codebase.",
   "Does that function touch the filesystem? Just answer.",
   "Never use os.path or the os module for paths here; always pathlib. Remember that.",
   "No - every new file must start with the exact line '# Copyright Acme'. Fix it and remember that."
  ],
  "trap_on": "content",
  "trap_regex": "\"|\\bimport os\\b|os\\.path|\\A(?!# Copyright Acme)",
  "tuned_on": false
 }
]""")

FROZEN_SHA256 = "df213b3277ddaf68ecfc28681f0c3b97b03acab070e41097007c72dcd82a0c7e"
