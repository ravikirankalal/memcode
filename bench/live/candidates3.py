"""Third pool: HARDER scenarios meant to separate memcode from a hand-written CLAUDE.md.
Several rules, rules taught in separate sessions, a rule that is superseded, and a rule stated as
information rather than as a correction. Some of these probe known memcode gaps on purpose
(supersession; capture of non-correction phrasing). `oracle` = the final rules stated outright; a
pilot with the oracle appended must score ~0 trap hits, proving the trap regex is satisfiable.
Trap regexes are compiled with re.S by metrics.py (no inline flags). Selected by a no-memory pilot (and an oracle check) before memcode/claudemd are ever run on them."""
from bench.live.run import BASE

HDR = r"\A(?!# Copyright Acme)"
MAIN = r"\A(?!.*__main__)"
FROM = r"(?:\A|\n)from \w[\w.]* import"
DEF2 = r"def [^\n]*:\n(?!  \S)"      # first body line must be indented by exactly 2 spaces
OSPATH = r"\bimport os\b|os\.path"

CANDIDATES3 = [
    {"name": "m_four_rules", "files": dict(BASE), "trap_on": "content",
     "trap_regex": "|".join([HDR, MAIN, FROM, OSPATH]),
     "s1": ["Create ops.py with a function mul(a, b).",
            "No - every new file in this repo must start with the exact line '# Copyright Acme'. Fix it and remember that.",
            "Also: every new module must end with an `if __name__ == '__main__':` demo block. Fix it and remember that.",
            "Also: never write 'from x import y' here; always 'import x' and call x.y. Fix it and remember that.",
            "Also: never use os.path or the os module for paths here; always pathlib. Fix it and remember that."],
     "later": "Create storage.py with a function dataFile(root, filename) that returns the full path of a file inside root, using the datetime module to stamp it with today's date in the name.",
     "oracle": "Rules: start every new file with the exact line '# Copyright Acme'; end every module with an `if __name__ == '__main__':` demo block; never use from-imports (use 'import x'); never use os or os.path (use pathlib via 'import pathlib')."},
    {"name": "m_three_across_sessions", "files": dict(BASE), "trap_on": "content",
     "trap_regex": r'"|return \{|dict\(|def [a-z]+_[a-z_]*\(',
     "teach": [["Create greet.py with a function greeting(name) that returns a hello message.",
                "No - use single quotes only in this repo, never double quotes. Rewrite it and remember that."],
               ["Create user.py with a function makeUser(name, email) that returns the user record.",
                "No - never use plain dicts for records in this repo; always a @dataclass. Rewrite it and remember that.",
                "Also: function names here must be camelCase, never snake_case. Rename and remember that."]],
     "later": "Create order.py with a function makeOrder(item, qty) that returns the order record, and a message for it.",
     "oracle": "Rules: single quotes only (never double quotes anywhere, including docstrings); records are @dataclass, never plain dicts; function names camelCase."},
    {"name": "m_supersede", "files": dict(BASE), "trap_on": "content",
     "trap_regex": r"def [^\n]*:\n(?!  \S)",
     "s1": ["Create ops.py with a function mul(a, b) that raises ValueError for non-numbers.",
            "No - this repo indents with tabs, never spaces. Rewrite it and remember that.",
            "Actually, change of plan: the team switched, so indent with exactly 2 spaces from now on, never tabs. Rewrite it and remember that."],
     "later": "Create geo.py with a function area(w, h) that raises ValueError if either side is negative.",
     "oracle": "Rule: indent with exactly 2 spaces (never tabs, never 4 spaces)."},
    {"name": "m_stated_as_info", "files": dict(BASE), "trap_on": "content", "trap_regex": r'"',
     "s1": ["Create greet.py with a function greeting(name) that returns a hello message.",
            "Heads up: this team prefers single quotes over double quotes everywhere, so keep to that."],
     "later": "Create farewell.py with a function farewell(name) that returns a goodbye message.",
     "oracle": "Rule: use single quotes only, never double quotes."},
    {"name": "m_rules_and_distractors", "files": dict(BASE), "trap_on": "content",
     "trap_regex": "|".join([HDR, DEF2, r"-> ?\w"]),
     "s1": ["Create ops.py with a function mul(a, b).",
            "No - every new file must start with the exact line '# Copyright Acme'. Fix it and remember that.",
            "Thanks. Now add a function sub(a, b) to ops.py.",
            "No - this repo indents with exactly 2 spaces, never 4. Rewrite ops.py and remember that.",
            "Now add div(a, b) to ops.py.",
            "No - no return type annotations anywhere in this repo. Remove them and remember that."],
     "later": "Create geo.py with a function area(w, h) that raises ValueError if either side is negative.",
     "oracle": "Rules: start every new file with the exact line '# Copyright Acme'; indent with exactly 2 spaces (never 4); no return type annotations."},
]
