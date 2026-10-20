"""`python3 -m memcode.agent ROOT`: the detached worker the Stop hook starts (agent.worker.spawn_worker)."""
import os
import sys

from .worker import run_worker

if not os.environ.get("MEMCODE_DISABLE"):       # set by memcode's own model calls: never recurse
    run_worker(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
