"""FROZEN third held-out set (2026-10-08): HARDER scenarios meant to separate memcode from a hand-written
CLAUDE.md (several rules, rules taught across sessions, a superseded rule, a rule stated as information).
DO NOT EDIT; do not change memcode/ in response to its results (add a new set instead).

Two scenarios probe KNOWN memcode gaps on purpose: m_supersede (no supersession logic: both the old and the
new rule are injected) and m_stated_as_info (the correction trigger needs correction phrasing).
Selected by pilots that never used memcode or claudemd: no memory failed 6/6 on every scenario (traps bite)
and with the rules stated in the prompt (oracle) 0/4 on every scenario (traps are satisfiable).
tests/test_heldout_frozen.py enforces the hash below.
"""
import json

HELDOUT3 = json.loads(r"""[
 {
  "files": {
   "app.py": "def add(a, b):\n    return a + b\n",
   "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
   "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"
  },
  "later": "Create storage.py with a function dataFile(root, filename) that returns the full path of a file inside root, using the datetime module to stamp it with today's date in the name.",
  "name": "m_four_rules",
  "oracle": "Rules: start every new file with the exact line '# Copyright Acme'; end every module with an `if __name__ == '__main__':` demo block; never use from-imports (use 'import x'); never use os or os.path (use pathlib via 'import pathlib').",
  "s1": [
   "Create ops.py with a function mul(a, b).",
   "No - every new file in this repo must start with the exact line '# Copyright Acme'. Fix it and remember that.",
   "Also: every new module must end with an `if __name__ == '__main__':` demo block. Fix it and remember that.",
   "Also: never write 'from x import y' here; always 'import x' and call x.y. Fix it and remember that.",
   "Also: never use os.path or the os module for paths here; always pathlib. Fix it and remember that."
  ],
  "trap_on": "content",
  "trap_regex": "\\A(?!# Copyright Acme)|\\A(?!.*__main__)|(?:\\A|\\n)from \\w[\\w.]* import|\\bimport os\\b|os\\.path",
  "tuned_on": false
 },
 {
  "files": {
   "app.py": "def add(a, b):\n    return a + b\n",
   "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
   "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"
  },
  "later": "Create order.py with a function makeOrder(item, qty) that returns the order record, and a message for it.",
  "name": "m_three_across_sessions",
  "oracle": "Rules: single quotes only (never double quotes anywhere, including docstrings); records are @dataclass, never plain dicts; function names camelCase.",
  "teach": [
   [
    "Create greet.py with a function greeting(name) that returns a hello message.",
    "No - use single quotes only in this repo, never double quotes. Rewrite it and remember that."
   ],
   [
    "Create user.py with a function makeUser(name, email) that returns the user record.",
    "No - never use plain dicts for records in this repo; always a @dataclass. Rewrite it and remember that.",
    "Also: function names here must be camelCase, never snake_case. Rename and remember that."
   ]
  ],
  "trap_on": "content",
  "trap_regex": "\"|return \\{|dict\\(|def [a-z]+_[a-z_]*\\(",
  "tuned_on": false
 },
 {
  "files": {
   "app.py": "def add(a, b):\n    return a + b\n",
   "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
   "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"
  },
  "later": "Create geo.py with a function area(w, h) that raises ValueError if either side is negative.",
  "name": "m_supersede",
  "oracle": "Rule: indent with exactly 2 spaces (never tabs, never 4 spaces).",
  "s1": [
   "Create ops.py with a function mul(a, b) that raises ValueError for non-numbers.",
   "No - this repo indents with tabs, never spaces. Rewrite it and remember that.",
   "Actually, change of plan: the team switched, so indent with exactly 2 spaces from now on, never tabs. Rewrite it and remember that."
  ],
  "trap_on": "content",
  "trap_regex": "def [^\\n]*:\\n(?!  \\S)",
  "tuned_on": false
 },
 {
  "files": {
   "app.py": "def add(a, b):\n    return a + b\n",
   "conftest.py": "import pytest\n\n@pytest.fixture\ndef three():\n    return 3\n",
   "qa": "#!/bin/sh\nexec python3 -m pytest -q \"$@\"\n"
  },
  "later": "Create farewell.py with a function farewell(name) that returns a goodbye message.",
  "name": "m_stated_as_info",
  "oracle": "Rule: use single quotes only, never double quotes.",
  "s1": [
   "Create greet.py with a function greeting(name) that returns a hello message.",
   "Heads up: this team prefers single quotes over double quotes everywhere, so keep to that."
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
  "later": "Create geo.py with a function area(w, h) that raises ValueError if either side is negative.",
  "name": "m_rules_and_distractors",
  "oracle": "Rules: start every new file with the exact line '# Copyright Acme'; indent with exactly 2 spaces (never 4); no return type annotations.",
  "s1": [
   "Create ops.py with a function mul(a, b).",
   "No - every new file must start with the exact line '# Copyright Acme'. Fix it and remember that.",
   "Thanks. Now add a function sub(a, b) to ops.py.",
   "No - this repo indents with exactly 2 spaces, never 4. Rewrite ops.py and remember that.",
   "Now add div(a, b) to ops.py.",
   "No - no return type annotations anywhere in this repo. Remove them and remember that."
  ],
  "trap_on": "content",
  "trap_regex": "\\A(?!# Copyright Acme)|def [^\\n]*:\\n(?!  \\S)|-> ?\\w",
  "tuned_on": false
 }
]""")

FROZEN_SHA256 = "7a4f27f3d83d7c9716606483d44c1b56ec2f35f4ef03f75956ec6bce60c02a34"
