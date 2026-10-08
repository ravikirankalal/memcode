"""FROZEN second held-out set (2026-10-08). DO NOT EDIT; do not change memcode/ in response to its results.

Built AFTER the pinned-block fix (user rules outside the untrusted wrapper; corrections anchored repo-wide)
and the clean-copy methodology, so it can validate them. Selected from bench/live/candidates2.py by a
no-memory pilot (6 runs each; memcode never run on them first): k_pathlib 6/6, k_dataclass 6/6,
k_main_block 6/6, k_header 6/6, k_module_imports 4/6 failed without memory. Dropped: k_app_error (0/6,
floor effect). Evidence of every kept pilot hit was inspected. tests/test_heldout_frozen.py enforces the hash.
"""
import json

HELDOUT2 = json.loads(r"""[
 {
  "files": {
   "app.py": "def add(a, b):\n    return a + b\n",
   "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
   "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"
  },
  "later": "Create storage.py with a function dataFile(root, filename) that returns the full path of a file inside root.",
  "name": "k_pathlib",
  "s1": [
   "Create paths.py with a function configFile(base_dir, name) that returns the full path of a file inside base_dir.",
   "No - never use os.path or the os module for paths in this repo; always pathlib. Rewrite it and remember that."
  ],
  "trap_on": "content",
  "trap_regex": "os\\.path|import os\\b",
  "tuned_on": false
 },
 {
  "files": {
   "app.py": "def add(a, b):\n    return a + b\n",
   "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
   "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"
  },
  "later": "Create order.py with a function makeOrder(item, qty) that returns the order record.",
  "name": "k_dataclass",
  "s1": [
   "Create user.py with a function makeUser(name, email) that returns the user record.",
   "No - never use plain dicts for records in this repo; always a @dataclass. Rewrite it and remember that."
  ],
  "trap_on": "content",
  "trap_regex": "return \\{|dict\\(",
  "tuned_on": false
 },
 {
  "files": {
   "app.py": "def add(a, b):\n    return a + b\n",
   "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
   "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"
  },
  "later": "Create timeutil.py with a function today() that returns today's date as an ISO string using datetime.",
  "name": "k_module_imports",
  "s1": [
   "Create stats.py with a function meanOf(values) using the statistics module.",
   "No - never use 'from x import y' in this repo; always 'import x' and call x.y. Rewrite it and remember that."
  ],
  "trap_on": "content",
  "trap_regex": "(?m)^from \\w[\\w.]* import",
  "tuned_on": false
 },
 {
  "files": {
   "app.py": "def add(a, b):\n    return a + b\n",
   "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
   "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"
  },
  "later": "Create geo.py with a function area(w, h).",
  "name": "k_main_block",
  "s1": [
   "Create ops.py with a function mul(a, b).",
   "No - every new module here must end with an `if __name__ == '__main__':` block that runs a tiny demo. Add it and remember that."
  ],
  "trap_on": "content",
  "trap_regex": "(?s)\\A(?!.*__main__)",
  "tuned_on": false
 },
 {
  "files": {
   "app.py": "def add(a, b):\n    return a + b\n",
   "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
   "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"
  },
  "later": "Create geo.py with a function area(w, h).",
  "name": "k_header",
  "s1": [
   "Create ops.py with a function mul(a, b).",
   "No - every new file in this repo must start with the exact line '# Copyright Acme'. Add it and remember that."
  ],
  "trap_on": "content",
  "trap_regex": "\\A(?!# Copyright Acme)",
  "tuned_on": false
 }
]""")

FROZEN_SHA256 = "640668427db186d1767e140def404872fa8ebff50acd0f9b1ee87d28ac25e565"
