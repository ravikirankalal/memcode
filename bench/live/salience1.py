"""FROZEN Gate 2 ablation set (salience1, 2026-10-10). DO NOT EDIT; add a new set instead.

Question: when more relevant memories compete than retrieval shows (seven rules about the task's directory, TOP_K=5),
does salience ranking put the needed one in front of the agent more often than recency?
- costly (4): the needed rule is the oldest of the seven and the user restated it twice (20 and 6 days ago).
- control (2): the needed rule is cheap and mid-aged; three competing rules carry restatements.
Distractors: 40 rules and 60 notes in synthetic directories, newest of all, filling the session-start block.
Arms: nomem, memcode_retrieval (relevance, ties by recency), memcode_salience (relevance x (1 + salience)).

Pre-registered, deterministic predictions (offline_check at the freezing commit, in PREDICTIONS):
costly: salience surfaces the needed rule in 4/4, recency in 1/4 (s_data_all wins on relevance either way);
control: recency 2/2, salience 1/2 (c_queue_version is pushed to rank 6).
Gate 2 passes if memcode_salience has a lower trap rate than memcode_retrieval on costly variants AND the
net over all six is better; a loss on c_queue_version is expected and counts against it.
Selection: every scenario trapped 6/6 without memory; oracle (all seven rules in the prompt) 0/4, except
s_reports_ctx 1/4 (a helper function without ctx). c_worker_logger was dropped (0/6 without memory: its
convention is visible in worker/log.py) and replaced by c_queue_version (6/6, 0/4).
tests/test_heldout_frozen.py enforces the hash below.
"""
import json

SALIENCE1 = json.loads(r"""[
 {
  "dir": "billing",
  "files": {
   "README.md": "Demo service.\n",
   "api/__init__.py": "",
   "api/errors.py": "class ApiError(Exception):\n    pass\n\n\ndef fail(code, msg):\n    raise ApiError(code, msg)\n",
   "api/users.py": "USERS = {}\n",
   "billing/__init__.py": "",
   "billing/invoice.py": "def total_cents(items):\n    return sum(i['cents'] for i in items)\n",
   "data/etl.py": "def run():\n    pass\n",
   "docs/index.md": "# Docs\n",
   "frontend/app.js": "export const app = {};\n",
   "infra/deploy.sh": "#!/bin/sh\n",
   "mobile/App.kt": "class App\n",
   "reports/__init__.py": "",
   "reports/weekly.py": "",
   "scripts/release.sh": "#!/bin/sh\n",
   "search/__init__.py": "",
   "search/index.py": "def tokens(text):\n    return text.split()\n",
   "tools/__init__.py": "",
   "tools/sync.py": "import argparse\n\n\ndef main():\n    p = argparse.ArgumentParser()\n    p.add_argument('src')\n    return p.parse_args()\n",
   "util/__init__.py": "",
   "util/dates.py": "import datetime\n",
   "worker/__init__.py": "",
   "worker/log.py": "import logging\n\n\ndef get(name):\n    return logging.getLogger('worker.' + name)\n"
  },
  "history": [
   {
    "age": 45,
    "needed": true,
    "repeats": [
     20,
     6
    ],
    "text": "Every new module under billing/ starts with the exact line '# PCI-SCOPE'."
   },
   {
    "age": 30,
    "needed": false,
    "repeats": [],
    "text": "Money amounts in billing/ are integers in cents, never floats."
   },
   {
    "age": 25,
    "needed": false,
    "repeats": [],
    "text": "Functions in billing/ carry full type hints on parameters and return values."
   },
   {
    "age": 18,
    "needed": false,
    "repeats": [],
    "text": "Modules in billing/ keep no module-level mutable state."
   },
   {
    "age": 12,
    "needed": false,
    "repeats": [],
    "text": "Docstrings in billing/ name the currency the function assumes."
   },
   {
    "age": 8,
    "needed": false,
    "repeats": [],
    "text": "Functions in billing/ stay under 40 lines; split helpers out instead."
   },
   {
    "age": 4,
    "needed": false,
    "repeats": [],
    "text": "Records returned from billing/ functions are plain dicts with snake_case keys."
   }
  ],
  "kind": "costly",
  "later": "Create billing/refunds.py with a function refund(amount_cents, reason) that returns a refund record.",
  "n_notes": 60,
  "n_rules": 40,
  "name": "s_billing_header",
  "oracle": "Rule: every new module under billing/ starts with the exact line '# PCI-SCOPE'.",
  "target": "Every new module under billing/ starts with the exact line '# PCI-SCOPE'.",
  "trap_on": "content",
  "trap_path": "(^|/)billing/refunds\\.py$",
  "trap_regex": "\\A(?!# PCI-SCOPE)",
  "tuned_on": false
 },
 {
  "dir": "data",
  "files": {
   "README.md": "Demo service.\n",
   "api/__init__.py": "",
   "api/errors.py": "class ApiError(Exception):\n    pass\n\n\ndef fail(code, msg):\n    raise ApiError(code, msg)\n",
   "api/users.py": "USERS = {}\n",
   "billing/__init__.py": "",
   "billing/invoice.py": "def total_cents(items):\n    return sum(i['cents'] for i in items)\n",
   "data/etl.py": "def run():\n    pass\n",
   "docs/index.md": "# Docs\n",
   "frontend/app.js": "export const app = {};\n",
   "infra/deploy.sh": "#!/bin/sh\n",
   "mobile/App.kt": "class App\n",
   "reports/__init__.py": "",
   "reports/weekly.py": "",
   "scripts/release.sh": "#!/bin/sh\n",
   "search/__init__.py": "",
   "search/index.py": "def tokens(text):\n    return text.split()\n",
   "tools/__init__.py": "",
   "tools/sync.py": "import argparse\n\n\ndef main():\n    p = argparse.ArgumentParser()\n    p.add_argument('src')\n    return p.parse_args()\n",
   "util/__init__.py": "",
   "util/dates.py": "import datetime\n",
   "worker/__init__.py": "",
   "worker/log.py": "import logging\n\n\ndef get(name):\n    return logging.getLogger('worker.' + name)\n"
  },
  "history": [
   {
    "age": 45,
    "needed": true,
    "repeats": [
     20,
     6
    ],
    "text": "Every new module under data/ ends with an __all__ list naming its public functions."
   },
   {
    "age": 30,
    "needed": false,
    "repeats": [],
    "text": "Functions in data/ take rows as a list of dicts and never mutate their input."
   },
   {
    "age": 25,
    "needed": false,
    "repeats": [],
    "text": "Modules in data/ import only from the standard library."
   },
   {
    "age": 18,
    "needed": false,
    "repeats": [],
    "text": "Functions in data/ carry type hints on parameters and return values."
   },
   {
    "age": 12,
    "needed": false,
    "repeats": [],
    "text": "Public functions in data/ have a one-line docstring."
   },
   {
    "age": 8,
    "needed": false,
    "repeats": [],
    "text": "Empty values in data/ rows are None or the empty string, nothing else."
   },
   {
    "age": 4,
    "needed": false,
    "repeats": [],
    "text": "Helpers in data/ that are not public start with an underscore."
   }
  ],
  "kind": "costly",
  "later": "Create data/clean.py with a function drop_empty(rows) that removes rows whose values are all empty.",
  "n_notes": 60,
  "n_rules": 40,
  "name": "s_data_all",
  "oracle": "Rule: every new module under data/ ends with an __all__ list naming its public functions.",
  "target": "Every new module under data/ ends with an __all__ list naming its public functions.",
  "trap_on": "content",
  "trap_path": "(^|/)data/clean\\.py$",
  "trap_regex": "\\A(?!.*__all__)",
  "tuned_on": false
 },
 {
  "dir": "search",
  "files": {
   "README.md": "Demo service.\n",
   "api/__init__.py": "",
   "api/errors.py": "class ApiError(Exception):\n    pass\n\n\ndef fail(code, msg):\n    raise ApiError(code, msg)\n",
   "api/users.py": "USERS = {}\n",
   "billing/__init__.py": "",
   "billing/invoice.py": "def total_cents(items):\n    return sum(i['cents'] for i in items)\n",
   "data/etl.py": "def run():\n    pass\n",
   "docs/index.md": "# Docs\n",
   "frontend/app.js": "export const app = {};\n",
   "infra/deploy.sh": "#!/bin/sh\n",
   "mobile/App.kt": "class App\n",
   "reports/__init__.py": "",
   "reports/weekly.py": "",
   "scripts/release.sh": "#!/bin/sh\n",
   "search/__init__.py": "",
   "search/index.py": "def tokens(text):\n    return text.split()\n",
   "tools/__init__.py": "",
   "tools/sync.py": "import argparse\n\n\ndef main():\n    p = argparse.ArgumentParser()\n    p.add_argument('src')\n    return p.parse_args()\n",
   "util/__init__.py": "",
   "util/dates.py": "import datetime\n",
   "worker/__init__.py": "",
   "worker/log.py": "import logging\n\n\ndef get(name):\n    return logging.getLogger('worker.' + name)\n"
  },
  "history": [
   {
    "age": 45,
    "needed": true,
    "repeats": [
     20,
     6
    ],
    "text": "Functions defined in search/ are named with a _q suffix, for example rank_q or tokens_q."
   },
   {
    "age": 30,
    "needed": false,
    "repeats": [],
    "text": "Text handling in search/ works on str only, never bytes."
   },
   {
    "age": 25,
    "needed": false,
    "repeats": [],
    "text": "Functions in search/ are pure: no I/O and no global state."
   },
   {
    "age": 18,
    "needed": false,
    "repeats": [],
    "text": "Functions in search/ carry type hints on parameters and return values."
   },
   {
    "age": 12,
    "needed": false,
    "repeats": [],
    "text": "Public functions in search/ have a one-line docstring with an example query."
   },
   {
    "age": 8,
    "needed": false,
    "repeats": [],
    "text": "Regular expressions in search/ are compiled once at module level."
   },
   {
    "age": 4,
    "needed": false,
    "repeats": [],
    "text": "Functions in search/ return new strings and lists rather than modifying arguments."
   }
  ],
  "kind": "costly",
  "later": "Add a function to search/index.py that lowercases a query and strips punctuation.",
  "n_notes": 60,
  "n_rules": 40,
  "name": "s_search_suffix",
  "oracle": "Rule: functions defined in search/ are named with a _q suffix, e.g. normalize_q.",
  "target": "Functions defined in search/ are named with a _q suffix, for example rank_q or tokens_q.",
  "trap_on": "content",
  "trap_path": "(^|/)search/index\\.py$",
  "trap_regex": "def (?!\\w*_q\\()(?!tokens\\()\\w+\\(",
  "tuned_on": false
 },
 {
  "dir": "reports",
  "files": {
   "README.md": "Demo service.\n",
   "api/__init__.py": "",
   "api/errors.py": "class ApiError(Exception):\n    pass\n\n\ndef fail(code, msg):\n    raise ApiError(code, msg)\n",
   "api/users.py": "USERS = {}\n",
   "billing/__init__.py": "",
   "billing/invoice.py": "def total_cents(items):\n    return sum(i['cents'] for i in items)\n",
   "data/etl.py": "def run():\n    pass\n",
   "docs/index.md": "# Docs\n",
   "frontend/app.js": "export const app = {};\n",
   "infra/deploy.sh": "#!/bin/sh\n",
   "mobile/App.kt": "class App\n",
   "reports/__init__.py": "",
   "reports/weekly.py": "",
   "scripts/release.sh": "#!/bin/sh\n",
   "search/__init__.py": "",
   "search/index.py": "def tokens(text):\n    return text.split()\n",
   "tools/__init__.py": "",
   "tools/sync.py": "import argparse\n\n\ndef main():\n    p = argparse.ArgumentParser()\n    p.add_argument('src')\n    return p.parse_args()\n",
   "util/__init__.py": "",
   "util/dates.py": "import datetime\n",
   "worker/__init__.py": "",
   "worker/log.py": "import logging\n\n\ndef get(name):\n    return logging.getLogger('worker.' + name)\n"
  },
  "history": [
   {
    "age": 45,
    "needed": true,
    "repeats": [
     20,
     6
    ],
    "text": "Every function in reports/ takes ctx as its first parameter."
   },
   {
    "age": 30,
    "needed": false,
    "repeats": [],
    "text": "Summaries built in reports/ are plain dicts with snake_case keys."
   },
   {
    "age": 25,
    "needed": false,
    "repeats": [],
    "text": "Functions in reports/ carry type hints on parameters and return values."
   },
   {
    "age": 18,
    "needed": false,
    "repeats": [],
    "text": "Money in reports/ is summed as integer cents, never floats."
   },
   {
    "age": 12,
    "needed": false,
    "repeats": [],
    "text": "Public functions in reports/ have a one-line docstring."
   },
   {
    "age": 8,
    "needed": false,
    "repeats": [],
    "text": "Functions in reports/ never print; they return data for the caller to render."
   },
   {
    "age": 4,
    "needed": false,
    "repeats": [],
    "text": "Date ranges in reports/ are half-open: start inclusive, end exclusive."
   }
  ],
  "kind": "costly",
  "later": "Add a function to reports/weekly.py that builds a weekly summary dict from a list of orders.",
  "n_notes": 60,
  "n_rules": 40,
  "name": "s_reports_ctx",
  "oracle": "Rule: every function in reports/ takes ctx as its first parameter.",
  "target": "Every function in reports/ takes ctx as its first parameter.",
  "trap_on": "content",
  "trap_path": "(^|/)reports/weekly\\.py$",
  "trap_regex": "def \\w+\\((?!\\s*ctx\\b)",
  "tuned_on": false
 },
 {
  "dir": "tools",
  "files": {
   "README.md": "Demo service.\n",
   "api/__init__.py": "",
   "api/errors.py": "class ApiError(Exception):\n    pass\n\n\ndef fail(code, msg):\n    raise ApiError(code, msg)\n",
   "api/users.py": "USERS = {}\n",
   "billing/__init__.py": "",
   "billing/invoice.py": "def total_cents(items):\n    return sum(i['cents'] for i in items)\n",
   "data/etl.py": "def run():\n    pass\n",
   "docs/index.md": "# Docs\n",
   "frontend/app.js": "export const app = {};\n",
   "infra/deploy.sh": "#!/bin/sh\n",
   "mobile/App.kt": "class App\n",
   "reports/__init__.py": "",
   "reports/weekly.py": "",
   "scripts/release.sh": "#!/bin/sh\n",
   "search/__init__.py": "",
   "search/index.py": "def tokens(text):\n    return text.split()\n",
   "tools/__init__.py": "",
   "tools/sync.py": "import argparse\n\n\ndef main():\n    p = argparse.ArgumentParser()\n    p.add_argument('src')\n    return p.parse_args()\n",
   "util/__init__.py": "",
   "util/dates.py": "import datetime\n",
   "worker/__init__.py": "",
   "worker/log.py": "import logging\n\n\ndef get(name):\n    return logging.getLogger('worker.' + name)\n"
  },
  "history": [
   {
    "age": 10,
    "needed": true,
    "repeats": [],
    "text": "Command-line options in tools/ are spelled as one lowercase word without dashes inside, like --dryrun or --nocache."
   },
   {
    "age": 30,
    "needed": false,
    "repeats": [
     20,
     6
    ],
    "text": "Scripts in tools/ exit with status 2 on bad arguments and 1 on runtime errors."
   },
   {
    "age": 25,
    "needed": false,
    "repeats": [
     20,
     6
    ],
    "text": "Scripts in tools/ print progress to stderr and results to stdout."
   },
   {
    "age": 18,
    "needed": false,
    "repeats": [
     20,
     6
    ],
    "text": "Functions in tools/ carry type hints on parameters and return values."
   },
   {
    "age": 12,
    "needed": false,
    "repeats": [],
    "text": "Every script in tools/ has a module docstring describing its usage."
   },
   {
    "age": 8,
    "needed": false,
    "repeats": [],
    "text": "Paths in tools/ are handled with pathlib, never os.path string joins."
   },
   {
    "age": 4,
    "needed": false,
    "repeats": [],
    "text": "Scripts in tools/ keep argument parsing inside main()."
   }
  ],
  "kind": "control",
  "later": "Add an option to tools/sync.py that makes it skip writing any files (a dry run).",
  "n_notes": 60,
  "n_rules": 40,
  "name": "c_tools_flags",
  "oracle": "Rule: command-line options in tools/ are one lowercase word without inner dashes, e.g. --dryrun.",
  "target": "Command-line options in tools/ are spelled as one lowercase word without dashes inside, like --dryrun or --nocache.",
  "trap_on": "content",
  "trap_path": "(^|/)tools/sync\\.py$",
  "trap_regex": "--dry[-_]run",
  "tuned_on": false
 },
 {
  "dir": "queue",
  "files": {
   "README.md": "Demo service.\n",
   "api/__init__.py": "",
   "api/errors.py": "class ApiError(Exception):\n    pass\n\n\ndef fail(code, msg):\n    raise ApiError(code, msg)\n",
   "api/users.py": "USERS = {}\n",
   "billing/__init__.py": "",
   "billing/invoice.py": "def total_cents(items):\n    return sum(i['cents'] for i in items)\n",
   "data/etl.py": "def run():\n    pass\n",
   "docs/index.md": "# Docs\n",
   "frontend/app.js": "export const app = {};\n",
   "infra/deploy.sh": "#!/bin/sh\n",
   "ledger/__init__.py": "",
   "ledger/entries.py": "ENTRIES = []\n",
   "mobile/App.kt": "class App\n",
   "queue/__init__.py": "",
   "queue/worker.py": "def run(job):\n    return job()\n",
   "reports/__init__.py": "",
   "reports/weekly.py": "",
   "scripts/release.sh": "#!/bin/sh\n",
   "search/__init__.py": "",
   "search/index.py": "def tokens(text):\n    return text.split()\n",
   "tools/__init__.py": "",
   "tools/sync.py": "import argparse\n\n\ndef main():\n    p = argparse.ArgumentParser()\n    p.add_argument('src')\n    return p.parse_args()\n",
   "util/__init__.py": "",
   "util/dates.py": "import datetime\n",
   "worker/__init__.py": "",
   "worker/log.py": "import logging\n\n\ndef get(name):\n    return logging.getLogger('worker.' + name)\n"
  },
  "history": [
   {
    "age": 10,
    "needed": true,
    "repeats": [],
    "text": "Every new module under queue/ defines a module-level constant SCHEMA_VERSION = 2."
   },
   {
    "age": 30,
    "needed": false,
    "repeats": [
     20,
     6
    ],
    "text": "Functions in queue/ never sleep in a loop without a maximum attempt count."
   },
   {
    "age": 25,
    "needed": false,
    "repeats": [
     20,
     6
    ],
    "text": "Functions in queue/ carry type hints on parameters and return values."
   },
   {
    "age": 18,
    "needed": false,
    "repeats": [
     20,
     6
    ],
    "text": "Exceptions in queue/ are re-raised after logging, never swallowed."
   },
   {
    "age": 12,
    "needed": false,
    "repeats": [],
    "text": "Public functions in queue/ have a one-line docstring."
   },
   {
    "age": 8,
    "needed": false,
    "repeats": [],
    "text": "Modules in queue/ keep no module-level mutable state."
   },
   {
    "age": 4,
    "needed": false,
    "repeats": [],
    "text": "Delays computed in queue/ are floats in seconds and are capped at 300."
   }
  ],
  "kind": "control",
  "later": "Create queue/retry_policy.py with a function backoff(attempt) that returns the delay in seconds for a retry.",
  "n_notes": 60,
  "n_rules": 40,
  "name": "c_queue_version",
  "oracle": "Rule: every new module under queue/ defines a module-level constant SCHEMA_VERSION = 2.",
  "target": "Every new module under queue/ defines a module-level constant SCHEMA_VERSION = 2.",
  "trap_on": "content",
  "trap_path": "(^|/)queue/retry_policy\\.py$",
  "trap_regex": "\\A(?!.*SCHEMA_VERSION\\s*=\\s*2\\b)",
  "tuned_on": false
 }
]""")

PREDICTIONS = json.loads(r"""{"c_queue_version": {"kind": "control", "relevance_injected": 5, "relevance_pinned": false, "relevance_rank": 4, "relevance_relevant_scored": 7, "relevance_retrieved": true, "relevance_surfaced": true, "salience_injected": 5, "salience_pinned": false, "salience_rank": 5, "salience_relevant_scored": 7, "salience_retrieved": false, "salience_surfaced": false}, "c_tools_flags": {"kind": "control", "relevance_injected": 5, "relevance_pinned": false, "relevance_rank": 0, "relevance_relevant_scored": 7, "relevance_retrieved": true, "relevance_surfaced": true, "salience_injected": 5, "salience_pinned": false, "salience_rank": 0, "salience_relevant_scored": 7, "salience_retrieved": true, "salience_surfaced": true}, "s_billing_header": {"kind": "costly", "relevance_injected": 5, "relevance_pinned": false, "relevance_rank": 6, "relevance_relevant_scored": 7, "relevance_retrieved": false, "relevance_surfaced": false, "salience_injected": 5, "salience_pinned": false, "salience_rank": 3, "salience_relevant_scored": 7, "salience_retrieved": true, "salience_surfaced": true}, "s_data_all": {"kind": "costly", "relevance_injected": 5, "relevance_pinned": false, "relevance_rank": 1, "relevance_relevant_scored": 7, "relevance_retrieved": true, "relevance_surfaced": true, "salience_injected": 5, "salience_pinned": false, "salience_rank": 1, "salience_relevant_scored": 7, "salience_retrieved": true, "salience_surfaced": true}, "s_reports_ctx": {"kind": "costly", "relevance_injected": 5, "relevance_pinned": false, "relevance_rank": 6, "relevance_relevant_scored": 7, "relevance_retrieved": false, "relevance_surfaced": false, "salience_injected": 5, "salience_pinned": false, "salience_rank": 2, "salience_relevant_scored": 7, "salience_retrieved": true, "salience_surfaced": true}, "s_search_suffix": {"kind": "costly", "relevance_injected": 5, "relevance_pinned": false, "relevance_rank": 6, "relevance_relevant_scored": 7, "relevance_retrieved": false, "relevance_surfaced": false, "salience_injected": 5, "salience_pinned": false, "salience_rank": 2, "salience_relevant_scored": 7, "salience_retrieved": true, "salience_surfaced": true}}""")

FROZEN_SHA256 = "1295a2f11ec69a7e3b92cb61f05a1ebd8ebd0cf1191380d491241ba140082731"
