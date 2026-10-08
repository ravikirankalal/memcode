"""Labeled accuracy check for opt-in model capture (memcode/model_capture.classify). Real model calls.

  python3 bench/live/capture_eval.py [--model claude-opus-5-5] [--workers 6]

Messages are written to pass the cheap prefilter (statements, not questions, no regex-trigger phrasing)
and to be distinct from the frozen benchmark sets. Label True = a standing convention for the codebase."""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from memcode import model_capture as mc  # noqa: E402

LABELED = [
    # standing conventions, stated descriptively
    ("We keep all SQL in the queries/ directory, not inline in Python.", True),
    ("Around here functions that return booleans start with is_ or has_.", True),
    ("Our test files sit next to the code they test, named like foo_test.py.", True),
    ("This project formats with black at line length 100.", True),
    ("Config values come from settings.py; nobody reads environment variables directly.", True),
    ("We log with structlog in this service, so plain logging calls look out of place.", True),
    ("Public functions in this package get a docstring with an Example section.", True),
    ("Migrations are written by hand here, autogenerate makes a mess of our schema.", True),
    ("Branch names follow the pattern feature/<ticket-id>-short-description.", True),
    ("The team writes commit messages in the imperative mood, under 60 characters.", True),
    ("In this codebase dates are stored as UTC ISO strings, never naive datetimes.", True),
    ("Error messages shown to users are kept in messages.py so they can be translated.", True),
    # not standing conventions
    ("Rename the variable x to total in the second loop.", False),
    ("That fixed the failing test, thanks.", False),
    ("The CI server is down for maintenance this afternoon.", False),
    ("I'm going to lunch, carry on with the refactor.", False),
    ("Add a unit test for the empty-list case in parse_items.", False),
    ("This function is too long, split it into two.", False),
    ("Looks like the build is green again.", False),
    ("Bump the version to 1.4.2 for this release.", False),
    ("Maria will review the PR tomorrow morning.", False),
    ("Move the helper into utils.py for now.", False),
    ("I like how the new error handling reads.", False),
    ("Revert the change to the README, I'll handle docs separately.", False),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    with cf.ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(lambda m: mc.classify(m[0], model=a.model), LABELED))
    tp = fp = fn = tn = fail = 0
    for (msg, want), r in zip(LABELED, res):
        if r is None:
            fail += 1; print(f"  CALL FAILED  {msg}"); continue
        got = r["is_rule"]
        tp += got and want; fp += got and not want; fn += want and not got; tn += not got and not want
        mark = "ok " if got == want else "ERR"
        print(f"  {mark} want={want!s:5} got={got!s:5} {msg[:58]:58}  -> {r['rule'][:50]}")
    n = len(LABELED) - fail
    print(f"\nmodel {(res[0] or {}).get('model')}: {n} classified, {fail} failed calls")
    print(f"precision {tp}/{tp + fp}  recall {tp}/{tp + fn}  accuracy {(tp + tn)}/{n}")


if __name__ == "__main__":
    main()
