"""Candidate held-out scenarios. Each rule conflicts with a strong model default, so a
memory-less agent should often violate it. Selected by a no-memory pilot (bench/live/pilot.py);
memcode was NOT run on these before selection. Later prompts never mention the rule."""
from bench.live.run import BASE

CANDIDATES = [
    {"name": "h_tabs", "files": dict(BASE), "trap_regex": r"(?m)^ +\S", "trap_on": "content",
     "s1": ["Create ops.py with a function mul(a, b) that raises ValueError for non-numbers.",
            "No - this repo indents with tabs, never spaces. Rewrite it with tabs and remember that."],
     "later": "Create geo.py with a function area(w, h) that raises ValueError if either side is negative."},
    {"name": "h_single_quotes", "files": dict(BASE), "trap_regex": r'"', "trap_on": "content",
     "s1": ["Create greet.py with a function greeting(name) that returns a hello message.",
            "No - use single quotes only in this repo, never double quotes. Rewrite it and remember that."],
     "later": "Create farewell.py with a function farewell(name) that returns a goodbye message."},
    {"name": "h_check_files", "files": dict(BASE), "trap_regex": r"/test_[^/]*\.py$",
     "s1": ["Add a test file for add().",
            "No - test files in this repo are named check_<name>.py, never test_*.py. Rename it and remember that."],
     "later": "Add a test file covering add() with negative numbers."},
    {"name": "h_no_docstrings", "files": dict(BASE), "trap_regex": r'"""|\'\'\'', "trap_on": "content",
     "s1": ["Create ops.py with a function mul(a, b).",
            "No - never write docstrings in this repo. Remove it and remember that."],
     "later": "Create geo.py with a function area(w, h)."},
    {"name": "h_no_type_hints", "files": dict(BASE), "trap_regex": r"->|\w: ?(int|float|str|bool|list|dict)\b",
     "trap_on": "content",
     "s1": ["Create ops.py with a function mul(a, b).",
            "No - no type hints anywhere in this repo, plain untyped signatures only. Fix it and remember that."],
     "later": "Create geo.py with a function area(w, h)."},
    {"name": "h_camel_case", "files": dict(BASE), "trap_regex": r"def [a-z]+_[a-z_]*\(", "trap_on": "content",
     "s1": ["Create pricing.py with a function that computes the total price from a list of prices.",
            "No - function names here must be camelCase, e.g. computeTotal, never snake_case. Rename it and remember that."],
     "later": "Create tax.py with a function that applies a tax rate to a price."},
]
