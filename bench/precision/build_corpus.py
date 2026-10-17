"""Build bench/precision/corpus.jsonl: user turns labelled rule / not_rule, for measuring capture precision.

  python3 bench/precision/build_corpus.py            # rebuild (keeps the frozen real rows if the sources are absent)

Each row: {id, text, prior_agent_action, label, scope, category, source, borderline, note}
  prior_agent_action  what the agent did between the previous user turn and this one, as memcode's two-tier
                      capture condition sees it:
                        none       first turn of the session (the agent has not used Bash or an edit tool yet)
                        text_only  the agent only replied in text since the last turn, but did use Bash/edit EARLIER
                                   in the session (memcode's strong tier)
                        tool       the agent ran a Bash command since the last turn (weak tier)
                        edit       the agent edited a file since the last turn (weak tier, rule gets a context path)
  label               rule = a standing convention/rule for this codebase or project that should apply in future
                      sessions; not_rule = everything else (task directions, approvals, questions, complaints,
                      corrections of the agent's interpretation, one-off instructions, fixes to the current change)
  scope               repo | dir | file for rules, none otherwise
  borderline          True where a careful reader could label the other way; metrics are also reported without them
  source              real (the user's own turns in this repo) | synthetic

Real rows come from (read-only):
  * the repo's memcode store, events kind='prompt' (only 18 user turns, memcode was enabled late), and
  * the main session transcript of this repo (~/.claude/projects/-home-user-memcode/<session>.jsonl), which also says
    what the agent did before each turn. Harness turns (<agent-message, <task-notification, <system-reminder, Stop-hook
    feedback, skill bodies, compaction summaries) are excluded: the store shows Stop-hook feedback never reaches the
    prompt hook, and engine.is_harness drops the rest.
Synthetic rows were written BEFORE any change to the triggers was designed (frozen); the proposal is also checked on
a separate held-out set written afterwards (heldout.jsonl).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from memcode.redact import redact  # noqa: E402

STORE = Path("/home/user/memcode/.memcode/memory.db")
TRANSCRIPTS = [Path.home() / ".claude/projects/-home-user-memcode/8067e07a-55bf-587b-83df-bff1f90a2e13.jsonl"]
HARNESS = ("<agent-message", "<task-notification", "<system-reminder", "<local-command", "[SYSTEM", "<command-",
           "Stop hook feedback", "Base directory for this skill", "# Update Config Skill", "<artifact-content")
ORDER = ["none", "text_only", "tool", "edit"]

# ---------------------------------------------------------------- real rows: labels by normalized text prefix
# Default for a real turn is not_rule; category picked below. Overrides here.
REAL_OVERRIDES = {
    "no, not just heirarchical memory": ("not_rule", "none", "interpretation_correction", False,
                                         "the dogfooding false positive: corrects the agent's reading of the request"),
    "maintain a learnings page and keep it up to date": ("rule", "repo", "process_rule", True,
                                                         "standing process instruction for this project"),
    "deligate test runs to subagents": ("not_rule", "none", "one_off_instruction", True,
                                        "working style for this session, not a codebase convention"),
    "continue, don't focus on teams": ("not_rule", "none", "one_off_instruction", False, "scope of current work"),
    "that is way to long": ("not_rule", "none", "complaint", False, ""),
    "planner subagent is showing up as completed": ("not_rule", "none", "status_remark", False, ""),
    "drop the serena idea": ("not_rule", "none", "task_direction", False, ""),
    "let them all talk to each other": ("not_rule", "none", "task_direction", False, ""),
    "both, use subagents": ("not_rule", "none", "task_direction", False, ""),
    "phase one looks good": ("not_rule", "none", "approval", False, ""),
    "looks like working directory has a lot": ("not_rule", "none", "task_direction", False, ""),
    "pr is merged. continue": ("not_rule", "none", "approval", False, ""),
    "merged, now continue": ("not_rule", "none", "approval", False, ""),
    "we can give it a memory budget": ("not_rule", "none", "task_direction", False, "design ideas + request for opinion"),
    "quote verbatim any memcode note": ("not_rule", "none", "question", False, "benchmark probe prompt"),
    "reply only: ok": ("not_rule", "none", "task_direction", False, "benchmark probe prompt"),
}


def _norm(t: str) -> str:
    return " ".join(t.split()).lower()


def _real_category(t: str) -> str:
    n = _norm(t)
    if n.startswith(("yes", "ok", "merge", "open pr", "commit and merge", "looks good")):
        return "approval"
    if n.startswith(("show me", "show the")):
        return "progress_request"
    if n.endswith("?") or n.startswith(("what ", "how ", "why ", "is it", "where", "wher ", "i want to know")):
        return "question"
    return "task_direction"


def _real_from_sources() -> list[dict]:
    rows: dict[str, dict] = {}
    for tp in TRANSCRIPTS:
        if not tp.exists():
            continue
        action, ever = "none", False
        for line in tp.open():
            d = json.loads(line)
            if d.get("type") == "assistant":
                for b in d["message"].get("content", []) or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        nm = b.get("name", "").lower()
                        a = "edit" if nm in ("edit", "write", "multiedit", "notebookedit") else (
                            "tool" if nm == "bash" else "text_only")
                        if ORDER.index(a) > ORDER.index(action):
                            action = a
                    elif isinstance(b, dict) and b.get("type") == "text" and action == "none":
                        action = "text_only"
            elif d.get("type") == "user":
                c = d["message"].get("content")
                if isinstance(c, list):
                    if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                        continue
                    c = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
                if not isinstance(c, str) or not c.strip():
                    continue
                if c.lstrip().startswith(HARNESS) or (d.get("origin") or {}).get("kind") not in (None, "human"):
                    continue
                prior = action if action in ("tool", "edit") else ("text_only" if ever else "none")
                rows.setdefault(_norm(c), {"text": c.strip(), "priors": []})["priors"].append(prior)
                if action in ("tool", "edit"):
                    ever = True
                action = "none"
    if STORE.exists():                               # probe prompts from short sessions not in the transcript
        con = sqlite3.connect(f"file:{STORE}?mode=ro", uri=True)
        for (p,) in con.execute("SELECT payload FROM events WHERE kind='prompt' ORDER BY id"):
            t = (json.loads(p).get("prompt") or "")
            if t.strip() and not t.lstrip().startswith(HARNESS):
                rows.setdefault(_norm(t), {"text": t.strip(), "priors": ["none"]})
        con.close()
    out = []
    for n, r in rows.items():
        label, scope, cat, border, note = "not_rule", "none", _real_category(r["text"]), False, ""
        for k, v in REAL_OVERRIDES.items():
            if n.startswith(k):
                label, scope, cat, border, note = v
        # the most common prior for repeated turns ("show me the progress" x5): the one memcode saw most
        prior = max(set(r["priors"]), key=lambda p: (r["priors"].count(p), ORDER.index(p)))
        out.append({"text": redact(r["text"]), "prior_agent_action": prior, "label": label, "scope": scope,
                    "category": cat, "source": "real", "borderline": border, "note": note,
                    "real_turns": len(r["priors"])})
    return out


# ---------------------------------------------------------------- synthetic rows
# (text, prior, label, scope, category[, borderline[, note]])
R, N = "rule", "not_rule"
SYNTHETIC = [
    # -- genuine conventions, imperative
    ("Always run the tests with ./qa, never call pytest directly.", "edit", R, "repo", "convention_imperative"),
    ("Never commit directly to main; open a branch first.", "tool", R, "repo", "convention_imperative"),
    ("Please always use type hints on new public functions.", "edit", R, "repo", "convention_imperative"),
    ("Never use print for diagnostics in this codebase, use the logger.", "edit", R, "repo", "convention_imperative"),
    ("Always add a CHANGELOG entry when you change behaviour.", "tool", R, "repo", "convention_imperative"),
    ("Never import from the internal modules of other packages.", "text_only", R, "repo", "convention_imperative"),
    ("Make sure every new endpoint has an integration test, always.", "edit", R, "repo", "convention_imperative"),
    ("Use f-strings, never % formatting.", "edit", R, "repo", "convention_imperative"),
    ("Don't ever hardcode credentials or tokens in source files.", "edit", R, "repo", "convention_imperative"),
    ("Do not add new dependencies without asking me first.", "tool", R, "repo", "convention_imperative"),
    ("Always keep functions under 50 lines in this project.", "edit", R, "repo", "convention_imperative"),
    ("In the migrations/ folder, never edit an existing migration; add a new one.", "edit", R, "dir", "convention_imperative"),
    ("In api/handlers.py always validate input with the schema helpers before touching the DB.", "edit", R, "file",
     "convention_imperative"),
    ("Never run the full integration suite locally, it hits staging. Use make test-unit.", "tool", R, "repo",
     "convention_imperative"),
    ("Always name test files test_<module>.py.", "text_only", R, "repo", "convention_imperative"),
    ("From now on, put new utilities in lib/utils/ rather than at the top level.", "text_only", R, "repo",
     "convention_imperative"),
    ("Remember that the frontend uses pnpm, not npm.", "tool", R, "dir", "convention_imperative"),
    ("Always run ./qa instead of pytest here.", "none", R, "repo", "convention_imperative", False,
     "first turn of a session"),
    # -- genuine conventions, descriptive
    ("We indent with tabs in this repo.", "edit", R, "repo", "convention_descriptive"),
    ("Our standard is Google-style docstrings.", "edit", R, "repo", "convention_descriptive"),
    ("Heads up: this team prefers single quotes for strings.", "edit", R, "repo", "convention_descriptive"),
    ("FYI we indent with tabs here, not spaces.", "edit", R, "repo", "convention_descriptive"),
    ("Just so you know, all timestamps in the DB are UTC.", "text_only", R, "repo", "convention_descriptive"),
    ("The convention here is snake_case module names.", "tool", R, "repo", "convention_descriptive"),
    ("We use pnpm in this monorepo.", "tool", R, "repo", "convention_descriptive"),
    ("In this project config comes from settings.toml, not environment variables.", "edit", R, "repo",
     "convention_descriptive"),
    ("Around here, error messages go in messages.py so they can be translated.", "edit", R, "repo",
     "convention_descriptive"),
    ("Our team writes commit messages in the imperative mood.", "tool", R, "repo", "convention_descriptive"),
    ("This codebase uses absolute imports only.", "edit", R, "repo", "convention_descriptive"),
    ("Tests live under checks/ in this repo, not tests/.", "edit", R, "repo", "convention_descriptive"),
    ("We keep SQL in the queries/ directory rather than inline.", "text_only", R, "repo", "convention_descriptive"),
    ("For the record, the payments service talks to Stripe only through payments/gateway.py.", "text_only", R, "dir",
     "convention_descriptive"),
    ("Note that all money amounts in billing/ are integer cents.", "edit", R, "dir", "convention_descriptive"),
    ("We prefer dataclasses over plain dicts for structured data.", "edit", R, "repo", "convention_descriptive"),
    ("Keep in mind the build must stay Python 3.8 compatible.", "tool", R, "repo", "convention_descriptive"),
    ("Before you start: we use pnpm in this repo, not npm.", "none", R, "repo", "convention_descriptive", False,
     "first turn of a session"),
    ("Our standard is to keep migrations reversible.", "none", R, "repo", "convention_descriptive", False,
     "first turn of a session"),
    # -- corrections of code that carry a general rule
    ("No, use pathlib instead of os.path.", "edit", R, "repo", "code_correction_general"),
    ("No - use the logger from log.py, not print.", "edit", R, "repo", "code_correction_general"),
    ("That's wrong, we use pytest fixtures, not setUp methods.", "edit", R, "repo", "code_correction_general"),
    ("No, don't use requests here; this project uses httpx everywhere.", "edit", R, "repo", "code_correction_general"),
    ("Nope, use Decimal for money, floats lose cents.", "edit", R, "repo", "code_correction_general"),
    ("No. Dates should be ISO 8601 strings in the API, not epoch seconds.", "edit", R, "repo", "code_correction_general"),
    ("Use the existing retry helper instead of writing your own loop.", "edit", R, "repo", "code_correction_general"),
    ("No, constants go in constants.py, not at the top of each module.", "edit", R, "repo", "code_correction_general"),
    ("Don't use mocks for the database in these tests, we use the sqlite fixture.", "edit", R, "repo",
     "code_correction_general"),
    ("You shouldn't catch bare Exception, catch the specific error.", "edit", R, "repo", "code_correction_general"),
    ("Wrong library: we use structlog, not the stdlib logging module.", "edit", R, "repo", "code_correction_general"),
    ("No, use `uv run` to execute scripts in this repo, not plain python.", "tool", R, "repo", "code_correction_general"),
    ("Instead, use the make target; the raw docker command misses the env file.", "tool", R, "repo",
     "code_correction_general"),
    ("That's not how we name branches - it's feature/<ticket>-<slug>.", "tool", R, "repo", "code_correction_general"),
    ("No, migrations must be reversible, add a down step.", "edit", R, "repo", "code_correction_general"),
    # -- corrections of the current change only (no standing rule)
    ("No, the function should return None there, not raise.", "edit", N, "none", "code_correction_specific"),
    ("No, that's the wrong variable, use total not subtotal.", "edit", N, "none", "code_correction_specific"),
    ("That's wrong, the loop should start at 1.", "edit", N, "none", "code_correction_specific"),
    ("No, put the check before the early return.", "edit", N, "none", "code_correction_specific"),
    ("Undo that last change to the README.", "edit", N, "none", "code_correction_specific"),
    ("Revert that, the old version was right.", "edit", N, "none", "code_correction_specific"),
    ("No, the timeout should be 30 seconds, not 300.", "edit", N, "none", "code_correction_specific"),
    ("Use 'user_id' instead of 'uid' in this function.", "edit", N, "none", "code_correction_specific"),
    ("Nope, the test is failing because of the fixture, not the code. Look at conftest.", "tool", N, "none",
     "code_correction_specific"),
    ("No - the bug is in parse_header, not in the caller.", "tool", N, "none", "code_correction_specific"),
    ("That's not right, the expected value in the assertion should be 42.", "edit", N, "none",
     "code_correction_specific"),
    ("Don't change the signature of process_order, just fix the body.", "edit", N, "none", "code_correction_specific"),
    ("No, rename it back to fetch_all.", "edit", N, "none", "code_correction_specific"),
    ("Stop editing utils.py, the problem is in the handler.", "edit", N, "none", "code_correction_specific"),
    ("No, delete the extra blank line you added at line 40.", "edit", N, "none", "code_correction_specific"),
    # -- corrections of the agent's interpretation / task scope
    ("No, not just the retrieval part, I am talking about the whole project.", "tool", N, "none",
     "interpretation_correction"),
    ("No, I meant the whole project, not only the CLI.", "tool", N, "none", "interpretation_correction"),
    ("Not that file, the other one.", "edit", N, "none", "interpretation_correction"),
    ("No, I was asking about the staging deploy, not production.", "tool", N, "none", "interpretation_correction"),
    ("No, I meant summarize the results, don't rerun anything.", "tool", N, "none", "interpretation_correction"),
    ("No, I'm talking about the old benchmark, the one from last week.", "tool", N, "none",
     "interpretation_correction"),
    ("That's not what I asked. I wanted a list of the failing tests, not fixes.", "edit", N, "none",
     "interpretation_correction"),
    ("No no, the question was whether it is useful at all.", "tool", N, "none", "interpretation_correction"),
    ("You misunderstood, I want a plan first, not code.", "edit", N, "none", "interpretation_correction"),
    ("Not the backend, the frontend build is the one that's broken.", "tool", N, "none", "interpretation_correction"),
    ("No, the other PR. #42, not #41.", "tool", N, "none", "interpretation_correction"),
    ("I meant the integration tests, not the unit tests.", "tool", N, "none", "interpretation_correction"),
    ("No, look at the logs from today's run, not yesterday's.", "tool", N, "none", "interpretation_correction"),
    ("Wrong repo - I'm talking about memcode, not the website.", "tool", N, "none", "interpretation_correction"),
    ("No, that's not what I mean. Compare memcode on vs off, not two memcode versions.", "tool", N, "none",
     "interpretation_correction"),
    ("Nope, I want the summary in the chat, not a new file.", "edit", N, "none", "interpretation_correction"),
    # -- one-off instructions
    ("Don't run the benchmark now, it costs money.", "tool", N, "none", "one_off_instruction"),
    ("Stop, wait.", "tool", N, "none", "one_off_instruction"),
    ("Stop. Let me check something first.", "tool", N, "none", "one_off_instruction"),
    ("Don't push yet.", "tool", N, "none", "one_off_instruction"),
    ("Don't merge this one until Maria reviews it.", "tool", N, "none", "one_off_instruction"),
    ("Do not touch the database right now, a migration is running.", "tool", N, "none", "one_off_instruction"),
    ("Hold off on the refactor for now.", "edit", N, "none", "one_off_instruction"),
    ("Skip the slow tests this time.", "tool", N, "none", "one_off_instruction"),
    ("No, don't open a PR for this, just commit locally.", "tool", N, "none", "one_off_instruction"),
    ("Never mind the lint errors for now, focus on the failing test.", "tool", N, "none", "one_off_instruction"),
    ("Stop the background job.", "tool", N, "none", "one_off_instruction"),
    ("Don't bother with docs in this PR.", "edit", N, "none", "one_off_instruction"),
    ("Leave the old config file alone today, I'll clean it up.", "edit", N, "none", "one_off_instruction"),
    ("Do not delete those temp files yet, I want to inspect them.", "tool", N, "none", "one_off_instruction"),
    ("Pause here and show me the diff before committing.", "edit", N, "none", "one_off_instruction"),
    # -- approvals
    ("yes, merge", "tool", N, "none", "approval"),
    ("Looks good, ship it.", "edit", N, "none", "approval"),
    ("ok go ahead", "text_only", N, "none", "approval"),
    ("Yes please", "tool", N, "none", "approval"),
    ("Perfect, thanks!", "edit", N, "none", "approval"),
    ("LGTM, open the PR.", "edit", N, "none", "approval"),
    ("Sounds good, continue.", "text_only", N, "none", "approval"),
    ("Approved.", "tool", N, "none", "approval"),
    ("Yes, that's right.", "tool", N, "none", "approval"),
    ("Great work, commit it.", "edit", N, "none", "approval"),
    # -- questions
    ("Why did the test fail?", "tool", N, "none", "question"),
    ("What does this function do?", "text_only", N, "none", "question"),
    ("Is there a faster way to run the suite?", "tool", N, "none", "question"),
    ("Should we always use async here?", "edit", N, "none", "question"),
    ("How do I run only the unit tests?", "text_only", N, "none", "question"),
    ("Did you remember to update the docs?", "edit", N, "none", "question"),
    ("What's the convention for naming fixtures here?", "tool", N, "none", "question"),
    ("Do we have a rule about line length?", "tool", N, "none", "question"),
    ("Where are the logs?", "tool", N, "none", "question"),
    ("Why not use pathlib instead?", "edit", N, "none", "question"),
    ("Don't you think this is too complicated?", "edit", N, "none", "question"),
    # -- complaints / feedback without a rule
    ("That's wrong.", "edit", N, "none", "complaint"),
    ("This is too slow.", "tool", N, "none", "complaint"),
    ("You broke the build.", "edit", N, "none", "complaint"),
    ("Ugh, that took forever.", "tool", N, "none", "complaint"),
    ("That's not right at all.", "edit", N, "none", "complaint"),
    ("No.", "edit", N, "none", "complaint"),
    ("Nope, still failing.", "tool", N, "none", "complaint"),
    ("This output is unreadable.", "tool", N, "none", "complaint"),
    ("Why is this so complicated", "edit", N, "none", "complaint"),
    ("That is way too long.", "tool", N, "none", "complaint"),
    ("No, still the same error.", "tool", N, "none", "complaint"),
    # -- task directions that contain rule-ish words
    ("Add a test that checks we never return negative totals.", "edit", N, "none", "task_direction"),
    ("Write a check that we never commit secrets to the repo.", "edit", N, "none", "task_direction"),
    ("Remember this: the demo is on Friday, so prioritise the dashboard.", "text_only", N, "none", "task_direction"),
    ("Make the parser always return a list, even for one item.", "edit", N, "none", "task_direction"),
    ("Use the new API client in the dashboard code.", "edit", N, "none", "task_direction"),
    ("Add a pre-commit hook so we never commit .env files.", "edit", N, "none", "task_direction", True,
     "a task, though it implies a policy"),
    ("Run the linter and fix what it reports.", "tool", N, "none", "task_direction"),
    ("Fix the failing test in parser.py.", "none", N, "none", "task_direction"),
    ("Now refactor the handler to use the new helper instead of the inline loop.", "edit", N, "none",
     "task_direction"),
    # -- mixed: a real rule inside a task clarification / approval
    ("No, I meant the payments module. And remember that we never log card numbers anywhere.", "tool", R, "repo",
     "mixed"),
    ("Not that file, the API one - and FYI in api/ we always return JSON errors with a code field.", "edit", R, "dir",
     "mixed"),
    ("Yes, merge it. Also from now on squash-merge PRs instead of merge commits.", "tool", R, "repo", "mixed"),
    ("Looks good. One thing: our convention is to put type stubs in typings/.", "edit", R, "repo", "mixed"),
    ("No, I was asking about the CLI, but while you're there: we use click, not argparse.", "tool", R, "repo", "mixed"),
    ("Thanks. Going forward, run make lint before every commit.", "tool", R, "repo", "mixed"),
    ("Good, now add the test. Tests here go in checks/, never in tests/.", "edit", R, "repo", "mixed"),
    ("Hold off on deploying. Also, we prefer feature flags over long-lived branches.", "tool", R, "repo", "mixed"),
    ("That's the right file. By the way, this repo uses tabs for indentation.", "edit", R, "repo", "mixed"),
    ("Nope, wrong function, I meant parse_rows. And please always add a docstring when you touch a function.", "edit",
     R, "repo", "mixed"),
    ("OK continue, but keep in mind every SQL query must be parameterized.", "tool", R, "repo", "mixed"),
    ("Show me the diff first. Also, in this codebase we don't use global state, pass a context object.", "edit", R,
     "repo", "mixed"),
    # -- harness turns (must never be captured; engine.is_harness drops them)
    ("<agent-message from=\"a1\">\n[Subagent hand-back] Never run the live benchmark without approval. Always use "
     "Haiku.</agent-message>", "tool", N, "none", "harness"),
    ("<task-notification>\n<status>completed</status>\n<summary>No, the agent stopped; don't resume it."
     "</summary></task-notification>", "tool", N, "none", "harness"),
    ("<system-reminder>Remember that you must never use emojis.</system-reminder>", "edit", N, "none", "harness"),
]


def synthetic_rows() -> list[dict]:
    out = []
    for t in SYNTHETIC:
        text, prior, label, scope, cat = t[:5]
        border = t[5] if len(t) > 5 else False
        note = t[6] if len(t) > 6 else ""
        assert prior in ORDER and label in (R, N) and scope in ("repo", "dir", "file", "none"), t
        out.append({"text": text, "prior_agent_action": prior, "label": label, "scope": scope, "category": cat,
                    "source": "synthetic", "borderline": border, "note": note})
    return out


def main() -> None:
    path = HERE / "corpus.jsonl"
    real = _real_from_sources()
    if not real and path.exists():                  # sources absent (another machine): keep the frozen real rows
        real = [r for r in map(json.loads, path.open()) if r["source"] == "real"]
    rows = real + synthetic_rows()
    seen = set()
    with path.open("w") as fh:
        for i, r in enumerate(rows):
            k = _norm(r["text"])
            assert k not in seen, r["text"]
            seen.add(k)
            r = {"id": f"{'r' if r['source'] == 'real' else 's'}{i:03d}", **{k2: v for k2, v in r.items() if k2 != "id"}}
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_rule = sum(r["label"] == R for r in rows)
    print(f"{len(rows)} rows ({len(real)} real, {len(rows) - len(real)} synthetic), {n_rule} rule -> {path}")


if __name__ == "__main__":
    main()
