"""Topic labels on memories: for display and filtering only (never ranking, never injected text).

Every memory gets labels from VOCAB, assigned by deterministic keyword / path / trigger rules (`auto`). The rules aim
for precision over completeness: a wrong label misleads `memcode list --label X` and `memory_search(label=X)`, while a
missing label only means a memory appears unlabelled. Users can add or remove any label (`memcode label ID +x -y`).

Why this vocabulary (VOCAB): these are the topics that recur in what a coding agent's memory actually holds (the trigger
corpora in bench/scenarios and the live runs). They are user conventions about formatting and names, failing tests and
builds, dependency files, version control, the runtime environment, and API and database code. Each label has to be
recognisable from surface words a memory really contains, so that the rules stay precise, and coarse enough that a
typical store has several memories under it. `env` matches the facts table's environment category (env vars, config
files, toolchain versions, OS / sandbox limits). `style` (layout, formatting, linters) and `naming` are kept apart
because user rules split that way: "indent with tabs" vs "camelCase for variables".

Storage: memories.labels holds the labels comma-separated and sorted. '' means not labelled yet (backfill will do it),
and NONE ('-') means labelled, with nothing applicable. NONE exists so that backfill never re-scans a memory. Read the
column through parse() / of(), never by splitting it yourself.
"""
from __future__ import annotations

import re

VOCAB = ("testing", "build", "style", "naming", "git", "deps", "security", "env", "perf", "api", "data", "docs", "ci")
NONE = "-"
_USER_LABEL = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,31}$")

_TEST_CMD = r"pytest|py\.test|unittest|nose2?|tox|nox|jest|vitest|mocha|jasmine|karma|rspec|phpunit|ctest|go test|cargo test|npm test|npm run test|yarn test|pnpm test|bun test|make test|make check|deno test|dotnet test|mvn test|gradle test"
_BUILD_CMD = r"make(?! test| check)|cmake|ninja|tsc|webpack|vite build|rollup|esbuild|gradle(?! test)|mvn(?! test)|cargo build|go build|npm run build|yarn build|pnpm build|bazel|docker build|python3? -m build|python3? setup\.py|gcc|g\+\+|clang|javac|dotnet build"
_LINT_CMD = r"ruff|flake8|pylint|black|isort|mypy|pyright|eslint|prettier|rubocop|gofmt|golangci-lint|clippy|cargo fmt|rustfmt|stylelint|shellcheck"
_DEPS_CMD = r"pip3? install|pip-compile|poetry (?:add|install|lock|update)|uv (?:add|pip|sync|lock)|npm (?:install|i|ci|update)|yarn (?:add|install)|pnpm (?:add|install)|cargo add|go get|go mod|bundle install|gem install|composer (?:install|require)|apt(?:-get)? install|brew install|conda install"
_GIT_CMD = r"git"

_CMD_RULES = (("testing", _TEST_CMD), ("build", _BUILD_CMD), ("style", _LINT_CMD), ("deps", _DEPS_CMD),
              ("git", _GIT_CMD))
_CMD = {k: re.compile(r"^\s*(?:sudo\s+|uv run\s+|poetry run\s+|npx\s+|python3? -m\s+)*(?:" + v + r")\b", re.I)
        for k, v in _CMD_RULES}
_TICKS = re.compile(r"`([^`]+)`")

_W = lambda s: re.compile(r"(?<![\w-])(?:" + s + r")(?![\w-])", re.I)   # word-bounded alternation
_KEYWORDS = {
    "testing": _W(r"tests?|testing|unit ?tests?|test suite|test case|pytest|unittest|jest|vitest|mocha|rspec|"
                  r"fixtures?|assertions?|asserts?|mocks?|mocking|coverage|flaky|tdd|conftest(?:\.py)?"),
    "build": _W(r"build(?:s|ing)?|compil(?:e|es|ed|er|ing|ation)|makefile|cmake|webpack|bundler|transpil\w*|"
                r"linker|link errors?"),
    "style": _W(r"indent(?:ation|ed|s)?|tabs|tab characters?|spaces|whitespace|single quotes?|double quotes?|"
                r"quote style|line length|line width|format(?:ting|ter|ted)|linters?|lint(?:ing)?|prettier|black|ruff|"
                r"flake8|eslint|pep ?8|code style|style guide|semicolons?|brace style|trailing commas?"),
    "naming": _W(r"naming|camel ?case|camelcase|snake[_ ]case|kebab[- ]case|pascal ?case|screaming[_ ]snake|"
                 r"rename[ds]?|renaming|prefix(?:ed)? with|suffix(?:ed)? with|variable names?|function names?|"
                 r"file ?names?|class names?|method names?"),
    "git": _W(r"git|commits?|committ(?:ed|ing)|branch(?:es)?|rebase|rebasing|merge conflicts?|cherry-pick|"
              r"stash|pull requests?|prs?|force[- ]push|push(?:ed|ing)? to (?:main|master|origin|the remote|remote)|"
              r"\.gitignore|gitignore|squash|amend"),
    "deps": _W(r"dependenc(?:y|ies)|deps|requirements(?:-\w+)?\.txt|package\.json|package-lock\.json|yarn\.lock|"
               r"pyproject\.toml|poetry\.lock|uv\.lock|pipfile|cargo\.toml|go\.mod|gemfile|lockfiles?|"
               r"pin(?:ned)? versions?|version pins?|third[- ]party (?:packages?|librar(?:y|ies))|"
               r"vendored|pip install|npm install"),
    "security": _W(r"secrets?|passwords?|credentials?|api[ _-]?keys?|(?:auth|access|bearer|api|refresh) tokens?|"
                   r"auth|authenticat\w*|authoriz\w*|oauth|jwt|encrypt\w*|decrypt\w*|xss|csrf|"
                   r"(?:sql|command|code|shell) injection|sanitiz\w*|escap(?:e|ing) (?:user )?input|vulnerab\w*|cve|"
                   r"security|permissions? checks?"),
    "env": _W(r"environment variables?|env vars?|\.env|dotenv|virtualenv|venv|conda|docker(?:file)?|"
              r"docker containers?|python ?3?\.\d+|node ?\d+|nvm|pyenv|toolchain|interpreter|sandbox(?:ed)?|offline|"
              r"no network|network access|proxy|path variable|\$path|operating system|macos|windows|linux|wsl|"
              r"config files?|settings\.(?:py|json|ya?ml)|config\.(?:py|json|ya?ml)"),
    "perf": _W(r"performance|perf|slow(?:er|ly|ness)?|faster|latency|throughput|speed ?ups?|optimi[sz]\w*|"
               r"profil(?:e|er|ing)|benchmarks?|o\(n\^?2\)|o\(n log n\)|quadratic|caching|cache[ds]?|memory usage|"
               r"memory leaks?"),
    "api": _W(r"api|apis|endpoints?|routes?|routing|rest|restful|http|https|http requests?|request bod(?:y|ies)|"
              r"response bod(?:y|ies)|status codes?|request handlers?|graphql|grpc|webhooks?|openapi|swagger|"
              r"middleware|json body|payloads?"),
    "data": _W(r"databases?|db|sql|sqlite|postgres(?:ql)?|mysql|mongo(?:db)?|redis|queries|query|migrations?|"
               r"schemas?|database tables?|orm|sqlalchemy|transactions?|csv|parquet|dataframes?|pandas|"
               r"serializ\w*|deserializ\w*"),
    "docs": _W(r"docs|documentation|documented|readme(?:\.md)?|docstrings?|changelog(?:\.md)?|comments?|"
               r"jsdoc|sphinx|mkdocs|man ?page"),
    "ci": _W(r"ci|ci/cd|continuous integration|github actions?|github workflows?|ci workflows?|ci pipelines?|"
             r"jenkins|gitlab[- ]ci|circleci|travis|buildkite|pre-commit|precommit|status checks?"),
}

_PATH_RULES = (
    ("testing", re.compile(r"(?:^|/)(?:tests?|spec|__tests__)/|(?:^|/)test_[^/]+\.py$|_test\.(?:py|go)$|"
                           r"\.(?:test|spec)\.[jt]sx?$|(?:^|/)conftest\.py$")),
    ("ci", re.compile(r"(?:^|/)\.github/workflows/|(?:^|/)\.gitlab-ci\.yml$|(?:^|/)\.circleci/|(?:^|/)Jenkinsfile$|"
                      r"(?:^|/)\.pre-commit-config\.ya?ml$")),
    ("docs", re.compile(r"(?:^|/)docs?/|\.(?:md|rst)$", re.I)),
    ("build", re.compile(r"(?:^|/)(?:Makefile|CMakeLists\.txt|build\.gradle|webpack\.config\.[jt]s|vite\.config\.[jt]s|"
                         r"tsconfig\.json|setup\.py)$")),
    ("env", re.compile(r"(?:^|/)(?:\.env(?:\.\w+)?|Dockerfile|docker-compose\.ya?ml|\.nvmrc|\.python-version|"
                       r"\.tool-versions)$")),
    ("git", re.compile(r"(?:^|/)\.git(?:ignore|attributes|modules)$")),
    ("data", re.compile(r"(?:^|/)migrations?/|\.sql$")),
)


def _dep_file(path: str) -> bool:
    from .triggers import _DEP_NAMES
    return bool(_DEP_NAMES.match(path.rsplit("/", 1)[-1]))


def auto(trigger: str, text: str, anchor_path: str = "") -> list[str]:
    """Labels for one memory, sorted. Rules (precise rather than complete):
    trigger   dep_change -> deps
    commands  the backticked command of a fail_to_fix / retry note (and of a user rule): test runner -> testing, build tool ->
              build, linter / formatter / type checker -> style, package manager install -> deps, git -> git
              (only the command decides for these notes: their template words are not topic words)
    words     word-bounded keywords in the memory text (user rules: the rule only, without the "(context: path)" tail)
    anchor    the anchor path: tests/, test_*.py -> testing; .github/workflows -> ci; docs/, *.md -> docs; Makefile ->
              build; .env, Dockerfile -> env; dependency manifests -> deps; migrations/, *.sql -> data"""
    trigger = trigger or ""
    text = text or ""
    anchor = (anchor_path or "").strip("/")
    out: set[str] = set()
    if trigger == "dep_change":
        out.add("deps")
    if trigger in ("fail_to_fix", "retry", "revert", "dep_change", "lesson"):
        if trigger != "revert":     # a revert's `git checkout` is how it was undone, not what the note is about
            for cmd in _TICKS.findall(text):
                out.update(k for k, rx in _CMD.items() if rx.search(cmd))
        prose = ""          # derived notes are templates: only commands and anchors carry topic
    else:
        prose = text
        if trigger == "correction":
            from .pinned import _rule_text
            prose = _rule_text(text)
        for cmd in _TICKS.findall(prose):
            out.update(k for k, rx in _CMD.items() if rx.search(cmd))
    if prose:
        out.update(k for k, rx in _KEYWORDS.items() if rx.search(prose))
    if anchor:
        out.update(k for k, rx in _PATH_RULES if rx.search(anchor))
        if _dep_file(anchor):
            out.add("deps")
    return sorted(out)


def parse(s: str | None) -> list[str]:
    """The labels stored in a memories.labels value ('' / NONE -> [])."""
    return sorted({x for x in (s or "").split(",") if x and x != NONE})


def fmt(labels) -> str:
    """Column value for a set of labels: sorted, comma-separated; NONE when empty."""
    labs = sorted({x for x in labels if x and x != NONE})
    return ",".join(labs) if labs else NONE


def of(row) -> list[str]:
    """A memory's labels: the stored ones, or (not backfilled yet) what auto() would assign."""
    stored = row["labels"] if "labels" in row.keys() else ""
    if stored:
        return parse(stored)
    return auto(row["trigger"], row["text"], row["anchor_path"])


def backfill(con) -> int:
    """Label every memory whose labels are '' (new since the last run). O(unlabelled rows). Returns rows labelled."""
    rows = con.execute("SELECT id, trigger, text, anchor_path FROM memories WHERE labels=''").fetchall()
    if not rows:
        return 0
    con.executemany("UPDATE memories SET labels=? WHERE id=?",
                    [(fmt(auto(r["trigger"], r["text"], r["anchor_path"])), r["id"]) for r in rows])
    con.commit()
    return len(rows)


def edit(con, memory_id: int, changes: list[str]) -> list[str]:
    """Apply user edits like ['+perf', '-style', 'api'] (bare = add). Any well-formed label is allowed, VOCAB or not.
    Returns the new labels."""
    r = con.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    if r is None:
        raise ValueError(f"no memory #{memory_id}")
    cur = set(of(r))
    for c in changes:
        op, name = (c[0], c[1:]) if c[:1] in "+-" else ("+", c)
        name = name.strip().lower()
        if not _USER_LABEL.match(name) or name == NONE:
            raise ValueError(f"invalid label {c!r} (use lowercase letters, digits, '_', '.', '-')")
        (cur.add if op == "+" else cur.discard)(name)
    con.execute("UPDATE memories SET labels=? WHERE id=?", (fmt(cur), memory_id))
    con.commit()
    return sorted(cur)


def has(row, label: str) -> bool:
    return (label or "").strip().lower() in of(row)
