"""pressure2 candidates: the pressure1 design at two scales (300 and 1200 memories), with distractors confined to
synthetic directories that never overlap a target, and traps that judge only the exact file the task asks for.
Question: does a CLAUDE.md holding every memory start dropping rules at scale, where per-prompt retrieval does not?"""
from bench.live.pressure import REPO

FILES = dict(REPO, **{"queue/__init__.py": "", "queue/worker.py": "def run(job):\n    return job()\n",
                      "ledger/__init__.py": "", "ledger/entries.py": "ENTRIES = []\n"})

BASE = [
    {"name": "billing_header", "target": ("correction", "Every new module under billing/ starts with the exact line '# PCI-SCOPE'.", ""),
     "later": "Create billing/refunds.py with a function refund(amount_cents, reason) that returns a refund record.",
     "trap_regex": r"\A(?!# PCI-SCOPE)", "trap_on": "content", "trap_path": r"(^|/)billing/refunds\.py$",
     "oracle": "Rule: every new module under billing/ starts with the exact line '# PCI-SCOPE'."},
    {"name": "tools_flags", "target": ("correction", "Command-line options in tools/ are spelled as one lowercase word without dashes inside, like --dryrun or --nocache.", ""),
     "later": "Add an option to tools/sync.py that makes it skip writing any files (a dry run).",
     "trap_regex": r"--dry[-_]run", "trap_on": "content", "trap_path": r"(^|/)tools/sync\.py$",
     "oracle": "Rule: command-line options in tools/ are one lowercase word without inner dashes, e.g. --dryrun."},
    {"name": "queue_version", "target": ("correction", "Every new module under queue/ defines a module-level constant SCHEMA_VERSION = 2.", ""),
     "later": "Create queue/retry_policy.py with a function backoff(attempt) that returns the delay in seconds for a retry.",
     "trap_regex": r"\A(?!.*SCHEMA_VERSION\s*=\s*2\b)", "trap_on": "content", "trap_path": r"(^|/)queue/retry_policy\.py$",
     "oracle": "Rule: every new module under queue/ defines a module-level constant SCHEMA_VERSION = 2."},
    {"name": "ledger_footer", "target": ("correction", "New modules under ledger/ end with the exact line '# end-of-ledger-module'.", ""),
     "later": "Create ledger/balance.py with a function balance(entries) that sums the amount of each entry.",
     "trap_regex": r"\A(?!.*# end-of-ledger-module\s*\Z)", "trap_on": "content", "trap_path": r"(^|/)ledger/balance\.py$",
     "oracle": "Rule: new modules under ledger/ end with the exact line '# end-of-ledger-module'."},
]
SIZES = {"s300": (240, 60), "s1200": (1000, 200)}          # (distractor rules, distractor notes)

CANDIDATES = [dict(b, name=f"{b['name']}_{tag}", n_rules=r, n_notes=n, files=dict(FILES))
              for b in BASE for tag, (r, n) in SIZES.items()]
