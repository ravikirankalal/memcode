"""FROZEN budget-pressure set (2026-10-08). DO NOT EDIT; add a new set instead.

Each scenario seeds ~109 memories (45 distractor rules, 63 distractor notes, 1 target = the oldest), so the capped
session-start pinned block shows 57 of them and leaves the target out. Arms: nomem, claudemd_full (all memories in
CLAUDE.md, loaded whole), memcode (pinned only), memcode_retrieval (+ per-prompt retrieval).

Pre-registered, deterministic predictions (bench/live/pressure.py offline_check, memcode at the freezing commit):
  target in pinned block: no, in all 4.   retrieval (relevance): surfaces the target at rank 1, alone, in all 4.
  Therefore expected: memcode (pinned only) behaves like nomem; memcode_retrieval behaves like claudemd_full.
  The salience arm is not run: offline it ranks identically to relevance here (seeded memories have no history).
Selection: no-memory pilot 6/6 failures and oracle pilot 0/4 failures for every kept scenario. Dropped:
  p_api_fail (0/6 without memory: the agent finds api/errors.fail itself), p_worker_logger (0/6; regex also flagged
  compliant code), p_dates_utc (0-1/6: model already writes tz-aware code), p_reports_ctx (oracle 1/4: helpers break
  "every function" even when the rule is in the prompt). Retrieval gained directory-scope matching after the FIRST
  offline check of these candidates (before any model outcome), see RESULTS.md.
tests/test_heldout_frozen.py enforces the hash below.
"""
import json

PRESSURE1 = json.loads(r"""[
 {
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
  "later": "Create billing/refunds.py with a function refund(amount_cents, reason) that returns a refund record.",
  "name": "p_billing_header",
  "oracle": "Rule: every new module under billing/ starts with the exact line '# PCI-SCOPE'.",
  "target": [
   "correction",
   "Every new module under billing/ starts with the exact line '# PCI-SCOPE'.",
   ""
  ],
  "trap_on": "content",
  "trap_path": "(^|/)billing/",
  "trap_regex": "\\A(?!# PCI-SCOPE)",
  "tuned_on": false
 },
 {
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
  "later": "Add an option to tools/sync.py that makes it skip writing any files (a dry run).",
  "name": "p_tools_flags",
  "oracle": "Rule: command-line options in tools/ are one lowercase word without inner dashes, e.g. --dryrun.",
  "target": [
   "correction",
   "Command-line options in tools/ are spelled as one lowercase word without dashes inside, like --dryrun or --nocache.",
   ""
  ],
  "trap_on": "content",
  "trap_path": "(^|/)tools/sync\\.py$",
  "trap_regex": "--dry[-_]run",
  "tuned_on": false
 },
 {
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
  "later": "Create data/clean.py with a function drop_empty(rows) that removes rows whose values are all empty.",
  "name": "p_data_all",
  "oracle": "Rule: every new module under data/ ends with an __all__ list naming its public functions.",
  "target": [
   "correction",
   "Every new module under data/ ends with an __all__ list naming its public functions.",
   ""
  ],
  "trap_on": "content",
  "trap_path": "(^|/)data/",
  "trap_regex": "\\A(?!.*__all__)",
  "tuned_on": false
 },
 {
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
  "later": "Add a function to search/index.py that lowercases a query and strips punctuation.",
  "name": "p_search_suffix",
  "oracle": "Rule: functions defined in search/ are named with a _q suffix, e.g. normalize_q.",
  "target": [
   "correction",
   "Functions defined in search/ are named with a _q suffix, for example rank_q or tokens_q.",
   ""
  ],
  "trap_on": "content",
  "trap_path": "(^|/)search/",
  "trap_regex": "def (?!\\w*_q\\()(?!tokens\\()\\w+\\(",
  "tuned_on": false
 }
]""")

PREDICTIONS = json.loads(r"""{"p_billing_header": {"memories": 109, "rank_relevance": 0, "rank_salience": 0, "retrieved_relevance": true, "retrieved_salience": true, "target_pinned": false}, "p_data_all": {"memories": 109, "rank_relevance": 0, "rank_salience": 0, "retrieved_relevance": true, "retrieved_salience": true, "target_pinned": false}, "p_search_suffix": {"memories": 109, "rank_relevance": 0, "rank_salience": 0, "retrieved_relevance": true, "retrieved_salience": true, "target_pinned": false}, "p_tools_flags": {"memories": 109, "rank_relevance": 0, "rank_salience": 0, "retrieved_relevance": true, "retrieved_salience": true, "target_pinned": false}}""")

FROZEN_SHA256 = "f50222a899ffda4434da826073ecf163d6e2cffe85322dd12810ac073f57e6b1"
