"""The memory agent: a model that reads the coding agent's session as it happens and keeps the repository's memory.

The pattern triggers (triggers.py) and facts (facts.py) see single events. The memory agent reads the whole turn: after
each one, the Stop hook queues the session log and a detached worker reads the new part, piece by piece, asking a model
to collect candidates of every kind (user rules, workflows, pitfalls, environment behaviour, design, decisions about
ongoing work), rate them, and propose add / update / retire operations against the memory as it stands. memcode keeps
only what passes the checks, best-rated first.

  transcript.py   reading the session log (condense, cut into pieces)
  model.py        the role prompt, output schema, briefing and model call
  checks.py       what a proposal must pass before it is stored
  curate.py       applying operations; decisions (subjects, expiry); memory_log
  conversation.py its running conversation per coding session: opened at SessionStart, resumed each turn
  worker.py       the queue, per-session budget, worker loop and health
  db.py           the agent's tables

On by default since 0.9.0; off with `memcode config memory-agent off` or MEMCODE_TRANSCRIPT_CAPTURE=0, and wherever the
`claude` CLI is missing. Model: MEMCODE_CAPTURE_MODEL (default claude-haiku-5-5). The condensed session log goes to the
model through the user's own `claude` login, the provider the coding agent already sent it to.
"""
from .curate import decision_days, decisions_enabled  # noqa: F401
from .model import DEFAULT_MODEL  # noqa: F401
from .conversation import start as start_session  # noqa: F401
from .worker import enabled, enqueue, health, spawn_worker  # noqa: F401
