"""The e2e1 starter project ("shelf", a small book-catalogue CLI) and the canonical merged code of each day.

Starter conventions on purpose: NO file has the SPDX header, legacy code (storage.py, csv_export.py) still calls
datetime directly and raises ValueError, and the README says "run the checks with tox" although tox is not
installed in the benchmark machine and the checks are named check_*.py (so plain pytest/unittest find nothing).
`shelf` is not installed as a command (only `python3 -m shelf` works).

CANON[day] = files the merged pull request of that day added or changed, written to comply with every convention
taught so far (as a reviewer would have required). Every session starts from STARTER + CANON of the earlier days, so
all arms see the same code and earlier sessions' code is present, as it would be for a real developer.
"""
from __future__ import annotations

SPDX = "# SPDX-License-Identifier: MIT\n"

STARTER = {
    "README.md": """# shelf

Catalogue your books from the command line.

    shelf add "The Hobbit" --author "J. R. R. Tolkien" --year 1937 --tag fantasy
    shelf list --sort year
    shelf search tolkien
    shelf export --format csv --out books.csv --fields title,author

Settings live in `shelf.toml` (which data file to use, default sort order).

## Development

Run the checks with `tox`.
""",
    "CHANGES.md": """# Changes

## Unreleased

## 0.3.0
- `shelf export --format csv`, with `--fields`.
- Books can carry tags (`--tag`, repeatable).

## 0.2.0
- `shelf search`.
""",
    "pyproject.toml": """[project]
name = "shelf"
version = "0.3.0"
description = "Catalogue a personal book collection from the command line"
requires-python = ">=3.11"

[project.scripts]
shelf = "shelf.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.ruff]
line-length = 120

[tool.ruff.lint]
select = ["E4", "E7", "E9", "F"]
""",
    "tox.ini": """[tox]
envlist = py311, py312, py313
skipsdist = true

[testenv]
commands = python -m unittest discover -s checks -p "check_*.py" -t .
""",
    "Makefile": """PY ?= python3

.PHONY: check lint demo

check:
\t$(PY) -m unittest discover -s checks -p "check_*.py" -t .

lint:
\truff check shelf checks

demo:
\t$(PY) -m shelf list --sort year
""",
    "shelf.toml": """[shelf]
data_file = "data/books.json"
default_sort = "title"
""",
    "data/books.json": """[
  {"title": "The Hobbit", "author": "J. R. R. Tolkien", "year": 1937, "tags": ["fantasy"], "added_at": "2026-09-02"},
  {"title": "Dune", "author": "Frank Herbert", "year": 1965, "tags": ["sf"], "added_at": "2026-09-20"},
  {"title": "The Left Hand of Darkness", "author": "Ursula K. Le Guin", "year": 1969, "tags": ["sf"], "added_at": "2026-10-01"},
  {"title": "Middlemarch", "author": "George Eliot", "year": 1871, "tags": ["classic"], "added_at": "2026-10-09"},
  {"title": "Piranesi", "author": "Susanna Clarke", "year": 2020, "tags": ["fantasy"], "added_at": "2026-10-13"},
  {"title": "Field Notes", "author": "Anonymous", "year": null, "tags": [], "added_at": "2026-10-15"}
]
""",
    "data/more_books.csv": """title,author,year,tags
Kindred,Octavia E. Butler,1979,sf;classic
Dune,Frank Herbert,1965,sf
The Name of the Rose,Umberto Eco,1980,mystery;classic
,Nobody,2001,
""",
    "shelf/__init__.py": '"""shelf: catalogue a personal book collection."""\n\n__version__ = "0.3.0"\n',
    "shelf/__main__.py": "from shelf.cli import main\n\nraise SystemExit(main())\n",
    "shelf/errors.py": '''class ShelfError(Exception):
    """An error reported to the user by the CLI (exit status 2)."""
''',
    "shelf/clock.py": '''"""The time source. Checks replace `_now` to freeze time."""
import datetime as _dt

_now = _dt.datetime.now


def now() -> _dt.datetime:
    return _now()


def today() -> _dt.date:
    return _now().date()
''',
    "shelf/models.py": '''"""Book records."""
from dataclasses import asdict, dataclass, field


@dataclass
class Book:
    title: str
    author: str
    year: int | None = None
    tags: list[str] = field(default_factory=list)
    added_at: str = ""          # ISO date the book was catalogued

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Book":
        return cls(title=d["title"], author=d["author"], year=d.get("year"),
                   tags=list(d.get("tags") or []), added_at=d.get("added_at") or "")
''',
    "shelf/config.py": '''"""Settings from shelf.toml in the current directory or the nearest parent."""
import tomllib
from pathlib import Path

DEFAULTS = {"data_file": "data/books.json", "default_sort": "title"}


def find_root(start: Path | None = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / "shelf.toml").is_file():
            return d
    return here


def load(start: Path | None = None) -> dict:
    root = find_root(start)
    cfg = dict(DEFAULTS)
    f = root / "shelf.toml"
    if f.is_file():
        cfg.update(tomllib.loads(f.read_text()).get("shelf", {}))
    cfg["root"] = root
    cfg["data_path"] = root / cfg["data_file"]
    return cfg
''',
    "shelf/storage.py": '''"""Load and save the book list (a JSON file)."""
import datetime
import json
from pathlib import Path

from shelf.errors import ShelfError
from shelf.models import Book


def load(path: Path) -> list[Book]:
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from e
    return [Book.from_dict(r) for r in rows]


def save(path: Path, books: list[Book]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([b.to_dict() for b in books], indent=2) + "\\n")


def add(path: Path, book: Book) -> Book:
    books = load(path)
    if any(b.title == book.title and b.author == book.author for b in books):
        raise ShelfError(f"already on the shelf: {book.title}")
    if not book.added_at:
        book.added_at = datetime.date.today().isoformat()
    books.append(book)
    save(path, books)
    return book
''',
    "shelf/search.py": '''"""Find books by a query string."""
from shelf.models import Book


def matches(book: Book, query: str) -> bool:
    return query in book.title or query in book.author or query in book.tags


def search(books: list[Book], query: str) -> list[Book]:
    return [b for b in books if matches(b, query)]
''',
    "shelf/formatting.py": '''"""Plain-text output for the CLI."""
from shelf.models import Book


def table(books: list[Book]) -> str:
    if not books:
        return "(no books)"
    rows = [(b.title, b.author, str(b.year or ""), ", ".join(b.tags)) for b in books]
    head = ("TITLE", "AUTHOR", "YEAR", "TAGS")
    widths = [max(len(r[i]) for r in rows + [head]) for i in range(4)]
    line = lambda r: "  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip()  # noqa: E731
    return "\\n".join([line(head)] + [line(r) for r in rows])


def sort_books(books: list[Book], key: str) -> list[Book]:
    if key == "year":
        return sorted(books, key=lambda b: (b.year is None, b.year or 0))
    return sorted(books, key=lambda b: getattr(b, key, b.title))
''',
    "shelf/exporters/__init__.py": '''"""Export formats: name -> function(books, out_path, fields)."""
from shelf.exporters.csv_export import export_csv

EXPORTERS = {"csv": export_csv}
FIELDS = ("title", "author", "year", "tags", "added_at")
''',
    "shelf/exporters/csv_export.py": '''import csv
from pathlib import Path

from shelf.models import Book


def export_csv(books: list[Book], out_path: Path, fields=("title", "author", "year", "tags")) -> int:
    from shelf.exporters import FIELDS
    for f in fields:
        if f not in FIELDS:
            raise ValueError(f"unknown field: {f}")
    with open(out_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(fields)
        for b in books:
            row = b.to_dict()
            w.writerow([";".join(row[f]) if f == "tags" else row[f] for f in fields])
    return len(books)
''',
    "shelf/cli.py": '''"""Command line: shelf add | list | search | export."""
import argparse
import sys
from pathlib import Path

from shelf import config, formatting, search, storage
from shelf.errors import ShelfError
from shelf.exporters import EXPORTERS
from shelf.models import Book


def cmd_add(args, cfg):
    book = storage.add(cfg["data_path"], Book(args.title, args.author, args.year, args.tag or []))
    print(f"added: {book.title}")


def cmd_list(args, cfg):
    books = storage.load(cfg["data_path"])
    print(formatting.table(formatting.sort_books(books, args.sort or cfg["default_sort"])))


def cmd_search(args, cfg):
    print(formatting.table(search.search(storage.load(cfg["data_path"]), args.query)))


def cmd_export(args, cfg):
    if args.format not in EXPORTERS:
        raise ShelfError(f"unknown format: {args.format} (have: {', '.join(sorted(EXPORTERS))})")
    n = EXPORTERS[args.format](storage.load(cfg["data_path"]), Path(args.out), tuple(args.fields.split(",")))
    print(f"exported {n} books to {args.out}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="shelf")
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("add")
    a.add_argument("title")
    a.add_argument("--author", required=True)
    a.add_argument("--year", type=int)
    a.add_argument("--tag", action="append")
    a.set_defaults(func=cmd_add)
    ls = sub.add_parser("list")
    ls.add_argument("--sort", choices=("title", "author", "year"))
    ls.set_defaults(func=cmd_list)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.set_defaults(func=cmd_search)
    e = sub.add_parser("export")
    e.add_argument("--format", default="csv")
    e.add_argument("--out", required=True)
    e.add_argument("--fields", default="title,author,year,tags")
    e.set_defaults(func=cmd_export)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args, config.load())
    except (ShelfError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0
''',
    "checks/__init__.py": "",
    "checks/helpers.py": '''from shelf.models import Book


def sample_books() -> list[Book]:
    return [Book("The Hobbit", "J. R. R. Tolkien", 1937, ["fantasy"], "2026-09-02"),
            Book("Dune", "Frank Herbert", 1965, ["sf"], "2026-09-20"),
            Book("Field Notes", "Anonymous", None, [], "2026-10-15")]
''',
    "checks/check_models.py": '''import unittest

from shelf.models import Book


class BookChecks(unittest.TestCase):
    def test_round_trip(self):
        b = Book("Dune", "Frank Herbert", 1965, ["sf"], "2026-09-20")
        self.assertEqual(Book.from_dict(b.to_dict()), b)

    def test_missing_optional_fields(self):
        self.assertEqual(Book.from_dict({"title": "X", "author": "Y"}).tags, [])
''',
    "checks/check_storage.py": '''import tempfile
import unittest
from pathlib import Path

from shelf import storage
from shelf.errors import ShelfError
from shelf.models import Book


class StorageChecks(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "books.json"

    def test_add_and_load(self):
        storage.add(self.path, Book("Dune", "Frank Herbert", 1965))
        self.assertEqual([b.title for b in storage.load(self.path)], ["Dune"])
        self.assertTrue(storage.load(self.path)[0].added_at)

    def test_duplicate_rejected(self):
        storage.add(self.path, Book("Dune", "Frank Herbert"))
        with self.assertRaises(ShelfError):
            storage.add(self.path, Book("Dune", "Frank Herbert"))
''',
    "checks/check_search.py": '''import unittest

from checks.helpers import sample_books
from shelf.search import search


class SearchChecks(unittest.TestCase):
    def test_by_author(self):
        self.assertEqual([b.title for b in search(sample_books(), "Herbert")], ["Dune"])

    def test_by_tag(self):
        self.assertEqual([b.title for b in search(sample_books(), "fantasy")], ["The Hobbit"])
''',
    "checks/check_cli.py": '''import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from shelf import cli


class CliChecks(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "shelf.toml").write_text('[shelf]\\ndata_file = "books.json"\\n')
        self.old = os.getcwd()
        os.chdir(self.dir)

    def tearDown(self):
        os.chdir(self.old)

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_add_then_list(self):
        self.assertEqual(self.run_cli("add", "Dune", "--author", "Frank Herbert")[0], 0)
        self.assertIn("Dune", self.run_cli("list")[1])

    def test_unknown_export_format(self):
        code, out = self.run_cli("export", "--format", "xml", "--out", "x.xml")
        self.assertEqual(code, 2)
        self.assertIn("unknown format", out)
''',
}

# ---- canonical merged code per day (complies with every convention taught so far) ----

CLI_IMPORT = (
    "from shelf import config, formatting, search, storage",
    "from shelf import config, formatting, importers, search, storage",
)

S1_IMPORTERS = SPDX + '''"""Import books from a CSV file (columns: title,author,year,tags; tags separated by ';')."""
import csv
from pathlib import Path

from shelf import clock
from shelf.errors import ShelfError
from shelf.models import Book


def import_csv(path: Path, books: list[Book]) -> list[Book]:
    """Return the new Book objects from `path` that are not already in `books`."""
    have = {(b.title, b.author) for b in books}
    new = []
    with open(path, newline="") as fh:
        for n, row in enumerate(csv.DictReader(fh), start=2):
            title = (row.get("title") or "").strip()
            if not title:
                raise ShelfError(f"{path}:{n}: row has no title")
            author = (row.get("author") or "").strip()
            if (title, author) in have:
                continue
            year = int(row["year"]) if (row.get("year") or "").strip() else None
            tags = [t for t in (row.get("tags") or "").split(";") if t]
            new.append(Book(title, author, year, tags, clock.today().isoformat()))
            have.add((title, author))
    return new
'''

S1_CHECK = SPDX + '''import datetime
import tempfile
import unittest
from pathlib import Path

from checks.helpers import sample_books
from shelf import clock
from shelf.errors import ShelfError
from shelf.importers import import_csv


class ImporterChecks(unittest.TestCase):
    def setUp(self):
        self.old = clock._now
        clock._now = lambda: datetime.datetime(2026, 10, 12, 9, 0)
        self.csv = Path(tempfile.mkdtemp()) / "in.csv"

    def tearDown(self):
        clock._now = self.old

    def test_new_rows_are_stamped_and_duplicates_skipped(self):
        self.csv.write_text("title,author,year,tags\\nKindred,Octavia E. Butler,1979,sf;classic\\nDune,Frank Herbert,1965,sf\\n")
        new = import_csv(self.csv, sample_books())
        self.assertEqual([b.title for b in new], ["Kindred"])
        self.assertEqual(new[0].tags, ["sf", "classic"])
        self.assertEqual(new[0].added_at, "2026-10-12")

    def test_row_without_title_is_an_error(self):
        self.csv.write_text("title,author,year,tags\\n,Nobody,2001,\\n")
        with self.assertRaises(ShelfError):
            import_csv(self.csv, [])
'''


def _cli(src: str, *edits: tuple[str, str]) -> str:
    for old, new in edits:
        assert old in src, old
        src = src.replace(old, new, 1)
    return src


_CLI0 = STARTER["shelf/cli.py"]
S1_CLI = _cli(
    _CLI0, CLI_IMPORT,
    ('def build_parser()', '''def cmd_import_csv(args, cfg):
    books = storage.load(cfg["data_path"])
    new = importers.import_csv(Path(args.file), books)
    storage.save(cfg["data_path"], books + new)
    print(f"imported {len(new)} books from {args.file}")


def build_parser()'''),
    ('    return p\n', '''    i = sub.add_parser("import-csv")
    i.add_argument("file")
    i.set_defaults(func=cmd_import_csv)
    return p
'''),
    ('"""Command line: shelf add | list | search | export."""', '"""Command line: shelf add | list | search | export | import-csv."""'),
)

S2_STATS = SPDX + '''"""Counts per tag and per decade for `shelf stats`."""
from collections import Counter

from shelf.errors import ShelfError
from shelf.models import Book


def _require_books(books: list[Book]) -> None:
    if not books:
        raise ShelfError("the library is empty: add books first")


def tag_counts(books: list[Book]) -> dict[str, int]:
    _require_books(books)
    return dict(Counter(t for b in books for t in b.tags).most_common())


def decade_counts(books: list[Book]) -> dict[str, int]:
    _require_books(books)
    c = Counter(f"{b.year // 10 * 10}s" if b.year else "unknown" for b in books)
    return dict(sorted(c.items()))
'''

S2_CHECK = SPDX + '''import unittest

from checks.helpers import sample_books
from shelf.errors import ShelfError
from shelf.stats import decade_counts, tag_counts


class StatsChecks(unittest.TestCase):
    def test_tags(self):
        self.assertEqual(tag_counts(sample_books()), {"fantasy": 1, "sf": 1})

    def test_decades(self):
        self.assertEqual(decade_counts(sample_books()), {"1930s": 1, "1960s": 1, "unknown": 1})

    def test_empty_library_is_an_error(self):
        with self.assertRaises(ShelfError):
            tag_counts([])
'''

S2_CLI = _cli(
    S1_CLI,
    ("from shelf import config, formatting, importers, search, storage",
     "from shelf import config, formatting, importers, search, stats, storage"),
    ('def build_parser()', '''def cmd_stats(args, cfg):
    books = storage.load(cfg["data_path"])
    tags, decades = stats.tag_counts(books), stats.decade_counts(books)
    print("BY TAG")
    for k, v in tags.items():
        print(f"  {k}: {v}")
    print("BY DECADE")
    for k, v in decades.items():
        print(f"  {k}: {v}")


def build_parser()'''),
    ('    return p\n', '''    st = sub.add_parser("stats")
    st.set_defaults(func=cmd_stats)
    return p
'''),
    ("| import-csv.", "| import-csv | stats."),
)


def _changes(*bullets: str) -> str:
    base = STARTER["CHANGES.md"]
    return base.replace("## Unreleased\n", "## Unreleased\n" + "".join(f"- {b}\n" for b in bullets), 1)


B1 = "`shelf import-csv FILE` adds books from a CSV file, skipping ones already on the shelf."
B2 = "`shelf stats` shows how many books there are per tag and per decade."
B3 = "`shelf search` ignores case."
B4 = "`shelf recent --days N` lists books added in the last N days."
B5 = "`shelf export --format md` writes a Markdown table."

S3_SEARCH = '''"""Find books by a query string (case-insensitive)."""
from shelf.models import Book


def matches(book: Book, query: str) -> bool:
    q = query.casefold()
    return (q in book.title.casefold() or q in book.author.casefold()
            or any(q == t.casefold() for t in book.tags))


def search(books: list[Book], query: str) -> list[Book]:
    return [b for b in books if matches(b, query)]
'''

S3_CHECK = STARTER["checks/check_search.py"] + '''
    def test_ignores_case(self):
        self.assertEqual([b.title for b in search(sample_books(), "tolkien")], ["The Hobbit"])
        self.assertEqual([b.title for b in search(sample_books(), "SF")], ["Dune"])
'''

S4_RECENT = SPDX + '''"""Books added in the last N days, for `shelf recent`."""
import datetime

from shelf import clock
from shelf.errors import ShelfError
from shelf.models import Book


def recent_books(books: list[Book], days: int = 7) -> list[Book]:
    """Books whose added_at lies within the last `days` days, newest first."""
    if days < 0:
        raise ShelfError(f"--days must be 0 or more, got {days}")
    since = clock.today() - datetime.timedelta(days=days)
    hits = [b for b in books if b.added_at and datetime.date.fromisoformat(b.added_at) >= since]
    return sorted(hits, key=lambda b: b.added_at, reverse=True)
'''

S4_CHECK = SPDX + '''import datetime
import unittest

from checks.helpers import sample_books
from shelf import clock
from shelf.errors import ShelfError
from shelf.recent import recent_books


class RecentChecks(unittest.TestCase):
    def setUp(self):
        self.old = clock._now
        clock._now = lambda: datetime.datetime(2026, 10, 16, 12, 0)

    def tearDown(self):
        clock._now = self.old

    def test_last_week_newest_first(self):
        self.assertEqual([b.title for b in recent_books(sample_books(), 7)], ["Field Notes"])
        self.assertEqual([b.title for b in recent_books(sample_books(), 30)], ["Field Notes", "Dune"])

    def test_negative_days_is_an_error(self):
        with self.assertRaises(ShelfError):
            recent_books(sample_books(), -1)
'''

S4_CLI = _cli(
    S2_CLI,
    ("from shelf import config, formatting, importers, search, stats, storage",
     "from shelf import config, formatting, importers, recent, search, stats, storage"),
    ('def build_parser()', '''def cmd_recent(args, cfg):
    print(formatting.table(recent.recent_books(storage.load(cfg["data_path"]), args.days)))


def build_parser()'''),
    ('    return p\n', '''    r = sub.add_parser("recent")
    r.add_argument("--days", type=int, default=7)
    r.set_defaults(func=cmd_recent)
    return p
'''),
    ("| stats.", "| stats | recent."),
)

S5_MD = SPDX + '''"""Markdown table export for `shelf export --format md`."""
from pathlib import Path

from shelf import clock
from shelf.errors import ShelfError
from shelf.models import Book


def export_markdown(books: list[Book], out_path: Path, fields=("title", "author", "year", "tags")) -> int:
    from shelf.exporters import FIELDS
    for f in fields:
        if f not in FIELDS:
            raise ShelfError(f"unknown field: {f}")
    lines = [f"Exported on {clock.today().isoformat()}", "",
             "| " + " | ".join(fields) + " |", "|" + "---|" * len(fields)]
    for b in books:
        row = b.to_dict()
        cells = [", ".join(row[f]) if f == "tags" else ("" if row[f] is None else str(row[f])) for f in fields]
        lines.append("| " + " | ".join(c.replace("|", "\\\\|") for c in cells) + " |")
    Path(out_path).write_text("\\n".join(lines) + "\\n")
    return len(books)
'''

S5_CHECK = SPDX + '''import datetime
import tempfile
import unittest
from pathlib import Path

from checks.helpers import sample_books
from shelf import clock
from shelf.errors import ShelfError
from shelf.exporters.markdown_export import export_markdown


class MarkdownExportChecks(unittest.TestCase):
    def setUp(self):
        self.old = clock._now
        clock._now = lambda: datetime.datetime(2026, 10, 16, 12, 0)
        self.out = Path(tempfile.mkdtemp()) / "books.md"

    def tearDown(self):
        clock._now = self.old

    def test_table(self):
        self.assertEqual(export_markdown(sample_books(), self.out, ("title", "year")), 3)
        lines = self.out.read_text().splitlines()
        self.assertEqual(lines[0], "Exported on 2026-10-16")
        self.assertEqual(lines[2], "| title | year |")
        self.assertIn("| Dune | 1965 |", lines)

    def test_unknown_field_is_an_error(self):
        with self.assertRaises(ShelfError):
            export_markdown(sample_books(), self.out, ("isbn",))
'''

S5_EXPORTERS = '''"""Export formats: name -> function(books, out_path, fields)."""
from shelf.exporters.csv_export import export_csv
from shelf.exporters.markdown_export import export_markdown

EXPORTERS = {"csv": export_csv, "md": export_markdown}
FIELDS = ("title", "author", "year", "tags", "added_at")
'''

def _version(v: str) -> dict[str, str]:
    """A patch-version bump, in both places (convention P2, taught on day 2)."""
    return {"pyproject.toml": STARTER["pyproject.toml"].replace('version = "0.3.0"', f'version = "{v}"', 1),
            "shelf/__init__.py": STARTER["shelf/__init__.py"].replace('"0.3.0"', f'"{v}"', 1)}


CANON = {
    1: {"shelf/importers.py": S1_IMPORTERS, "checks/check_importers.py": S1_CHECK, "shelf/cli.py": S1_CLI},
    2: {"shelf/stats.py": S2_STATS, "checks/check_stats.py": S2_CHECK, "shelf/cli.py": S2_CLI,
        "CHANGES.md": _changes(B1, B2), **_version("0.3.1")},
    3: {"shelf/search.py": S3_SEARCH, "checks/check_search.py": S3_CHECK, "CHANGES.md": _changes(B1, B2, B3), **_version("0.3.2")},
    4: {"shelf/recent.py": S4_RECENT, "checks/check_recent.py": S4_CHECK, "shelf/cli.py": S4_CLI,
        "CHANGES.md": _changes(B1, B2, B3, B4), **_version("0.3.3")},
    5: {"shelf/exporters/markdown_export.py": S5_MD, "checks/check_markdown_export.py": S5_CHECK,
        "shelf/exporters/__init__.py": S5_EXPORTERS, "CHANGES.md": _changes(B1, B2, B3, B4, B5), **_version("0.3.4")},
}


def files_for_day(day: int) -> dict[str, str]:
    """Repo content at the START of session `day` (1-based): starter + merged code of days 1..day-1."""
    files = dict(STARTER)
    for d in range(1, day):
        files.update(CANON[d])
    return files
