"""Second candidate pool (for heldout2). Same method as candidates.py: rules that conflict with a
strong model default; selected by a NO-MEMORY pilot before memcode is ever run on them.
Later prompts never mention the rule. `\\A(?!...)` traps flag a written file that LACKS something."""
from bench.live.run import BASE

ERRORS = {"errors.py": "class AppError(Exception):\n\tpass\n"}

CANDIDATES2 = [
    {"name": "k_pathlib", "files": dict(BASE), "trap_regex": r"os\.path|import os\b", "trap_on": "content",
     "s1": ["Create paths.py with a function configFile(base_dir, name) that returns the full path of a file inside base_dir.",
            "No - never use os.path or the os module for paths in this repo; always pathlib. Rewrite it and remember that."],
     "later": "Create storage.py with a function dataFile(root, filename) that returns the full path of a file inside root."},
    {"name": "k_app_error", "files": dict(BASE, **ERRORS), "trap_regex": r"raise (ValueError|TypeError|Exception|RuntimeError)",
     "trap_on": "content",
     "s1": ["Create ops.py with a function divide(a, b) that fails clearly when b is zero.",
            "No - never raise built-in exceptions in this repo; always raise AppError from errors.py. Fix it and remember that."],
     "later": "Create geo.py with a function ratio(w, h) that fails clearly when h is zero."},
    {"name": "k_dataclass", "files": dict(BASE), "trap_regex": r"return \{|dict\(", "trap_on": "content",
     "s1": ["Create user.py with a function makeUser(name, email) that returns the user record.",
            "No - never use plain dicts for records in this repo; always a @dataclass. Rewrite it and remember that."],
     "later": "Create order.py with a function makeOrder(item, qty) that returns the order record."},
    {"name": "k_module_imports", "files": dict(BASE), "trap_regex": r"(?m)^from \w[\w.]* import", "trap_on": "content",
     "s1": ["Create stats.py with a function meanOf(values) using the statistics module.",
            "No - never use 'from x import y' in this repo; always 'import x' and call x.y. Rewrite it and remember that."],
     "later": "Create timeutil.py with a function today() that returns today's date as an ISO string using datetime."},
    {"name": "k_main_block", "files": dict(BASE), "trap_regex": r"(?s)\A(?!.*__main__)", "trap_on": "content",
     "s1": ["Create ops.py with a function mul(a, b).",
            "No - every new module here must end with an `if __name__ == '__main__':` block that runs a tiny demo. Add it and remember that."],
     "later": "Create geo.py with a function area(w, h)."},
    {"name": "k_header", "files": dict(BASE), "trap_regex": r"\A(?!# Copyright Acme)", "trap_on": "content",
     "s1": ["Create ops.py with a function mul(a, b).",
            "No - every new file in this repo must start with the exact line '# Copyright Acme'. Add it and remember that."],
     "later": "Create geo.py with a function area(w, h)."},
]
