"""Fourth pool, built to VALIDATE the capture changes made after heldout3: (a) rules stated as
information in varied phrasings, (b) rules given after text-only exchanges (question/answer turns in
which the agent uses no Bash/edit tool). Trap regexes are compiled with re.S by metrics.py.
Selected by a no-memory pilot and an oracle pilot before memcode/claudemd are run on them."""
from bench.live.run import BASE

HDR = r"\A(?!# Copyright Acme)"
MAIN = r"\A(?!.*__main__)"
DEFTAB = r"def [^\n]*:\n(?!\t)"          # first body line of a function must start with a tab
OSPATH = r"\bimport os\b|os\.path"
DQ = r'"'

CANDIDATES4 = [
    {"name": "n_info_tabs", "files": dict(BASE), "trap_on": "content", "trap_regex": DEFTAB,
     "s1": ["Create ops.py with a function mul(a, b) that raises ValueError for non-numbers.",
            "FYI, in this repo we indent with tabs rather than spaces."],
     "later": "Create geo.py with a function area(w, h) that raises ValueError if either side is negative.",
     "oracle": "Rule: indent with tabs (never spaces)."},
    {"name": "n_info_header", "files": dict(BASE), "trap_on": "content", "trap_regex": HDR,
     "s1": ["Create ops.py with a function mul(a, b).",
            "Just so you know, our standard is that every new file starts with the exact line '# Copyright Acme'."],
     "later": "Create geo.py with a function area(w, h).",
     "oracle": "Rule: every new file starts with the exact line '# Copyright Acme'."},
    {"name": "n_text_gap_main", "files": dict(BASE), "trap_on": "content", "trap_regex": MAIN,
     "s1": ["Create ops.py with a function mul(a, b).",
            "What does mul return if I pass it two strings? Just explain, do not change anything.",
            "Also: every new module must end with an `if __name__ == '__main__':` demo block. Remember that."],
     "later": "Create geo.py with a function area(w, h).",
     "oracle": "Rule: every new module ends with an `if __name__ == '__main__':` demo block."},
    {"name": "n_text_gap_two_rules", "files": dict(BASE), "trap_on": "content", "trap_regex": "|".join([DEFTAB, HDR]),
     "s1": ["Create ops.py with a function mul(a, b).",
            "Is mul safe to call with negative numbers? Just answer.",
            "From now on, indent with tabs, never spaces.",
            "Why did you choose those parameter names? Just answer.",
            "Always start every new file with the exact line '# Copyright Acme'."],
     "later": "Create geo.py with a function area(w, h) that raises ValueError if either side is negative.",
     "oracle": "Rules: indent with tabs (never spaces); start every new file with the exact line '# Copyright Acme'."},
    {"name": "n_mixed", "files": dict(BASE), "trap_on": "content", "trap_regex": "|".join([DQ, OSPATH, HDR]),
     "s1": ["Create paths.py with a function dataFile(root, filename) that returns the full path of a file inside root.",
            "Note that we only use single quotes in this codebase.",
            "Does that function touch the filesystem? Just answer.",
            "Never use os.path or the os module for paths here; always pathlib. Remember that.",
            "No - every new file must start with the exact line '# Copyright Acme'. Fix it and remember that."],
     "later": "Create storage.py with a function logFile(root, name) that returns the full path of a log file inside root, with a message string describing it.",
     "oracle": "Rules: single quotes only (never double quotes anywhere); never use os or os.path (use pathlib); every new file starts with the exact line '# Copyright Acme'."},
]
