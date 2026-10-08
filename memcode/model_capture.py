"""Opt-in model-based rule capture.

The regex triggers miss rules stated in plain descriptive language ("we indent with tabs"). When
enabled, a user prompt that the triggers did not capture is queued, and a detached background worker
asks a model whether it states a standing convention for the codebase; if so the rule is stored like a
user correction. The hook never waits for the model.

Enable per repo with `python3 -m memcode config model-capture on` (writes .memcode/config.json) or with
MEMCODE_MODEL_CAPTURE=1. Model: MEMCODE_CAPTURE_MODEL (default claude-opus-5-5; e.g. claude-haiku-5-5 to
cut cost). The call goes through the `claude` CLI, so it uses the user's existing Claude Code login.

Privacy/cost: the (redacted) prompt text is sent to the model; each classified prompt is one call
(about $0.02 on Opus 5.5 measured; less on Haiku). Only prompts that pass `should_queue` are sent.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from . import store
from .redact import redact

DEFAULT_MODEL = "claude-opus-5-5"
SYSTEM = ("You read one message a developer sent to their coding agent. Decide whether it states a STANDING "
          "convention or rule for this codebase that should apply in future sessions (style, naming, tooling, "
          "structure, process), as opposed to a one-off task, a question, feedback on the current change, or "
          "chatter. If it does, restate the rule as one short imperative sentence. Reply via the schema.")
SCHEMA = json.dumps({"type": "object", "additionalProperties": False, "required": ["is_rule", "rule"],
                     "properties": {"is_rule": {"type": "boolean"}, "rule": {"type": "string"}}})
MIN_LEN, MAX_LEN = 12, 1500
MAX_ATTEMPTS = 2


def config_path(root) -> Path:
    return Path(root) / ".memcode" / "config.json"


def read_config(root) -> dict:
    try:
        return json.loads(config_path(root).read_text())
    except (OSError, ValueError):
        return {}


def write_config(root, **kv) -> dict:
    cfg = read_config(root)
    cfg.update(kv)
    p = config_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2) + "\n")
    return cfg


def enabled(root) -> bool:
    env = os.environ.get("MEMCODE_MODEL_CAPTURE", "").lower()
    if env in ("0", "false", "off"):
        return False
    return env in ("1", "true", "on") or bool(read_config(root).get("model_capture"))


def should_queue(con, session: str, text: str) -> bool:
    """Cheap gate so most prompts never reach the model."""
    t = " ".join((text or "").split())
    if not (MIN_LEN <= len(t) <= MAX_LEN) or t.endswith("?"):
        return False
    from .triggers import _CORRECTION, _STATEMENT, _STRONG
    if _CORRECTION.search(t) or _STATEMENT.search(t) or _STRONG.search(t):
        return False          # the pattern triggers own these (incl. repeats they dedupe on purpose)
    # Only after the agent has done something this session (same rule as the regex triggers).
    acted = con.execute("""SELECT 1 FROM events WHERE session=? AND kind='tool_use' AND
                           lower(json_extract(payload,'$.tool')) IN ('bash','edit','write','multiedit','notebookedit')
                           LIMIT 1""", (session,)).fetchone()
    return bool(acted)


def enqueue(con, session: str, text: str) -> int:
    cur = con.execute("INSERT INTO capture_queue(session, text, status, attempts, ts) VALUES(?,?,'pending',0,?)",
                      (session, redact(" ".join(text.split()))[:MAX_LEN], time.time()))
    con.commit()
    return cur.lastrowid


def spawn_worker(root: str) -> None:
    """Start a detached worker; it exits when the queue is empty. Never raises."""
    try:
        pkg_parent = str(Path(__file__).resolve().parent.parent)
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in (pkg_parent, os.environ.get("PYTHONPATH")) if p))
        subprocess.Popen([sys.executable, "-m", "memcode.model_capture", str(root)], env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
    except OSError:
        pass


def classify(text: str, model: str | None = None, timeout: int = 90) -> dict | None:
    """-> {"is_rule": bool, "rule": str} or None on any failure. Uses the `claude` CLI with no tools,
    no settings/plugins (so memcode cannot recurse), no session persistence and a budget cap."""
    model = model or os.environ.get("MEMCODE_CAPTURE_MODEL") or DEFAULT_MODEL
    cmd = ["claude", "-p", f"Message: {text}", "--model", model, "--effort", "low",
           "--setting-sources", "", "--strict-mcp-config", "--tools", "", "--no-session-persistence",
           "--session-id", str(uuid.uuid4()), "--max-budget-usd", "0.10", "--output-format", "json",
           "--system-prompt", SYSTEM, "--json-schema", SCHEMA]
    env = dict(os.environ, MEMCODE_DISABLE="1")
    try:
        with tempfile.TemporaryDirectory() as cwd:
            p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        out = json.loads(p.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    so = out.get("structured_output") if isinstance(out, dict) and not out.get("is_error") else None
    if not isinstance(so, dict) or not isinstance(so.get("is_rule"), bool) or not isinstance(so.get("rule"), str):
        return None
    return {"is_rule": so["is_rule"], "rule": so["rule"].strip(), "model": model}


def _claim(con):
    con.execute("BEGIN IMMEDIATE")
    row = con.execute("""SELECT id, session, text, attempts FROM capture_queue
                         WHERE status='pending' ORDER BY id LIMIT 1""").fetchone()
    if row:
        con.execute("UPDATE capture_queue SET status='working', attempts=attempts+1 WHERE id=?", (row[0],))
    con.commit()
    return row


def run_worker(root: str, classify_fn=classify) -> int:
    """Drain the queue. Returns the number of rules stored."""
    con = store.connect(root)
    stored = 0
    try:
        while True:
            row = _claim(con)
            if not row:
                return stored
            qid, sess, text, attempts = row
            res = classify_fn(text)
            if res is None:
                status = "pending" if attempts + 1 < MAX_ATTEMPTS else "error"
                con.execute("UPDATE capture_queue SET status=? WHERE id=?", (status, qid))
                con.commit()
                continue
            mid = None
            rule = " ".join(res["rule"].split())[:240]
            if res["is_rule"] and rule:
                body = redact(f"Rule from user correction: {rule}")
                dup = con.execute("SELECT id FROM memories WHERE trigger='correction' AND anchor_path='' AND text=?",
                                  (body,)).fetchone()
                if not dup:
                    mid = store.add_memory(con, "correction", body, "", None,
                                           {"session": sess, "source": "model", "model": res.get("model"),
                                            "ts": time.time()}, 0.6, commit=False)
                    store.bump(con, sess, "captured", commit=False)
                    stored += 1
            con.execute("UPDATE capture_queue SET status='done', result=?, memory_id=? WHERE id=?",
                        (json.dumps(res), mid, qid))
            con.commit()
    finally:
        con.close()


def pending(con) -> int:
    return con.execute("SELECT COUNT(*) FROM capture_queue WHERE status IN ('pending','working')").fetchone()[0]


if __name__ == "__main__":
    if os.environ.get("MEMCODE_DISABLE"):
        sys.exit(0)
    run_worker(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
