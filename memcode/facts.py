"""Facts: keyed, aggregated knowledge about the repo and how work gets done in it.

A fact is a keyed memory (memories.mkey), updated in place as evidence accumulates:

  command    shell commands the agent runs, per simple command, classified by role (test, build, lint, typecheck,
             format, run, install) or kept because they recur; with run / ok / fail counts and last use. Keyed by
             cmd_key (flag variants merge); scripts and one-off actions are never recorded (#36)
  repo       read from the working tree at session start: package.json scripts, Makefile targets, pyproject, Cargo,
             go.mod, CI `run:` steps, main languages, test directory. Each carries its source file's hash and is
             rebuilt when that file changes
  env        limitations observed in this environment, e.g. a command that is not installed (exit 127 and not on PATH)
  inference  aggregated from memories and command stats: fragile folders, commands that keep failing
  user       set by the user (`memcode fact set KEY VALUE`)

Only facts derived from the command itself are recorded, never text from command output (untrusted). The one use of output is a pass/fail verdict for a piped command (agents habitually run `cmd 2>&1 | tail`,
which hides the exit status): a known test/lint/typecheck summary line decides it; nothing from it is stored. Rendered in the session-start block as a compact "## Facts" section (inside the untrusted wrapper).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time

from . import store

SCHEMA = "CREATE TABLE IF NOT EXISTS facts_meta (k TEXT PRIMARY KEY, v INTEGER NOT NULL);"
# Facts are keyed memories (memories.mkey; counters in memories.stats), read through the fact_rows view (store.py):
# key, category (command | repo | env | inference | user), role, value, source, runs, ok, fail, first_seen, last_seen,
# source_hash.
FACTS_VERSION = 2                 # 2: command facts keyed by cmd_key, one-offs and compound pieces dropped (#36)

# role -> patterns on the normalized simple command
_ROLES = [
    ("test", re.compile(r"^(?:python3?\s+-m\s+)?(?:pytest|py\.test|unittest|nose2?|tox)\b|\bmanage\.py\s+test\b|"
                        r"^(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test\b|^npx\s+(?:jest|vitest|mocha)\b|^(?:jest|vitest|mocha)\b|"
                        r"^go\s+test\b|^cargo\s+(?:test|nextest)\b|^(?:mvn|\./mvnw|gradle|\./gradlew)\b.*\b(?:test|verify)\b|^make\s+(?:test|check)\b|"
                        r"^(?:rspec|bundle\s+exec\s+rspec|phpunit|ctest|dotnet\s+test)\b")),
    ("typecheck", re.compile(r"^(?:python3?\s+-m\s+)?mypy\b|^(?:npx\s+)?tsc\b|^pyright\b|^cargo\s+check\b")),
    ("lint", re.compile(r"^(?:python3?\s+-m\s+)?(?:ruff(?:\s+check)?|flake8|pylint|pyflakes)\b|^(?:npx\s+)?eslint\b|"
                        r"^(?:npm|pnpm|yarn)\s+(?:run\s+)?lint\b|^golangci-lint\b|^cargo\s+clippy\b|^make\s+lint\b")),
    ("format", re.compile(r"^(?:python3?\s+-m\s+)?(?:black|isort|ruff\s+format)\b|^(?:npx\s+)?prettier\b|^gofmt\b|"
                          r"^cargo\s+fmt\b|^make\s+(?:fmt|format)\b")),
    ("build", re.compile(r"^(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?build\b|^cargo\s+build\b|^go\s+build\b|^make(?:\s+(?:build|all))?$|"
                         r"^make\s+build\b|^(?:mvn|\./mvnw|gradle|\./gradlew)\b.*\b(?:package|build|assemble|install)\b|^python3?\s+-m\s+build\b|"
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
                      r"mkdir|rmdir|rm|cp|mv|touch|chmod|ln|stat|file|which|type|env|clear|diff|git|history|exit|wait|kill|ps|"
                      r"date|basename|dirname|realpath|readlink|du|df|uptime|nproc|whoami|id|jq|tar|unzip|gzip|curl|wget)$")
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*$")
# env prefixes that change only how output looks: dropped from a fact. Any other VAR=value prefix is kept, because the
# command may only work with it (TALLY_DATA=ledger python3 -m tally ...; tc2, Run 17).
_COSMETIC_ENV = re.compile(r"^(?:NO_COLOR|FORCE_COLOR|CLICOLOR(?:_FORCE)?|TERM|COLUMNS|LINES|PAGER|GIT_PAGER|LESS|"
                           r"LANG|LC_\w+|TZ|PYTHONUNBUFFERED|PYTHONDONTWRITEBYTECODE|CI|MEMCODE_\w+)=")
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
    row = con.execute("SELECT v FROM facts_meta WHERE k='version'").fetchone()
    if not row or row[0] < FACTS_VERSION:
        _migrate(con)


def _migrate(con) -> None:
    """Bring command facts written by older versions to today's rules: drop what normalize/one_off_command would not record
    now, and merge variants that share a cmd_key (#36). Counts are summed; the newest passing variant is shown."""
    rows = con.execute("SELECT * FROM fact_rows WHERE category='command' ORDER BY ok>0, last_seen").fetchall()
    _delete(con, "category='command'")
    for r in rows:
        v = r["value"]
        if normalize(v) != v or one_off_command(v):
            continue
        _upsert(con, f"cmd:{cmd_key(v)}", "command", role_of(v), v, r["source"], ok=r["ok"], fail=r["fail"],
                runs=r["runs"], ts=r["last_seen"])
    con.execute("INSERT INTO facts_meta(k, v) VALUES('version', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (FACTS_VERSION,))
    con.commit()


# A Bash call that is a script, not a command: loops, conditionals, functions, substitutions, subshells, several
# lines. Its pieces are not commands anyone would rerun ("b8dcf40 34302cd" from a for-list, "mvn -v)" from a $( )).
_SCRIPT = re.compile(r"(?:^|[;&|({\n]\s*)(?:for|while|until|if|case|select|function)\s|\$\(|`|<\(|>\(|"
                     r"(?:^|[;&|\n]\s*)\(|\b[\w-]+\s*\(\)\s*\{|\n\s*\S")
# Commands that act on one thing once, or manage tools rather than the repo: never a repo workflow fact (#36)
_ONE_OFF = re.compile(
    r"^(?:gh|glab|hub|pgrep|pidof|ssh|scp|sftp|rsync|open|xdg-open|code|cursor|osascript|brew|apt(?:-get)?|yum|dnf|"
    r"pacman|snap|man|tldr|tmux|screen|pkill|killall|lsof|netstat|ping|dig|nslookup|telnet|nc|psql|mysql|"
    r"sqlite3|redis-cli|mongo(?:sh)?)\b"
    r"|^claude\b(?!\s+plugin\s+(?:test|validate)\b)"    # plugin management is one-off; a plugin repo's own checks are not
    r"|^(?:kubectl|oc)\b.*\s(?:exec|logs|port-forward|describe|get|top|cp|attach|debug|edit|delete)\b"
    r"|^docker(?:\s+compose)?\b.*\s(?:exec|logs|ps|inspect|rm|stop|kill|attach|images|pull)\b"
    r"|^(?:npm|pnpm|yarn)\s+(?:view|info|outdated|ls|why|search)\b|^pip3?\s+(?:show|list|freeze|download)\b"
    r"|(?:^|\s)(?:--help|-h|help|--version|-V)(?:\s|$)")
_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_KEY_VALUE_FLAGS = {"-k", "-n", "-j", "-T", "--tb", "--maxfail", "--timeout", "-t", "--namespace", "--context"}


def one_off_command(cmd: str) -> bool:
    """A normalized command that is a one-time action or a tool probe, not a way to build/test/run the repo."""
    toks = re.sub(r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+", "", cmd).split()
    return bool(_ONE_OFF.search(" ".join(toks))) or any(_SHA.match(t) and re.search(r"\d", t) for t in toks[1:])


def cmd_key(cmd: str) -> str:
    """Variants that differ only by flags share a fact: flags dropped (and the value of a flag that takes one), but
    `-m` kept so `python3 -m pytest` stays itself. `pytest -q` and `pytest -x` -> one fact, shown as the newest
    passing variant."""
    out, prev = [], ""
    for t in cmd.split():
        if prev in _KEY_VALUE_FLAGS or (prev.startswith("--") and "=" not in prev
                                        and re.fullmatch(r"[a-z][a-z0-9_-]*", t)):
            prev = ""                                   # the value of the flag before it (`--output-format concise`)
            continue
        prev = t
        if t.startswith("-") and t != "-m":
            continue
        out.append(t)
    return " ".join(out)


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
    """A simple command as worth remembering, or None: wrappers, redirects and cosmetic env prefixes dropped, other
    env prefixes kept (the command may need them), repo root made relative; commands naming absolute paths outside
    the repo (scratch dirs, temp files) are not reusable."""
    toks = seg.split()
    env: list[str] = []
    while True:                                         # FOO=1 timeout 60 npm test -> FOO=1 npm test
        while toks and _ASSIGN.match(toks[0]):
            if not _COSMETIC_ENV.match(toks[0]):
                env.append(toks[0])
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
    if seg.count("(") != seg.count(")") or seg.count("{") != seg.count("}"):
        return None                                     # a piece cut out of $( ... ) or { ... }: `mvn -v)` (#36)
    if toks[0] in ("python", "python3", "node", "deno", "bun", "ruby", "perl") and len(toks) > 1 \
            and toks[1] in ("-c", "-e", "-", "-p"):
        return None                                     # inline or stdin scripts are one-offs
    if toks[0] == "claude" and toks[1:2] == ["-p"]:
        return None
    if toks[0] in ("bash", "sh", "zsh", "dash") and "-c" in toks[1:3]:
        return None                                     # an inline shell script: a one-off (#36)
    if any("$" in a or "`" in a for a in env):
        return None                                     # a variable in the prefix: not a reusable command
    toks = env + toks
    if toks[-1] in ("--version", "-V", "--help", "-h"):
        return None                                     # `ruff --version` is a probe, not how the repo is linted
    rootp = os.path.realpath(root).rstrip("/") + "/" if root else None
    out = []
    for t in toks:
        name, eq, val = t.partition("=") if _ASSIGN.match(t) else ("", "", t)
        if rootp and val.startswith(rootp):
            val = val[len(rootp):] or "."
        if val.startswith("/") and not val.startswith(("/dev/null",)) and not re.match(r"^/usr/(?:local/)?bin/", val):
            return None
        out.append(name + eq + val)
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
    cmd = re.sub(r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+", "", cmd)    # TALLY_DATA=ledger python3 -m x: role of the rest
    for role, rx in _ROLES:
        if rx.search(cmd):
            return role
    return None


def _origin(category: str) -> str:
    return "manual" if category == "user" else category


def _delete(con, where: str, params=()) -> int:
    """Delete the facts matching a fact_rows condition (with their vectors and links)."""
    ids = [r[0] for r in con.execute(f"SELECT id FROM fact_rows WHERE {where}", params).fetchall()]
    store.delete_ids(con, ids)
    return len(ids)


def _upsert(con, key, category, role, value, source, ok=0, fail=0, runs=0, ts=None, source_hash=None):
    ts = time.time() if ts is None else ts
    r = con.execute("SELECT * FROM fact_rows WHERE key=?", (key,)).fetchone()
    if r is None:
        stats = {"role": role, "source": source, "runs": runs, "ok": ok, "fail": fail, "source_hash": source_hash}
        con.execute("""INSERT INTO memories(trigger, text, anchor_path, provenance, created_at, updated_at, topic, mkey,
                         stats) VALUES(?,?,'','{}',?,?,?,?,?)""",
                    (_origin(category), value, ts, ts, role or "", key, json.dumps(stats)))
        return
    stats = {"role": role, "source": source, "runs": r["runs"] + runs, "ok": r["ok"] + ok, "fail": r["fail"] + fail,
             "source_hash": source_hash or r["source_hash"]}
    con.execute("UPDATE memories SET text=?, topic=?, stats=?, updated_at=MAX(updated_at, ?) WHERE id=?",
                (value if ok > 0 or r["ok"] == 0 else r["value"], role or "", json.dumps(stats), ts, r["id"]))


def observe(con, root: str, ev: dict, ts: float | None = None) -> int:
    """Record one finished shell command (normalized tool event). Returns facts touched."""
    if str(ev.get("tool", "")).lower() not in ("bash", "shell") or not ev.get("command"):
        return 0
    code = ev.get("exit_code")
    if code is None:                                    # unknown outcome (e.g. Codex): nothing to learn
        return 0
    ensure(con)
    cmd = str(ev["command"])
    if "<<" in cmd:                                     # heredoc: the body is data, only the first line is a command
        cmd = cmd.split("\n", 1)[0]
    script = bool(_SCRIPT.search(cmd.strip()))          # loops, $( ), functions, several lines: no command facts
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
        n = None if outside or script else normalize(s, root)
        segs.append((s, op, None if n is None or one_off_command(n) else n))
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
            if w and _delete(con, "key=?", (f"env:missing:{w}",)):
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
            if role_of(n) is None and len(segs) > 1:
                continue                                # a plain piece of a chain is no workflow; roles still count
            _upsert(con, f"cmd:{cmd_key(n)}", "command", role_of(n), n, "observed", runs=1, ok=ok, fail=fail, ts=ts)
            touched += 1
    elif len(useful) == 1 and len(segs) == 1:           # a failure is attributable only to a lone command
        n = useful[0][2]
        _upsert(con, f"cmd:{cmd_key(n)}", "command", role_of(n), n, "observed", runs=1, fail=1, ts=ts)
        touched += 1
    if touched:
        _prune_commands(con)
        con.commit()
    return touched


def _prune_commands(con) -> None:
    n = con.execute("SELECT COUNT(*) FROM fact_rows WHERE category='command'").fetchone()[0]
    if n > MAX_COMMAND_FACTS:
        _delete(con, """key IN (SELECT key FROM fact_rows WHERE category='command'
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
    if _read(root, "pom.xml") is not None:
        mvn = "./mvnw" if os.path.exists(os.path.join(root, "mvnw")) else "mvn"
        out["pom.xml"] = [("mvn:build", "build", f"{mvn} package"), ("mvn:test", "test", f"{mvn} test")]
    for gfile in ("build.gradle.kts", "build.gradle"):
        if _read(root, gfile) is not None:
            gw = "./gradlew" if os.path.exists(os.path.join(root, "gradlew")) else "gradle"
            out[gfile] = [("gradle:build", "build", f"{gw} build"), ("gradle:test", "test", f"{gw} test")]
            break
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
    for r in con.execute("SELECT key, source, source_hash FROM fact_rows WHERE category='repo' AND source!='paths'"):
        have.setdefault(r["source"], (r["source_hash"], []))[1].append(r["key"])
    changed = 0
    for src, items in sources.items():
        h = store.sha1((_read(root, src) or "").encode("utf-8"))
        old_hash, old_keys = have.pop(src, (None, []))
        if old_hash == h:
            continue
        for k in old_keys:
            _delete(con, "key=?", (k,))
        for suffix, role, value in items:
            _upsert(con, f"repo:{suffix}", "repo", role, value, src, source_hash=h)
        changed += 1
    for src, (_, keys) in have.items():                 # source file gone
        for k in keys:
            _delete(con, "key=?", (k,))
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
    systems = [name for f, name in (("pom.xml", "Maven"), ("build.gradle.kts", "Gradle"), ("build.gradle", "Gradle"),
                                    ("package.json", "npm"), ("pyproject.toml", "pyproject"), ("Cargo.toml", "Cargo"),
                                    ("go.mod", "Go modules"), ("Makefile", "make"))
               if os.path.exists(os.path.join(root, f))]
    _set_derived(con, "repo:build_system", "repo", "build_system",
                 "built with " + ", ".join(dict.fromkeys(systems)) if systems else None, "paths")
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
        _delete(con, "key=?", (key,))
        return
    r = con.execute("SELECT id, stats FROM memories WHERE mkey=?", (key,)).fetchone()
    if r is None:
        _upsert(con, key, category, role, value, source)
        return
    stats = dict(json.loads(r["stats"] or "{}"), role=role)
    con.execute("UPDATE memories SET text=?, topic=?, stats=?, updated_at=? WHERE id=?",
                (value, role or "", json.dumps(stats), time.time(), r["id"]))


# ---- inference (aggregated) ----

FRAGILE_MIN = 0.6


def infer(con) -> None:
    """Facts aggregated from memories and command stats; recomputed each session start."""
    ensure(con)
    _delete(con, "category='inference'")
    for (key,) in con.execute("SELECT key FROM fact_rows WHERE key LIKE 'env:missing:%'").fetchall():
        if shutil.which(key[len("env:missing:"):]):       # installed since: the limitation is gone
            _delete(con, "key=?", (key,))
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
    for r in con.execute("SELECT value, fail FROM fact_rows WHERE category='command' AND fail>=2 AND ok=0 "
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
    _set_derived(con, f"user:{key}", "user", None, value.strip()[:300], "user")
    con.commit()
    return f"user:{key}"


def remove(con, key: str) -> int:
    ensure(con)
    n = _delete(con, "key=? OR key=?", (key, f"user:{key}"))
    con.commit()
    return n


def list_facts(con) -> list:
    ensure(con)
    return con.execute("SELECT * FROM fact_rows ORDER BY category, role, runs DESC, key").fetchall()


# ---- rendering ----

ROLE_ORDER = ["install", "build", "test", "lint", "typecheck", "format", "run"]


def shown(con, max_lines: int = 14) -> list[tuple]:
    """The facts worth showing, most useful first: [(fact_rows row, label, text)]. label is the role for the one
    command shown per role (observed-and-passing beats declared), else None."""
    ensure(con)
    out = []
    for r in con.execute("SELECT * FROM fact_rows WHERE category='user' ORDER BY last_seen"):
        out.append((r, None, r["value"]))
    best: dict[str, tuple] = {}
    for r in con.execute("SELECT * FROM fact_rows WHERE category IN ('command','repo') AND role IN (%s)"
                         % ",".join("?" * len(ROLE_ORDER)), ROLE_ORDER):
        score = (r["ok"] * 2 + r["runs"] - r["fail"] * 3 + (1 if r["category"] == "repo" else 0), r["last_seen"])
        if r["category"] == "command" and (r["fail"] > r["ok"] or r["ok"] == 0):
            continue                                    # never confirmed to pass: not shown (#36)
        if r["role"] not in best or score > best[r["role"]][0]:
            best[r["role"]] = (score, r)
    for role in ROLE_ORDER:
        if role in best:
            r = best[role][1]
            if r["category"] != "command":
                how = f"from {r['source']}"
            else:
                how = f"ran {r['runs']}x, {r['ok']} confirmed ok" + (f", {r['fail']} failed" if r["fail"] else "")
            out.append((r, role, f"`{r['value']}` ({how})"))
    for r in con.execute("SELECT * FROM fact_rows WHERE category='command' AND role IS NULL AND ok>=? "
                         "AND fail<=ok ORDER BY ok DESC LIMIT 3", (RECUR_MIN,)):
        out.append((r, "often used", f"`{r['value']}`"))
    for r in con.execute("SELECT * FROM fact_rows WHERE category IN ('env','inference') ORDER BY category, last_seen DESC"):
        out.append((r, None, r["value"]))
    for r in con.execute("SELECT * FROM fact_rows WHERE key IN ('repo:languages','repo:build_system','repo:tests_dir') "
                         "ORDER BY key"):
        out.append((r, None, r["value"]))
    return out[:max_lines]


def lines(con, max_lines: int = 14) -> list[str]:
    """Compact fact lines (`memcode facts`, the memory agent's briefing), most useful first."""
    return [f"- {label}: {text}" if label else f"- {text}" for _, label, text in shown(con, max_lines)]


def backfill(con, root: str, force: bool = False) -> int:
    """Build command and env facts from the event log already stored (history from before facts existed).
    Live observation also logs events, so replaying on top of live facts would double-count: only runs on an
    empty command table, or with force (which rebuilds command/env facts from the log alone)."""
    ensure(con)
    if con.execute("SELECT COUNT(*) FROM fact_rows WHERE category IN ('command','env')").fetchone()[0]:
        if not force:
            raise ValueError("facts already exist; use force to rebuild them from the event log")
        _delete(con, "category IN ('command','env')")
    n = 0
    for (payload, ts) in con.execute("SELECT payload, ts FROM events WHERE kind='tool_result' ORDER BY id").fetchall():
        try:
            ev = json.loads(payload)
        except ValueError:
            continue
        n += observe(con, root, ev, ts=ts)
    infer(con)
    return n
