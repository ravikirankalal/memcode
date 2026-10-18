"""Facts: keyed, aggregated knowledge about the repo and how work gets done in it.

A memory records one event ("the user corrected X"). A fact is keyed and updated in place as evidence accumulates:

  command    shell commands the agent runs, per simple command, classified by role (test, build, lint, typecheck,
             format, run, install) or kept because they recur; with run / ok / fail counts and last use
  repo       read from the working tree at session start: package.json scripts, Makefile targets, pyproject, Cargo,
             go.mod, CI `run:` steps, main languages, test directory. Each carries its source file's hash and is
             rebuilt when that file changes
  env        limitations observed in this environment, e.g. a command that is not installed (exit 127 and not on PATH)
  inference  aggregated from memories and command stats: fragile folders, commands that keep failing
  user       set by the user (`memcode fact set KEY VALUE`)

Only facts derived from the command itself are recorded, never text from command output (untrusted). Commands are
redacted. The one use of output is a pass/fail verdict for a piped command (agents habitually run `cmd 2>&1 | tail`,
which hides the exit status): a known test/lint/typecheck summary line decides it; nothing from it is stored. Rendered in the session-start block as a compact "## Facts" section (inside the untrusted wrapper).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time

from . import store
from .redact import redact

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
  key TEXT PRIMARY KEY,           -- e.g. 'cmd:python3 -m unittest discover -s tests', 'repo:npm:build', 'env:missing:sqlite3'
  category TEXT NOT NULL,         -- command | repo | env | inference | user
  role TEXT,                      -- test | build | lint | typecheck | format | run | install | ...
  value TEXT NOT NULL,            -- the command / statement shown to the agent
  source TEXT NOT NULL,           -- observed | file path | derived | user
  runs INTEGER NOT NULL DEFAULT 0,
  ok INTEGER NOT NULL DEFAULT 0,
  fail INTEGER NOT NULL DEFAULT 0,
  first_seen REAL NOT NULL,
  last_seen REAL NOT NULL,
  source_hash TEXT                -- repo facts: hash of the file they were read from
);
"""

# role -> patterns on the normalized simple command
_ROLES = [
    ("test", re.compile(r"^(?:python3?\s+-m\s+)?(?:pytest|py\.test|unittest|nose2?|tox)\b|\bmanage\.py\s+test\b|"
                        r"^(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test\b|^npx\s+(?:jest|vitest|mocha)\b|^(?:jest|vitest|mocha)\b|"
                        r"^go\s+test\b|^cargo\s+(?:test|nextest)\b|^(?:mvn|gradle|\./gradlew)\b.*\btest\b|^make\s+(?:test|check)\b|"
                        r"^(?:rspec|bundle\s+exec\s+rspec|phpunit|ctest|dotnet\s+test)\b")),
    ("typecheck", re.compile(r"^(?:python3?\s+-m\s+)?mypy\b|^(?:npx\s+)?tsc\b|^pyright\b|^cargo\s+check\b")),
    ("lint", re.compile(r"^(?:python3?\s+-m\s+)?(?:ruff(?:\s+check)?|flake8|pylint|pyflakes)\b|^(?:npx\s+)?eslint\b|"
                        r"^(?:npm|pnpm|yarn)\s+(?:run\s+)?lint\b|^golangci-lint\b|^cargo\s+clippy\b|^make\s+lint\b")),
    ("format", re.compile(r"^(?:python3?\s+-m\s+)?(?:black|isort|ruff\s+format)\b|^(?:npx\s+)?prettier\b|^gofmt\b|"
                          r"^cargo\s+fmt\b|^make\s+(?:fmt|format)\b")),
    ("build", re.compile(r"^(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?build\b|^cargo\s+build\b|^go\s+build\b|^make(?:\s+(?:build|all))?$|"
                         r"^make\s+build\b|^(?:mvn|gradle|\./gradlew)\b.*\b(?:package|build|assemble)\b|^python3?\s+-m\s+build\b|"
                         r"^docker\s+build\b|^cmake\s+--build\b|^dotnet\s+build\b")),
    ("install", re.compile(r"^(?:python3?\s+-m\s+)?pip3?\s+install\b|^(?:npm|pnpm|yarn|bun)\s+(?:install|ci|i)\b|^yarn$|"
                           r"^poetry\s+install\b|^uv\s+(?:sync|pip\s+install)\b|^bundle\s+install\b|^go\s+mod\s+download\b")),
    ("run", re.compile(r"^(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:start|dev|serve)\b|^cargo\s+run\b|^go\s+run\b|"
                       r"^python3?\s+-m\s+[\w.]+|^python3?\s+[\w./-]+\.py\b|^(?:node|deno|bun)\s+[\w./-]+|^\./[\w./-]+|"
                       r"^(?:uvicorn|gunicorn|flask|rails|php\s+artisan)\b")),
]
# never facts: navigation, reading, git plumbing, shell control
_TRIVIAL = re.compile(r"^(?:cd|ls|ll|pwd|cat|head|tail|less|more|grep|rg|ag|find|fd|sed|awk|cut|sort|uniq|wc|tr|tee|xargs|"
                      r"echo|printf|true|false|sleep|until|while|for|if|then|do|done|fi|test|\[|export|set|unset|source|\.|"
                      r"mkdir|rm|cp|mv|touch|chmod|ln|stat|file|which|type|env|clear|diff|git|history|exit|wait|kill|ps|"
                      r"date|basename|dirname|realpath|readlink|du|df|uptime|nproc|whoami|id|jq|tar|unzip|gzip|curl|wget)$")
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*$")
_REDIRECT = re.compile(r"^(?:\d?>>?|&>|<)\S*$|^\d?>&\d$")
# summary lines of common runners; a pipe hides the exit status, these restore it (see _piped_verdict)
_OUT_FAIL = re.compile(r"^FAILED \((?:failures|errors)=|^=+ .*\b\d+ (?:failed|errors?)\b.* =+$|"
                       r"^(?:\d+ failed|\d+ errors?)(?:, \d+ \w+)* in [\d.]+s|^Tests:.*\b\d+ failed\b|"
                       r"^\s*Tests\s+\d+ failed\b|^FAIL\b|^--- FAIL:|^test result: FAILED\b|"
                       r"^Found \d+ errors?\b|^error(?:\[E\d+\])?:|^make(?:\[\d+\])?: \*\*\*", re.M)
_OUT_PASS = re.compile(r"^OK(?: \(.*\))?$|^=+ (?:\d+ (?:passed|skipped|deselected|xfailed|xpassed|warnings?)"
                       r"(?:, )?)+ in [\d.]+s(?: \(.*\))? =+$|^(?:\d+ (?:passed|skipped|deselected|warnings?)(?:, )?)+"
                       r" in [\d.]+s$|^Tests:\s+(?:\d+ (?:passed|skipped|todo)(?:, )?)+, \d+ total$|"
                       r"^\s*Tests\s+\d+ passed\b|^ok\s+\S+|^test result: ok\.|^All checks passed!$|"
                       r"^Success: no issues found\b", re.M)
_TAIL_FILTERS = ("tail", "cat", "tee", "less", "more")   # keep the end of the output, where summaries are
RECUR_MIN = 3                     # a non-role command becomes a fact after this many successful runs
MAX_COMMAND_FACTS = 300


def ensure(con) -> None:
    con.executescript(SCHEMA)


_FD_DUP = re.compile(r"\d*>&\d+|&>>?|>&\d*")                # 2>&1, &>, >&2: redirections, not operators
_WRAPPERS = re.compile(r"^(?:timeout\s+\S+|time|nohup|nice(?:\s+-n\s*\S+)?|stdbuf\s+\S+)\s+")
_CMD_WORD = re.compile(r"^(?=.*[A-Za-z])[\w.+/-]+$")           # a command word has at least one letter


def split_ops(cmd: str) -> list[tuple[str, str]]:
    """[(simple command, operator after it)] outside quotes; operator is one of ; && || | & or '' (end).
    File-descriptor redirections (2>&1, &>) are removed first so their '&' is not read as an operator."""
    import shlex
    cmd = _FD_DUP.sub(" ", cmd)
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=";&|")
        lex.whitespace_split = True
        lex.commenters = ""
        out, cur = [], []
        for tok in lex:
            if tok and set(tok) <= set(";&|"):
                out.append((" ".join(cur), tok))
                cur = []
            else:
                cur.append(tok)
        out.append((" ".join(cur), ""))
        return [(c, op) for c, op in out if c.strip()]
    except ValueError:
        return [(cmd.strip(), "")]


def normalize(seg: str, root: str | None = None) -> str | None:
    """A simple command as worth remembering, or None: env assignments and redirects dropped, repo root made
    relative; commands naming absolute paths outside the repo (scratch dirs, temp files) are not reusable."""
    toks = seg.split()
    while True:                                         # FOO=1 timeout 60 npm test -> npm test
        while toks and _ASSIGN.match(toks[0]):
            toks = toks[1:]
        stripped = _WRAPPERS.sub("", " ".join(toks)).split()
        if stripped == toks:
            break
        toks = stripped
    toks = [t for t in toks if not _REDIRECT.match(t)]
    if not toks or _TRIVIAL.match(toks[0]) or not _CMD_WORD.match(toks[0]) or toks[0].startswith("-"):
        return None
    if any("$" in t or "`" in t or t in ("(", ")", "{", "}") or (t.endswith("...") and not t.endswith("/...")) for t in toks):
        return None                                     # shell variables / subshells / clipped text: not reusable
    if toks[0] in ("python", "python3", "node", "deno", "bun", "ruby", "perl") and len(toks) > 1 \
            and toks[1] in ("-c", "-e", "-", "-p"):
        return None                                     # inline or stdin scripts are one-offs
    if toks[0] == "claude" and toks[1:2] == ["-p"]:
        return None
    if toks[-1] in ("--version", "-V", "--help", "-h"):
        return None                                     # `ruff --version` is a probe, not how the repo is linted
    rootp = os.path.realpath(root).rstrip("/") + "/" if root else None
    out = []
    for t in toks:
        if rootp and t.startswith(rootp):
            t = t[len(rootp):] or "."
        if t.startswith("/") and not t.startswith(("/dev/null",)) and not re.match(r"^/usr/(?:local/)?bin/", t):
            return None
        out.append(t)
    s = " ".join(out)
    return s if len(s) <= 200 else None


def _piped_verdict(rest: list[str], output: str) -> bool | None:
    """Outcome of a command piped into `rest` (the simple commands after it), read from summary lines in the
    output; None when unknown. A failure summary anywhere decides; a pass needs only end-keeping filters after
    the command (tail, cat, tee), untruncated output and no failure line, since head/grep may cut a failure off."""
    out = output or ""
    if _OUT_FAIL.search(out):
        return False
    words = [r.split()[0] for r in rest if r.split()]
    if not words or any(w not in _TAIL_FILTERS for w in words) or out.endswith("..."):
        return None
    return True if _OUT_PASS.search(out[-4000:]) else None


def role_of(cmd: str) -> str | None:
    for role, rx in _ROLES:
        if rx.search(cmd):
            return role
    return None


def _upsert(con, key, category, role, value, source, ok=0, fail=0, runs=0, ts=None, source_hash=None):
    ts = time.time() if ts is None else ts
    con.execute(
        """INSERT INTO facts(key,category,role,value,source,runs,ok,fail,first_seen,last_seen,source_hash)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(key) DO UPDATE SET runs=runs+excluded.runs, ok=ok+excluded.ok, fail=fail+excluded.fail,
             last_seen=MAX(last_seen, excluded.last_seen), value=excluded.value, role=excluded.role,
             source=excluded.source, source_hash=COALESCE(excluded.source_hash, source_hash)""",
        (key, category, role, value, source, runs, ok, fail, ts, ts, source_hash))


def observe(con, root: str, ev: dict, ts: float | None = None) -> int:
    """Record one finished shell command (normalized tool event). Returns facts touched."""
    if str(ev.get("tool", "")).lower() not in ("bash", "shell") or not ev.get("command"):
        return 0
    code = ev.get("exit_code")
    if code is None:                                    # unknown outcome (e.g. Codex): nothing to learn
        return 0
    ensure(con)
    cmd = redact(str(ev["command"]))
    if "<<" in cmd:                                     # heredoc: the body is data, only the first line is a command
        cmd = cmd.split("\n", 1)[0]
    parts = split_ops(cmd)
    segs, outside = [], False
    rootp = os.path.realpath(root).rstrip("/")
    for s, op in parts:
        w = s.split()
        if w and w[0] == "cd" and len(w) > 1:            # commands after `cd` to outside the repo are not repo facts
            target = w[1]
            outside = ("$" in target or "`" in target or target.startswith("~")    # unknown place: assume outside
                       or (target.startswith("/") and not (os.path.realpath(target) + "/").startswith(rootp + "/")))
            continue
        segs.append((s, op, None if outside else normalize(s, root)))
    # exit 0 proves a command passed only when nothing after it could mask a failure: not followed by || or |
    # a command followed by || came with a prepared fallback: its outcome is unknown and it is weak evidence
    useful = [(s, op, n) for s, op, n in segs if n and op != "||"]
    touched = 0
    if code == 127:                                     # command not found: which one? ask PATH, not the output
        words = [s.split()[0] for s, _, _ in segs if s.split() and not _ASSIGN.match(s.split()[0])
                 and _CMD_WORD.match(s.split()[0])]
        missing = [w for w in dict.fromkeys(words) if "/" not in w and shutil.which(w) is None
                   and not _TRIVIAL.match(w)]
        for w in missing[:3]:
            _upsert(con, f"env:missing:{w}", "env", "missing", f"`{w}` is not installed in this environment",
                    "observed", runs=1, fail=1, ts=ts)
            touched += 1
    if code == 0:                                       # it ran, so whatever it names is installed now
        for s, _, _ in segs:
            w = s.split()[0] if s.split() else ""
            if w and con.execute("DELETE FROM facts WHERE key=?", (f"env:missing:{w}",)).rowcount:
                touched += 1
        for _, op, n in useful:
            ok, fail = (1, 0) if op not in ("|", "&") else (0, 0)   # a pipe or background job hides the exit status
            if op == "|" and len(useful) == 1:           # `cmd 2>&1 | tail -3`: the output's summary line decides
                j = next(k for k, sg in enumerate(segs) if sg[2] == n)
                rest = []
                for s2, op2, _ in segs[j + 1:]:
                    rest.append(s2)
                    if op2 != "|":
                        break
                verdict = _piped_verdict(rest, str(ev.get("output") or ""))
                ok, fail = (1, 0) if verdict else (0, 1) if verdict is False else (0, 0)
            _upsert(con, f"cmd:{n}", "command", role_of(n), n, "observed", runs=1, ok=ok, fail=fail, ts=ts)
            touched += 1
    elif len(useful) == 1 and len(segs) == 1:           # a failure is attributable only to a lone command
        n = useful[0][2]
        _upsert(con, f"cmd:{n}", "command", role_of(n), n, "observed", runs=1, fail=1, ts=ts)
        touched += 1
    if touched:
        _prune_commands(con)
        con.commit()
    return touched


def _prune_commands(con) -> None:
    n = con.execute("SELECT COUNT(*) FROM facts WHERE category='command'").fetchone()[0]
    if n > MAX_COMMAND_FACTS:
        con.execute("""DELETE FROM facts WHERE key IN (SELECT key FROM facts WHERE category='command'
                       ORDER BY (role IS NOT NULL) ASC, ok ASC, last_seen ASC LIMIT ?)""", (n - MAX_COMMAND_FACTS,))


# ---- repo facts (static) ----

def _read(root: str, rel: str, limit: int = 200_000) -> str | None:
    p = os.path.join(root, rel)
    try:
        if os.path.getsize(p) > limit:
            return None
        with open(p, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _repo_sources(root: str) -> dict[str, list[tuple[str, str | None, str]]]:
    """{source file: [(key suffix, role, value)]} read from build manifests."""
    out: dict[str, list] = {}
    pkg = _read(root, "package.json")
    if pkg:
        try:
            scripts = (json.loads(pkg).get("scripts") or {})
        except ValueError:
            scripts = {}
        mgr = "pnpm" if os.path.exists(os.path.join(root, "pnpm-lock.yaml")) else (
            "yarn" if os.path.exists(os.path.join(root, "yarn.lock")) else "npm")
        out["package.json"] = [(f"npm:{k}", role_of(f"{mgr} run {k}") or ("run" if k in ("start", "dev") else None),
                                f"{mgr} run {k}" if k != "test" else f"{mgr} test")
                               for k in list(scripts)[:25] if isinstance(k, str) and re.match(r"^[\w:.-]+$", k)]
    mk = _read(root, "Makefile")
    if mk:
        targets = [t for t in re.findall(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", mk, re.M) if not t.startswith(".")]
        out["Makefile"] = [(f"make:{t}", role_of(f"make {t}"), f"make {t}") for t in list(dict.fromkeys(targets))[:25]]
    pp = _read(root, "pyproject.toml")
    if pp:
        items = []
        if re.search(r"^\[tool\.pytest", pp, re.M) or re.search(r"\bpytest\b", pp):
            items.append(("py:test", "test", "pytest"))
        for tool, role, cmd in (("ruff", "lint", "ruff check ."), ("mypy", "typecheck", "mypy ."),
                                ("black", "format", "black .")):
            if re.search(rf"^\[tool\.{tool}\b", pp, re.M):
                items.append((f"py:{tool}", role, cmd))
        for name in re.findall(r"^\[project\.scripts\][^\[]*", pp, re.M):
            for script in re.findall(r"^([\w-]+)\s*=", name, re.M)[:10]:
                items.append((f"py:script:{script}", "run", script))
        out["pyproject.toml"] = items
    if _read(root, "Cargo.toml") is not None:
        out["Cargo.toml"] = [("cargo:build", "build", "cargo build"), ("cargo:test", "test", "cargo test")]
    if _read(root, "go.mod") is not None:
        out["go.mod"] = [("go:build", "build", "go build ./..."), ("go:test", "test", "go test ./...")]
    wf_dir = os.path.join(root, ".github", "workflows")
    if os.path.isdir(wf_dir):
        for f in sorted(os.listdir(wf_dir))[:10]:
            if f.endswith((".yml", ".yaml")):
                rel = f".github/workflows/{f}"
                runs = re.findall(r"^\s*-?\s*run:\s*([^|>\n][^\n]*)$", _read(root, rel) or "", re.M)
                out[rel] = [(f"ci:{f}:{i}", role_of(r.strip()), r.strip()[:160]) for i, r in enumerate(runs[:15])
                            if r.strip() and not r.strip().startswith("${{")]
    return out


def scan_repo(con, root: str) -> int:
    """Refresh repo facts whose source file changed (by content hash); drop facts whose source vanished."""
    ensure(con)
    sources = _repo_sources(root)
    have = {}
    for r in con.execute("SELECT key, source, source_hash FROM facts WHERE category='repo' AND source!='paths'"):
        have.setdefault(r["source"], (r["source_hash"], []))[1].append(r["key"])
    changed = 0
    for src, items in sources.items():
        h = store.sha1((_read(root, src) or "").encode("utf-8"))
        old_hash, old_keys = have.pop(src, (None, []))
        if old_hash == h:
            continue
        con.executemany("DELETE FROM facts WHERE key=?", [(k,) for k in old_keys])
        for suffix, role, value in items:
            _upsert(con, f"repo:{suffix}", "repo", role, value, src, source_hash=h)
        changed += 1
    for src, (_, keys) in have.items():                 # source file gone
        con.executemany("DELETE FROM facts WHERE key=?", [(k,) for k in keys])
        changed += 1
    # languages and test directory, from the path index (no extra I/O)
    exts: dict[str, int] = {}
    for (p,) in con.execute("SELECT path FROM paths WHERE kind='file'"):
        e = os.path.splitext(p)[1].lower()
        if e:
            exts[e] = exts.get(e, 0) + 1
    langs = {".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript", ".go": "Go",
             ".rs": "Rust", ".java": "Java", ".kt": "Kotlin", ".rb": "Ruby", ".php": "PHP", ".cs": "C#",
             ".c": "C", ".cpp": "C++", ".swift": "Swift"}
    counts: dict[str, int] = {}
    for e, n in exts.items():
        if e in langs:
            counts[langs[e]] = counts.get(langs[e], 0) + n
    top = sorted(counts.items(), key=lambda x: -x[1])[:3]
    _set_derived(con, "repo:languages", "repo", "languages",
                 ", ".join(f"{l} ({n} files)" for l, n in top) if top else None, "paths")
    tdirs = [d for (d,) in con.execute("SELECT path FROM paths WHERE kind='dir' AND parent='' AND path IN "
                                       "('tests','test','spec','__tests__','checks')")]
    _set_derived(con, "repo:tests_dir", "repo", "tests", f"tests live in {', '.join(t + '/' for t in tdirs)}"
                 if tdirs else None, "paths")
    con.commit()
    return changed


def _set_derived(con, key, category, role, value, source):
    if value is None:
        con.execute("DELETE FROM facts WHERE key=?", (key,))
        return
    now = time.time()
    con.execute("""INSERT INTO facts(key,category,role,value,source,first_seen,last_seen) VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, role=excluded.role, last_seen=excluded.last_seen""",
                (key, category, role, value, source, now, now))


# ---- inference (aggregated) ----

FRAGILE_MIN = 0.6


def infer(con) -> None:
    """Facts aggregated from memories and command stats; recomputed each session start."""
    ensure(con)
    con.execute("DELETE FROM facts WHERE category='inference'")
    for (key,) in con.execute("SELECT key FROM facts WHERE key LIKE 'env:missing:%'").fetchall():
        if shutil.which(key[len("env:missing:"):]):       # installed since: the limitation is gone
            con.execute("DELETE FROM facts WHERE key=?", (key,))
    from . import salience
    roll = salience.rollup(con, fail_weight=0.5)
    fragile = sorted(((p, v) for p, v in roll.items() if p and v >= FRAGILE_MIN), key=lambda x: -x[1])
    # keep only the most specific fragile paths (drop an ancestor that adds nothing)
    shown = []
    for p, v in fragile:
        if not any(q.startswith(p + "/") and abs(roll[q] - v) < 1e-6 for q, _ in fragile):
            shown.append((p, v))
    for p, v in shown[:5]:
        _set_derived(con, f"inf:fragile:{p}", "inference", "fragile",
                     f"{p} is fragile: recent reverts/failures there (score {v:.2f})", "derived")
    for r in con.execute("SELECT value, fail FROM facts WHERE category='command' AND fail>=2 AND ok=0 "
                         "ORDER BY fail DESC LIMIT 3").fetchall():
        _set_derived(con, f"inf:failing:{r['value']}", "inference", "failing",
                     f"`{r['value']}` has failed {r['fail']}x and never passed here", "derived")
    con.commit()


# ---- user facts ----

def set_user(con, key: str, value: str) -> str:
    ensure(con)
    key = re.sub(r"[^\w:.\-/]+", "-", key.strip())[:80]
    if not key or not value.strip():
        raise ValueError("key and value are required")
    _set_derived(con, f"user:{key}", "user", None, redact(value.strip())[:300], "user")
    con.commit()
    return f"user:{key}"


def remove(con, key: str) -> int:
    ensure(con)
    n = con.execute("DELETE FROM facts WHERE key=? OR key=?", (key, f"user:{key}")).rowcount
    con.commit()
    return n


def list_facts(con) -> list:
    ensure(con)
    return con.execute("SELECT * FROM facts ORDER BY category, role, runs DESC, key").fetchall()


# ---- rendering ----

ROLE_ORDER = ["install", "build", "test", "lint", "typecheck", "format", "run"]


def lines(con, max_lines: int = 14) -> list[str]:
    """Compact fact lines for the session-start block, most useful first."""
    ensure(con)
    out = []
    for r in con.execute("SELECT value FROM facts WHERE category='user' ORDER BY last_seen"):
        out.append(f"- {r['value']}")
    best: dict[str, tuple] = {}                         # one command per role: observed-and-passing beats declared
    for r in con.execute("SELECT * FROM facts WHERE category IN ('command','repo') AND role IN (%s)"
                         % ",".join("?" * len(ROLE_ORDER)), ROLE_ORDER):
        score = (r["ok"] * 2 + r["runs"] - r["fail"] * 3 + (1 if r["category"] == "repo" else 0), r["last_seen"])
        if r["category"] == "command" and (r["fail"] > r["ok"] or r["runs"] == 0):
            continue
        if r["role"] not in best or score > best[r["role"]][0]:
            best[r["role"]] = (score, r)
    for role in ROLE_ORDER:
        if role in best:
            r = best[role][1]
            if r["category"] != "command":
                how = f"from {r['source']}"
            elif r["ok"]:
                how = f"ran {r['runs']}x, {r['ok']} confirmed ok" + (f", {r['fail']} failed" if r["fail"] else "")
            else:
                how = f"ran {r['runs']}x; exit status not confirmed (piped)"
            out.append(f"- {role}: `{r['value']}` ({how})")
    for r in con.execute("SELECT value FROM facts WHERE category='command' AND role IS NULL AND runs>=? "
                         "AND fail<=ok ORDER BY runs DESC LIMIT 3", (RECUR_MIN,)):
        out.append(f"- often used: `{r['value']}`")
    for r in con.execute("SELECT value FROM facts WHERE category IN ('env','inference') ORDER BY category, last_seen DESC"):
        out.append(f"- {r['value']}")
    for r in con.execute("SELECT value FROM facts WHERE key IN ('repo:languages','repo:tests_dir')"):
        out.append(f"- {r['value']}")
    return out[:max_lines]


def backfill(con, root: str, force: bool = False) -> int:
    """Build command and env facts from the event log already stored (history from before facts existed).
    Live observation also logs events, so replaying on top of live facts would double-count: only runs on an
    empty command table, or with force (which rebuilds command/env facts from the log alone)."""
    ensure(con)
    if con.execute("SELECT COUNT(*) FROM facts WHERE category IN ('command','env')").fetchone()[0]:
        if not force:
            raise ValueError("facts already exist; use force to rebuild them from the event log")
        con.execute("DELETE FROM facts WHERE category IN ('command','env')")
    n = 0
    for (payload, ts) in con.execute("SELECT payload, ts FROM events WHERE kind='tool_result' ORDER BY id").fetchall():
        try:
            ev = json.loads(payload)
        except ValueError:
            continue
        n += observe(con, root, ev, ts=ts)
    infer(con)
    return n
