"""e2e1 CANDIDATE week (not frozen): a realistic multi-session benchmark on the `shelf` project (e2e1_project.py).

Week: three teaching sessions (Mon-Wed) with real tasks; the simulated user states seven arbitrary conventions
(C1-C4 code conventions, P1-P3 process conventions) while correcting the agent. Two repo-specific execution facts (E1, E2) are never stated by anyone: the agent
meets them by itself whenever it runs the checks or the CLI. Three measured later sessions (Thu, Fri, next Mon):
two feature tasks where every lesson applies, and one question where none applies (noise and overhead).

Each session starts from the canonical repo of that day (starter + merged code of earlier days, identical for every
arm) plus ONLY the arm's memory carried from the previous session. Measured later sessions all start from the memory
as it stood after Wednesday (they do not see each other's memory). Trap files are new files created in that session.
"""
from __future__ import annotations

SPDX_LINE = "# SPDX-License-Identifier: MIT"

CONVENTIONS = {
    "C1": {"rule": f"Every new Python file starts with the line '{SPDX_LINE}'.",
           "stated": "day 1, as a correction ('No - ... remember that')"},
    "C2": {"rule": "Errors that reach the user are ShelfError (shelf/errors.py), never ValueError or another built-in exception.",
           "stated": "day 2, descriptively ('By the way, errors ... are ShelfError ..., not ValueError')"},
    "C3": {"rule": "Every user-visible change adds a bullet to CHANGES.md under '## Unreleased'.",
           "stated": "day 2, as a request ('please always add a bullet ...')"},
    "C4": {"rule": "New code never calls datetime.now()/date.today()/time.time() directly; it uses shelf.clock.now()/clock.today().",
           "stated": "day 1, as a correction ('Don't call datetime.now() ...')"},
    "P1": {"rule": "Before saying the work is done, run `make lint` (ruff) as well as the checks.",
           "stated": "day 1, as a request ('before you tell me you're done, always run `make lint` too')"},
    "P2": {"rule": "Every user-visible change bumps the patch version in both pyproject.toml and shelf/__init__.py.",
           "stated": "day 2, as a team habit ('we always bump the patch version ...')"},
    "P3": {"rule": "When the checks pass, commit the work with a message that starts with 'shelf: '.",
           "stated": "day 3, as a standing instruction ('from now on, commit ... starts with shelf: ')"},
}
# C1-C4 are visible in the merged code of earlier days (a capable model can copy them from sibling files);
# P1-P3 are process conventions no file shows. E1/E2 are discoverable by exploring (Makefile, tox.ini, __main__.py).
VISIBLE_IN_CODE = ("C1", "C2", "C3", "C4")
FACTS = {
    "E1": {"fact": "The checks run with `make check` (python3 -m unittest discover -s checks -p 'check_*.py' -t .). "
                   "tox is not installed, and plain pytest/unittest collect nothing because the checks are named check_*.py.",
           "stated": "never (README says 'run the checks with tox')"},
    "E2": {"fact": "The `shelf` command is not installed; run the CLI as `python3 -m shelf ...`.",
           "stated": "never (README shows `shelf ...`)"},
}

TEACH = [
    {"day": 1, "turns": [
        {"text": "Add a CSV importer: `shelf import-csv FILE` reads rows with the columns title,author,year,tags (tags "
                 "separated by ';') and adds them to the library, skipping books that are already on the shelf and "
                 "stamping each new book's added_at with today's date. Put the logic in a new module shelf/importers.py "
                 "with a function import_csv(path, books) that returns the new Book objects; a row without a title must "
                 "be rejected with an error. Wire it into cli.py, add checks in checks/check_importers.py, make sure all "
                 "the checks pass, and show me the output of importing data/more_books.csv (its last row has no title)."},
        {"text": f"No - every new Python file in this repo must start with the line `{SPDX_LINE}`. Add it to the "
                 "files you created and remember that.", "rule": "C1"},
        {"text": "Don't call datetime.now() or date.today() directly in new code; we always go through shelf.clock "
                 "(clock.now() / clock.today()) so the checks can freeze time. Please fix importers.py.", "rule": "C4"},
        {"text": "Also, before you tell me you're done, always run `make lint` too - CI fails on lint errors. Run it "
                 "now and fix whatever it reports.", "rule": "P1"},
    ]},
    {"day": 2, "turns": [
        {"text": "Add `shelf stats`: print how many books there are per tag and per decade (from the year; books "
                 "without a year count as 'unknown'). Put the counting in a new module shelf/stats.py with functions "
                 "tag_counts(books) and decade_counts(books); an empty library must make stats fail with an error "
                 "instead of printing empty tables. Wire it into cli.py, add checks in checks/check_stats.py, make sure "
                 "all the checks pass, and show me the output on the sample data."},
        {"text": "By the way, errors that reach the user in this codebase are ShelfError from shelf/errors.py, not "
                 "ValueError or other built-in exceptions. Please switch stats over.", "rule": "C2"},
        {"text": "And please always add a bullet to CHANGES.md under '## Unreleased' for user-visible changes like "
                 "this one. Add one for import-csv and one for stats.", "rule": "C3"},
        {"text": "One more thing: we always bump the patch version for user-visible changes, in both pyproject.toml "
                 "and shelf/__init__.py. Do that for this change.", "rule": "P2"},
    ]},
    {"day": 3, "turns": [
        {"text": "`shelf search tolkien` does not find The Hobbit because matching is case-sensitive. Make title, "
                 "author and tag matching ignore case, add a check for it, and make sure all the checks pass."},
        {"text": "Looks good. Commit it - and from now on, commit your work when the checks pass, with a message "
                 "that starts with 'shelf: '.", "rule": "P3"},
        {"text": "Quick question, no changes: why does search live in its own module instead of in cli.py?"},
    ]},
]

LATER = [
    {"name": "thu_recent", "day": 4, "applies": ["C1", "C2", "C3", "C4", "P1", "P2", "P3", "E1", "E2"],
     "prompt": "Add `shelf recent`: list the books added in the last N days (`--days N`, default 7), newest first. Put "
               "the logic in a new module shelf/recent.py with a function recent_books(books, days); a negative N "
               "must be rejected with an error. Wire it into cli.py, add checks in checks/check_recent.py, make sure "
               "all the checks pass, and show me the output of running it on the sample data.",
     "new_py": ["shelf/recent.py", "checks/check_recent.py"], "module": "shelf/recent.py",
     "also_judge": ["shelf/cli.py"]},
    {"name": "fri_markdown", "day": 5, "applies": ["C1", "C2", "C3", "C4", "P1", "P2", "P3", "E1", "E2"],
     "prompt": "Add a Markdown exporter so that `shelf export --format md --out FILE` writes the books as a Markdown "
               "table whose first line is 'Exported on YYYY-MM-DD' (today's date). Put it in a new module "
               "shelf/exporters/markdown_export.py with a function export_markdown(books, out_path, fields); an "
               "unknown field name must be rejected with an error. Register it so `--format md` works, add checks in "
               "checks/check_markdown_export.py, make sure all the checks pass, and show me the output of exporting "
               "the sample data to exports/books.md.",
     "new_py": ["shelf/exporters/markdown_export.py", "checks/check_markdown_export.py"],
     "module": "shelf/exporters/markdown_export.py", "also_judge": ["shelf/cli.py", "shelf/exporters/__init__.py"]},
    {"name": "mon_question", "day": 6, "applies": [],
     "prompt": "Quick question, no code changes: how does shelf decide which data file to use, and how would I point "
               "it at a different one?",
     "new_py": [], "module": None, "also_judge": []},
]

# Judging (final repo state of the later session, exact files; plus the transcript for E1/E2).
JUDGE = {
    "C1": {"first_line": SPDX_LINE},                       # every existing file in new_py must start with it
    "C2": {"regex": r"raise\s+(?:ValueError|TypeError|KeyError|RuntimeError|LookupError|IndexError|Exception|"
                    r"AssertionError|argparse\.ArgumentTypeError)\b",
           "comply": r"raise\s+(?:errors\.)?ShelfError\b"},  # module text + lines added to also_judge files
    "C3": {"section": "## Unreleased"},                    # mistake: no new bullet under it in CHANGES.md
    "C4": {"regex": r"\b(?:datetime\.(?:now|today|utcnow)|date\.today|time\.time)\s*\("},   # module text
    "P1": {"lint_cmd": r"^(?:make\s+lint|ruff(?:\s+check)?|python3?\s+-m\s+(?:ruff|pyflakes|flake8)|flake8|pyflakes)\b"},
    "P2": {"files": {"pyproject.toml": r'(?m)^version = "([0-9.]+)"', "shelf/__init__.py": r'__version__ = "([0-9.]+)"'}},
    "P3": {"prefix": "shelf: "},                           # every new commit's subject; no new commit = mistake
    # E1/E2 classify each simple command (split on ; && || |, leading `cd x` and VAR=val dropped).
    "E1": {"test_cmd": r"^(?:tox|pytest|py\.test|python3?\s+-m\s+(?:pytest|unittest)|make\s+(?:check|test))\b",
           "wrong": r"^(?:tox|make\s+test)\b",
           "no_tests": r"Ran 0 tests|NO TESTS RAN|no tests ran|collected 0 items|command not found|No rule to make target"},
    "E2": {"wrong": r"^shelf(?:\s|$)"},
}

ORACLE = ("Project rules and facts you must follow: "
          + " ".join(c["rule"] for c in CONVENTIONS.values()) + " "
          + " ".join(f["fact"] for f in FACTS.values()))

# Lines of injected memory text that concern each lesson (used to label memory as relevant or irrelevant).
KEYS = {"P1": r"make lint|\bruff\b|\blint", "P2": r"version|pyproject", "P3": r"commit|shelf: ",
        "C1": r"SPDX", "C2": r"ShelfError", "C3": r"CHANGES", "C4": r"clock|datetime|date\.today",
        "E1": r"make check|check_\*|unittest discover|\btox\b", "E2": r"-m shelf|`shelf`|shelf: not found|\bshelf\b.*(?:not installed|127)"}
