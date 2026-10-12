"""FROZEN Gate 2b set (salience2, 2026-10-10). DO NOT EDIT; add a new set instead.

Question: does split ranking (MEMCODE_RANK=split: relevance top-5 kept, up to 2 extra slots for memories with strong
cost evidence) keep salience's wins on restated rules without its losses on cheap needed rules? Split was designed
after salience1, so it is judged here, on fresh conventions and history shapes salience1 lacked.
- costly (restated twice), costly_once (restated once: below split's promotion threshold), costly_crowded (three other
  restated rules compete for the two extra slots), costly_wide (nine relevant rules), control_heavy (needed rule cheap,
  four competitors restated), control_newest (needed rule is the newest).
Arms: nomem, memcode_retrieval (recency), memcode_salience, memcode_split.

Pre-registered, deterministic predictions (PREDICTIONS, offline_check at the freezing commit), needed rule surfaced:
recency 2/6 (controls only); salience 5/6 (misses t_geo_srid, control_heavy); split 5/6 (misses t_notify_header,
costly_once). Split shows 1-2 extra memories per prompt.
Criterion: split is adopted as the candidate default ranking if its repeated-mistake rate is no worse than salience's
over all six AND better than recency's, with no control worse than recency.
Selection: all six trapped 6/6 without memory and 0/4 with all relevant rules in the prompt. Dropped after the pilot:
t_payments_idem and t_shipping_prefix (conventions visible in the repo files: 0/6 without memory).
tests/test_heldout_frozen.py enforces the hash below.
"""
import json

SALIENCE2 = json.loads(r"""[
 {
  "dir": "inventory",
  "files": {
   "README.md": "Demo service.\n",
   "api/__init__.py": "",
   "api/errors.py": "class ApiError(Exception):\n    pass\n\n\ndef fail(code, msg):\n    raise ApiError(code, msg)\n",
   "api/users.py": "USERS = {}\n",
   "auth/__init__.py": "",
   "auth/session.py": "SESSIONS = {}\n",
   "billing/__init__.py": "",
   "billing/invoice.py": "def total_cents(items):\n    return sum(i['cents'] for i in items)\n",
   "data/etl.py": "def run():\n    pass\n",
   "docs/index.md": "# Docs\n",
   "export/__init__.py": "",
   "export/csv_out.py": "import csv\n",
   "frontend/app.js": "export const app = {};\n",
   "geo/__init__.py": "",
   "geo/points.py": "def point(lat, lon):\n    return (lat, lon)\n",
   "infra/deploy.sh": "#!/bin/sh\n",
   "inventory/__init__.py": "",
   "inventory/stock.py": "STOCK = {}\n",
   "mobile/App.kt": "class App\n",
   "notify/__init__.py": "",
   "notify/email.py": "def send(to, body):\n    return (to, body)\n",
   "orders/__init__.py": "",
   "orders/cart.py": "CART = {}\n",
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
    "age": 50,
    "needed": true,
    "repeats": [
     21,
     5
    ],
    "text": "Every new module under inventory/ defines a module-level constant OWNER = \"team-stock\"."
   },
   {
    "age": 33,
    "needed": false,
    "repeats": [],
    "text": "Functions in inventory/ carry full type hints on parameters and return values."
   },
   {
    "age": 26,
    "needed": false,
    "repeats": [],
    "text": "Public functions in inventory/ have a one-line docstring."
   },
   {
    "age": 19,
    "needed": false,
    "repeats": [],
    "text": "Modules in inventory/ keep no module-level mutable state."
   },
   {
    "age": 11,
    "needed": false,
    "repeats": [],
    "text": "Functions in inventory/ never print; they return values or raise."
   },
   {
    "age": 7,
    "needed": false,
    "repeats": [],
    "text": "Functions in inventory/ stay under 40 lines; split helpers out instead."
   },
   {
    "age": 3,
    "needed": false,
    "repeats": [],
    "text": "Errors in inventory/ are raised as ValueError with a message naming the bad argument."
   }
  ],
  "kind": "costly",
  "later": "Create inventory/restock.py with a function needs_restock(item, threshold) that says whether an item is below its threshold.",
  "n_notes": 60,
  "n_rules": 40,
  "name": "t_inventory_owner",
  "oracle": "Rule: every new module under inventory/ defines a module-level constant OWNER = \"team-stock\".",
  "target": "Every new module under inventory/ defines a module-level constant OWNER = \"team-stock\".",
  "trap_on": "content",
  "trap_path": "(^|/)inventory/restock\\.py$",
  "trap_regex": "\\A(?!.*OWNER\\s*=\\s*[\\\"']team-stock[\\\"'])",
  "tuned_on": false
 },
 {
  "dir": "notify",
  "files": {
   "README.md": "Demo service.\n",
   "api/__init__.py": "",
   "api/errors.py": "class ApiError(Exception):\n    pass\n\n\ndef fail(code, msg):\n    raise ApiError(code, msg)\n",
   "api/users.py": "USERS = {}\n",
   "auth/__init__.py": "",
   "auth/session.py": "SESSIONS = {}\n",
   "billing/__init__.py": "",
   "billing/invoice.py": "def total_cents(items):\n    return sum(i['cents'] for i in items)\n",
   "data/etl.py": "def run():\n    pass\n",
   "docs/index.md": "# Docs\n",
   "export/__init__.py": "",
   "export/csv_out.py": "import csv\n",
   "frontend/app.js": "export const app = {};\n",
   "geo/__init__.py": "",
   "geo/points.py": "def point(lat, lon):\n    return (lat, lon)\n",
   "infra/deploy.sh": "#!/bin/sh\n",
   "inventory/__init__.py": "",
   "inventory/stock.py": "STOCK = {}\n",
   "mobile/App.kt": "class App\n",
   "notify/__init__.py": "",
   "notify/email.py": "def send(to, body):\n    return (to, body)\n",
   "orders/__init__.py": "",
   "orders/cart.py": "CART = {}\n",
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
    "age": 40,
    "needed": true,
    "repeats": [
     6
    ],
    "text": "Every new module under notify/ starts with the exact line '# owner: notify-team'."
   },
   {
    "age": 30,
    "needed": false,
    "repeats": [],
    "text": "Functions in notify/ carry full type hints on parameters and return values."
   },
   {
    "age": 24,
    "needed": false,
    "repeats": [],
    "text": "Public functions in notify/ have a one-line docstring."
   },
   {
    "age": 17,
    "needed": false,
    "repeats": [],
    "text": "Modules in notify/ keep no module-level mutable state."
   },
   {
    "age": 12,
    "needed": false,
    "repeats": [],
    "text": "Functions in notify/ never print; they return values or raise."
   },
   {
    "age": 6,
    "needed": false,
    "repeats": [],
    "text": "Functions in notify/ stay under 40 lines; split helpers out instead."
   },
   {
    "age": 2,
    "needed": false,
    "repeats": [],
    "text": "Errors in notify/ are raised as ValueError with a message naming the bad argument."
   }
  ],
  "kind": "costly_once",
  "later": "Create notify/sms.py with a function send_sms(number, text) that returns a message record.",
  "n_notes": 60,
  "n_rules": 40,
  "name": "t_notify_header",
  "oracle": "Rule: every new module under notify/ starts with the exact line '# owner: notify-team'.",
  "target": "Every new module under notify/ starts with the exact line '# owner: notify-team'.",
  "trap_on": "content",
  "trap_path": "(^|/)notify/sms\\.py$",
  "trap_regex": "\\A(?!# owner: notify-team)",
  "tuned_on": false
 },
 {
  "dir": "orders",
  "files": {
   "README.md": "Demo service.\n",
   "api/__init__.py": "",
   "api/errors.py": "class ApiError(Exception):\n    pass\n\n\ndef fail(code, msg):\n    raise ApiError(code, msg)\n",
   "api/users.py": "USERS = {}\n",
   "auth/__init__.py": "",
   "auth/session.py": "SESSIONS = {}\n",
   "billing/__init__.py": "",
   "billing/invoice.py": "def total_cents(items):\n    return sum(i['cents'] for i in items)\n",
   "data/etl.py": "def run():\n    pass\n",
   "docs/index.md": "# Docs\n",
   "export/__init__.py": "",
   "export/csv_out.py": "import csv\n",
   "frontend/app.js": "export const app = {};\n",
   "geo/__init__.py": "",
   "geo/points.py": "def point(lat, lon):\n    return (lat, lon)\n",
   "infra/deploy.sh": "#!/bin/sh\n",
   "inventory/__init__.py": "",
   "inventory/stock.py": "STOCK = {}\n",
   "mobile/App.kt": "class App\n",
   "notify/__init__.py": "",
   "notify/email.py": "def send(to, body):\n    return (to, body)\n",
   "orders/__init__.py": "",
   "orders/cart.py": "CART = {}\n",
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
    "age": 44,
    "needed": true,
    "repeats": [
     20,
     9
    ],
    "text": "Every function in orders/ takes a parameter named trace_id."
   },
   {
    "age": 40,
    "needed": false,
    "repeats": [
     15,
     4
    ],
    "text": "Functions in orders/ carry full type hints on parameters and return values."
   },
   {
    "age": 37,
    "needed": false,
    "repeats": [
     18,
     3
    ],
    "text": "Public functions in orders/ have a one-line docstring."
   },
   {
    "age": 35,
    "needed": false,
    "repeats": [
     12,
     2
    ],
    "text": "Modules in orders/ keep no module-level mutable state."
   },
   {
    "age": 10,
    "needed": false,
    "repeats": [],
    "text": "Functions in orders/ never print; they return values or raise."
   },
   {
    "age": 6,
    "needed": false,
    "repeats": [],
    "text": "Functions in orders/ stay under 40 lines; split helpers out instead."
   },
   {
    "age": 2,
    "needed": false,
    "repeats": [],
    "text": "Errors in orders/ are raised as ValueError with a message naming the bad argument."
   }
  ],
  "kind": "costly_crowded",
  "later": "Add a function to orders/cart.py that computes the total quantity of items in a cart.",
  "n_notes": 60,
  "n_rules": 40,
  "name": "t_orders_trace",
  "oracle": "Rule: every function in orders/ takes a parameter named trace_id.",
  "target": "Every function in orders/ takes a parameter named trace_id.",
  "trap_on": "content",
  "trap_path": "(^|/)orders/cart\\.py$",
  "trap_regex": "def \\w+\\((?![^)]*trace_id)",
  "tuned_on": false
 },
 {
  "dir": "auth",
  "files": {
   "README.md": "Demo service.\n",
   "api/__init__.py": "",
   "api/errors.py": "class ApiError(Exception):\n    pass\n\n\ndef fail(code, msg):\n    raise ApiError(code, msg)\n",
   "api/users.py": "USERS = {}\n",
   "auth/__init__.py": "",
   "auth/session.py": "SESSIONS = {}\n",
   "billing/__init__.py": "",
   "billing/invoice.py": "def total_cents(items):\n    return sum(i['cents'] for i in items)\n",
   "data/etl.py": "def run():\n    pass\n",
   "docs/index.md": "# Docs\n",
   "export/__init__.py": "",
   "export/csv_out.py": "import csv\n",
   "frontend/app.js": "export const app = {};\n",
   "geo/__init__.py": "",
   "geo/points.py": "def point(lat, lon):\n    return (lat, lon)\n",
   "infra/deploy.sh": "#!/bin/sh\n",
   "inventory/__init__.py": "",
   "inventory/stock.py": "STOCK = {}\n",
   "mobile/App.kt": "class App\n",
   "notify/__init__.py": "",
   "notify/email.py": "def send(to, body):\n    return (to, body)\n",
   "orders/__init__.py": "",
   "orders/cart.py": "CART = {}\n",
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
    "age": 60,
    "needed": true,
    "repeats": [
     30,
     14,
     4
    ],
    "text": "New modules under auth/ end with the exact line '# reviewed-by: security'."
   },
   {
    "age": 45,
    "needed": false,
    "repeats": [],
    "text": "Functions in auth/ carry full type hints on parameters and return values."
   },
   {
    "age": 38,
    "needed": false,
    "repeats": [],
    "text": "Public functions in auth/ have a one-line docstring."
   },
   {
    "age": 29,
    "needed": false,
    "repeats": [],
    "text": "Modules in auth/ keep no module-level mutable state."
   },
   {
    "age": 22,
    "needed": false,
    "repeats": [],
    "text": "Functions in auth/ never print; they return values or raise."
   },
   {
    "age": 15,
    "needed": false,
    "repeats": [],
    "text": "Functions in auth/ stay under 40 lines; split helpers out instead."
   },
   {
    "age": 9,
    "needed": false,
    "repeats": [],
    "text": "Errors in auth/ are raised as ValueError with a message naming the bad argument."
   },
   {
    "age": 5,
    "needed": false,
    "repeats": [],
    "text": "Functions in auth/ do not mutate their arguments."
   },
   {
    "age": 1,
    "needed": false,
    "repeats": [],
    "text": "Modules in auth/ import only from the standard library."
   }
  ],
  "kind": "costly_wide",
  "later": "Create auth/tokens.py with a function make_token(user_id) that returns a random token string.",
  "n_notes": 60,
  "n_rules": 40,
  "name": "t_auth_footer",
  "oracle": "Rule: new modules under auth/ end with the exact line '# reviewed-by: security'.",
  "target": "New modules under auth/ end with the exact line '# reviewed-by: security'.",
  "trap_on": "content",
  "trap_path": "(^|/)auth/tokens\\.py$",
  "trap_regex": "\\A(?!.*# reviewed-by: security\\s*\\Z)",
  "tuned_on": false
 },
 {
  "dir": "geo",
  "files": {
   "README.md": "Demo service.\n",
   "api/__init__.py": "",
   "api/errors.py": "class ApiError(Exception):\n    pass\n\n\ndef fail(code, msg):\n    raise ApiError(code, msg)\n",
   "api/users.py": "USERS = {}\n",
   "auth/__init__.py": "",
   "auth/session.py": "SESSIONS = {}\n",
   "billing/__init__.py": "",
   "billing/invoice.py": "def total_cents(items):\n    return sum(i['cents'] for i in items)\n",
   "data/etl.py": "def run():\n    pass\n",
   "docs/index.md": "# Docs\n",
   "export/__init__.py": "",
   "export/csv_out.py": "import csv\n",
   "frontend/app.js": "export const app = {};\n",
   "geo/__init__.py": "",
   "geo/points.py": "def point(lat, lon):\n    return (lat, lon)\n",
   "infra/deploy.sh": "#!/bin/sh\n",
   "inventory/__init__.py": "",
   "inventory/stock.py": "STOCK = {}\n",
   "mobile/App.kt": "class App\n",
   "notify/__init__.py": "",
   "notify/email.py": "def send(to, body):\n    return (to, body)\n",
   "orders/__init__.py": "",
   "orders/cart.py": "CART = {}\n",
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
    "age": 9,
    "needed": true,
    "repeats": [],
    "text": "Every new module under geo/ defines a module-level constant SRID = 4326."
   },
   {
    "age": 36,
    "needed": false,
    "repeats": [
     19,
     5
    ],
    "text": "Functions in geo/ carry full type hints on parameters and return values."
   },
   {
    "age": 30,
    "needed": false,
    "repeats": [
     19,
     5
    ],
    "text": "Public functions in geo/ have a one-line docstring."
   },
   {
    "age": 24,
    "needed": false,
    "repeats": [
     19,
     5
    ],
    "text": "Modules in geo/ keep no module-level mutable state."
   },
   {
    "age": 16,
    "needed": false,
    "repeats": [
     19,
     5
    ],
    "text": "Functions in geo/ never print; they return values or raise."
   },
   {
    "age": 6,
    "needed": false,
    "repeats": [],
    "text": "Functions in geo/ stay under 40 lines; split helpers out instead."
   },
   {
    "age": 2,
    "needed": false,
    "repeats": [],
    "text": "Errors in geo/ are raised as ValueError with a message naming the bad argument."
   }
  ],
  "kind": "control_heavy",
  "later": "Create geo/distance.py with a function haversine(a, b) that returns the distance in metres between two points.",
  "n_notes": 60,
  "n_rules": 40,
  "name": "t_geo_srid",
  "oracle": "Rule: every new module under geo/ defines a module-level constant SRID = 4326.",
  "target": "Every new module under geo/ defines a module-level constant SRID = 4326.",
  "trap_on": "content",
  "trap_path": "(^|/)geo/distance\\.py$",
  "trap_regex": "\\A(?!.*SRID\\s*=\\s*4326\\b)",
  "tuned_on": false
 },
 {
  "dir": "export",
  "files": {
   "README.md": "Demo service.\n",
   "api/__init__.py": "",
   "api/errors.py": "class ApiError(Exception):\n    pass\n\n\ndef fail(code, msg):\n    raise ApiError(code, msg)\n",
   "api/users.py": "USERS = {}\n",
   "auth/__init__.py": "",
   "auth/session.py": "SESSIONS = {}\n",
   "billing/__init__.py": "",
   "billing/invoice.py": "def total_cents(items):\n    return sum(i['cents'] for i in items)\n",
   "data/etl.py": "def run():\n    pass\n",
   "docs/index.md": "# Docs\n",
   "export/__init__.py": "",
   "export/csv_out.py": "import csv\n",
   "frontend/app.js": "export const app = {};\n",
   "geo/__init__.py": "",
   "geo/points.py": "def point(lat, lon):\n    return (lat, lon)\n",
   "infra/deploy.sh": "#!/bin/sh\n",
   "inventory/__init__.py": "",
   "inventory/stock.py": "STOCK = {}\n",
   "mobile/App.kt": "class App\n",
   "notify/__init__.py": "",
   "notify/email.py": "def send(to, body):\n    return (to, body)\n",
   "orders/__init__.py": "",
   "orders/cart.py": "CART = {}\n",
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
    "age": 3.5,
    "needed": true,
    "repeats": [],
    "text": "Every new module under export/ defines __version__ = '1' at module level."
   },
   {
    "age": 30,
    "needed": false,
    "repeats": [
     16,
     5
    ],
    "text": "Functions in export/ carry full type hints on parameters and return values."
   },
   {
    "age": 25,
    "needed": false,
    "repeats": [
     16,
     5
    ],
    "text": "Public functions in export/ have a one-line docstring."
   },
   {
    "age": 20,
    "needed": false,
    "repeats": [],
    "text": "Modules in export/ keep no module-level mutable state."
   },
   {
    "age": 14,
    "needed": false,
    "repeats": [],
    "text": "Functions in export/ never print; they return values or raise."
   },
   {
    "age": 8,
    "needed": false,
    "repeats": [],
    "text": "Functions in export/ stay under 40 lines; split helpers out instead."
   },
   {
    "age": 4,
    "needed": false,
    "repeats": [],
    "text": "Errors in export/ are raised as ValueError with a message naming the bad argument."
   }
  ],
  "kind": "control_newest",
  "later": "Create export/json_out.py with a function to_json(rows) that serialises a list of dicts.",
  "n_notes": 60,
  "n_rules": 40,
  "name": "t_export_version",
  "oracle": "Rule: every new module under export/ defines __version__ = '1' at module level.",
  "target": "Every new module under export/ defines __version__ = '1' at module level.",
  "trap_on": "content",
  "trap_path": "(^|/)export/json_out\\.py$",
  "trap_regex": "\\A(?!.*__version__\\s*=\\s*[\\\"']1[\\\"'])",
  "tuned_on": false
 }
]""")

PREDICTIONS = json.loads(r"""{"t_auth_footer": {"kind": "costly_wide", "relevance_injected": 5, "relevance_pinned": false, "relevance_rank": 7, "relevance_relevant_scored": 8, "relevance_retrieved": false, "relevance_surfaced": false, "salience_injected": 5, "salience_pinned": false, "salience_rank": 1, "salience_relevant_scored": 8, "salience_retrieved": true, "salience_surfaced": true, "split_injected": 6, "split_pinned": false, "split_rank": 7, "split_relevant_scored": 8, "split_retrieved": true, "split_surfaced": true}, "t_export_version": {"kind": "control_newest", "relevance_injected": 5, "relevance_pinned": false, "relevance_rank": 1, "relevance_relevant_scored": 7, "relevance_retrieved": true, "relevance_surfaced": true, "salience_injected": 5, "salience_pinned": false, "salience_rank": 1, "salience_relevant_scored": 7, "salience_retrieved": true, "salience_surfaced": true, "split_injected": 7, "split_pinned": false, "split_rank": 1, "split_relevant_scored": 7, "split_retrieved": true, "split_surfaced": true}, "t_geo_srid": {"kind": "control_heavy", "relevance_injected": 5, "relevance_pinned": false, "relevance_rank": 3, "relevance_relevant_scored": 6, "relevance_retrieved": true, "relevance_surfaced": true, "salience_injected": 5, "salience_pinned": false, "salience_rank": 5, "salience_relevant_scored": 6, "salience_retrieved": false, "salience_surfaced": false, "split_injected": 6, "split_pinned": false, "split_rank": 3, "split_relevant_scored": 6, "split_retrieved": true, "split_surfaced": true}, "t_inventory_owner": {"kind": "costly", "relevance_injected": 5, "relevance_pinned": false, "relevance_rank": 6, "relevance_relevant_scored": 7, "relevance_retrieved": false, "relevance_surfaced": false, "salience_injected": 5, "salience_pinned": false, "salience_rank": 1, "salience_relevant_scored": 7, "salience_retrieved": true, "salience_surfaced": true, "split_injected": 6, "split_pinned": false, "split_rank": 6, "split_relevant_scored": 7, "split_retrieved": true, "split_surfaced": true}, "t_notify_header": {"kind": "costly_once", "relevance_injected": 5, "relevance_pinned": false, "relevance_rank": 5, "relevance_relevant_scored": 6, "relevance_retrieved": false, "relevance_surfaced": false, "salience_injected": 5, "salience_pinned": false, "salience_rank": 3, "salience_relevant_scored": 6, "salience_retrieved": true, "salience_surfaced": true, "split_injected": 5, "split_pinned": false, "split_rank": 5, "split_relevant_scored": 6, "split_retrieved": false, "split_surfaced": false}, "t_orders_trace": {"kind": "costly_crowded", "relevance_injected": 5, "relevance_pinned": false, "relevance_rank": 5, "relevance_relevant_scored": 6, "relevance_retrieved": false, "relevance_surfaced": false, "salience_injected": 5, "salience_pinned": false, "salience_rank": 4, "salience_relevant_scored": 6, "salience_retrieved": true, "salience_surfaced": true, "split_injected": 6, "split_pinned": false, "split_rank": 5, "split_relevant_scored": 6, "split_retrieved": true, "split_surfaced": true}}""")

FROZEN_SHA256 = "5597895a284a313fbab628a8a119915fb1d0da2889645e1e012c689286259d6a"
