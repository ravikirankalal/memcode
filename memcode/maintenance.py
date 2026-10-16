"""Session-start maintenance for hierarchical memory (scope, labels, consolidation, storage budget).

Called by engine.session_start inside its error guard. Each step lives in its own module, owned by one implementer:
  scope.rescope_new(con, root)      give new / default-scoped memories their scope (repo, dir, file, symbol)
  labels.backfill(con)              label memories that have no labels yet (display and filtering only)
  consolidate.run_if_enabled(con)   MEMCODE_CONSOLIDATE=1: group redundant notes under one lesson
  budget.enforce_if_enabled(con)    MEMCODE_STORE_BUDGET=N: merge-before-evict down to N live memories
A module or function that does not exist yet is skipped, so the pieces can land independently.
"""
from __future__ import annotations

import importlib

STEPS = (("scope", "rescope_new", True), ("labels", "backfill", False),
         ("consolidate", "run_if_enabled", False), ("budget", "enforce_if_enabled", False))


def run(con, root: str) -> dict:
    done = {}
    for module, func, wants_root in STEPS:
        try:
            mod = importlib.import_module(f"{__package__}.{module}")
        except ImportError:
            continue
        fn = getattr(mod, func, None)
        if fn is None:
            continue
        done[f"{module}.{func}"] = fn(con, root) if wants_root else fn(con)
    return done
