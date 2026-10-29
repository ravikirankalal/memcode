"""`python3 -m memcode.agent ROOT [--bootstrap]`: the detached worker the hooks start (agent.worker.spawn_worker);
with --bootstrap it reads the repository once instead (agent/bootstrap.py)."""
import os
import sys

from .worker import run_worker

if not os.environ.get("MEMCODE_DISABLE"):       # set by memcode's own model calls: never recurse
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    if "--bootstrap" in sys.argv[2:]:
        from .bootstrap import run
        run(root)
    else:
        run_worker(root)
