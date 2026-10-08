"""`python3 -m memcode <command>`: inspect and control the memory store.

  list [--all]        memories (stale hidden unless --all)
  show ID             one memory with provenance
  forget ID...        delete memories (and their retrievals / salience rows)
  add TEXT [--path P] record a manual memory (redacted, path confined to the repo)
  stats               counts by trigger, stale, retrievals, events
  sessions [-n N]     per-session counters: rules/notes injected, captured, repeated corrections
  salience            shadow-mode scores per memory (logged each session start; not used for ranking)
  config [KEY on|off] show or set options (model-capture: opt-in model-based rule capture)
  export [FILE]       JSON dump (stdout if no FILE)
  prune-stale         delete all stale memories

Root resolution matches the hooks (CLAUDE_PROJECT_DIR, else git toplevel, else cwd).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import store
from .mcp_server import safe_rel
from .redact import redact


def _fmt_ts(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def cmd_list(con, a) -> int:
    rows = store.list_memories(con, include_stale=a.all)
    if not rows:
        print("no memories")
    for r in rows:
        flag = " [stale]" if r["stale"] else ""
        anchor = (r["anchor_path"] or "/") + (f"::{r['anchor_symbol']}" if r["anchor_symbol"] else "")
        print(f"#{r['id']:<4} {r['trigger']:<9} {anchor:<20} {r['text']}{flag}")
    return 0


def cmd_show(con, a) -> int:
    r = con.execute("SELECT * FROM memories WHERE id=?", (a.id,)).fetchone()
    if not r:
        print(f"no memory #{a.id}", file=sys.stderr)
        return 1
    n = con.execute("SELECT COUNT(*) FROM retrievals WHERE memory_id=?", (a.id,)).fetchone()[0]
    print(f"#{r['id']} [{r['trigger']}] confidence={r['confidence']:.2f} stale={bool(r['stale'])} retrievals={n}")
    where = r["anchor_path"] or "(repo-wide)"
    if r["anchor_symbol"]:
        where += f"::{r['anchor_symbol']}"
    print(f"anchor: {where}  hash: {r['anchor_hash'] or '-'}")
    print(f"created {_fmt_ts(r['created_at'])}, updated {_fmt_ts(r['updated_at'])}")
    print(f"provenance: {r['provenance']}")
    outs = con.execute("SELECT outcome, COUNT(*) FROM outcomes WHERE memory_id=? GROUP BY outcome", (a.id,)).fetchall()
    if outs:
        print("outcomes: " + ", ".join(f"{o} x{n}" for o, n in outs))
    print(f"\n{r['text']}")
    return 0


def _delete(con, ids: list[int]) -> int:
    n = 0
    for i in ids:
        for t in ("retrievals", "salience_log"):
            con.execute(f"DELETE FROM {t} WHERE memory_id=?", (i,))
        n += con.execute("DELETE FROM memories WHERE id=?", (i,)).rowcount
    con.commit()
    return n


def cmd_forget(con, a) -> int:
    n = _delete(con, a.ids)
    print(f"forgot {n} of {len(a.ids)}")
    return 0 if n == len(a.ids) else 1


def cmd_prune_stale(con, a) -> int:
    ids = [r[0] for r in con.execute("SELECT id FROM memories WHERE stale=1")]
    print(f"pruned {_delete(con, ids)} stale memories")
    return 0


def cmd_add(con, a, root: str) -> int:
    rel = safe_rel(root, a.path or "")
    h = None
    f = os.path.join(os.path.realpath(root), rel) if rel else None
    if f and os.path.isfile(f):
        with open(f, "rb") as fh:
            h = store.sha1(fh.read())
    mid = store.add_memory(con, "manual", redact(a.text.strip())[:2000], redact(rel), h, {"source": "cli"}, confidence=0.6)
    print(f"stored memory #{mid}")
    return 0


def cmd_stats(con, a) -> int:
    by = con.execute("SELECT trigger, COUNT(*), SUM(stale) FROM memories GROUP BY trigger ORDER BY 2 DESC").fetchall()
    total = sum(r[1] for r in by)
    print(f"memories: {total} ({sum(r[2] or 0 for r in by)} stale)")
    for t, n, st in by:
        print(f"  {t:<10} {n:>4}  ({st or 0} stale)")
    one = lambda q: con.execute(q).fetchone()[0]
    q = dict(con.execute("SELECT status, COUNT(*) FROM capture_queue GROUP BY status").fetchall())
    if q:
        print("model capture queue: " + ", ".join(f"{k} {v}" for k, v in sorted(q.items())))
    rep = one("SELECT COALESCE(SUM(repeated_corrections),0) FROM session_stats")
    print(f"repeated corrections: {rep}")
    print(f"retrievals: {one('SELECT COUNT(*) FROM retrievals')}  events: {one('SELECT COUNT(*) FROM events')}  "
          f"paths: {one('SELECT COUNT(*) FROM paths')}")
    return 0


def cmd_sessions(con, a) -> int:
    rows = con.execute("SELECT * FROM session_stats ORDER BY started_at DESC LIMIT ?", (a.n,)).fetchall()
    if not rows:
        print("no sessions recorded yet")
        return 0
    print(f"{'session':<10} {'started':<16} {'rules':>5} {'notes':>5} {'captured':>8} {'repeated':>8}")
    for r in rows:
        print(f"{r['session'][:8]:<10} {_fmt_ts(r['started_at']):<16} {r['rules_injected']:>5} "
              f"{r['notes_injected']:>5} {r['captured']:>8} {r['repeated_corrections']:>8}")
    t = con.execute("SELECT SUM(captured), SUM(repeated_corrections), COUNT(*) FROM session_stats").fetchone()
    print(f"\n{t[2]} sessions: {t[0] or 0} memories captured, {t[1] or 0} corrections repeated "
          f"(a repeated correction means a stored rule did not stick)")
    return 0


def cmd_salience(con, a) -> int:
    rows = con.execute("""SELECT m.id, m.trigger, m.text,
          (SELECT COUNT(*) FROM injections i WHERE i.memory_id=m.id) AS shown,
          (SELECT COUNT(*) FROM outcomes o WHERE o.memory_id=m.id AND o.outcome LIKE 'success%') AS ok,
          (SELECT COUNT(*) FROM outcomes o WHERE o.memory_id=m.id AND o.outcome LIKE 'failure%') AS bad,
          s.surprise, s.friction, s.fragility, s.confidence,
          (SELECT COUNT(*) FROM salience_log x WHERE x.memory_id=m.id) AS samples
        FROM memories m LEFT JOIN salience_log s ON s.id=(SELECT MAX(id) FROM salience_log WHERE memory_id=m.id)
        WHERE m.stale=0 ORDER BY m.id""").fetchall()
    if not rows:
        print("no memories")
        return 0
    print(f"{'id':<4} {'trigger':<10} {'shown':>5} {'ok':>3} {'bad':>3} {'samples':>7} {'surp':>5} {'fric':>5} {'frag':>5} {'conf':>5}  text")
    for r in rows:
        f = lambda v: f"{v:.2f}" if v is not None else "  - "
        print(f"{r['id']:<4} {r['trigger']:<10} {r['shown']:>5} {r['ok']:>3} {r['bad']:>3} {r['samples']:>7} {f(r['surprise']):>5} "
              f"{f(r['friction']):>5} {f(r['fragility']):>5} {f(r['confidence']):>5}  {r['text'][:50]}")
    return 0


def cmd_config(con, a, root: str) -> int:
    from . import model_capture
    keys = {"model-capture": "model_capture", "retrieval": "retrieval"}
    if a.key is None:
        cfg = model_capture.read_config(root)
        print(f"model-capture: {'on' if model_capture.enabled(root) else 'off'}"
              f" (config {'on' if cfg.get('model_capture') else 'off'}; env MEMCODE_MODEL_CAPTURE overrides)")
        print(f"capture model: {os.environ.get('MEMCODE_CAPTURE_MODEL') or model_capture.DEFAULT_MODEL}")
        from . import retrieval
        print(f"retrieval: {'on' if retrieval.enabled(root) else 'off'}"
              f" (config {'on' if cfg.get('retrieval') else 'off'}; env MEMCODE_RETRIEVAL overrides)")
        return 0
    if a.key not in keys or a.value not in ("on", "off"):
        print("usage: memcode config model-capture|retrieval on|off", file=sys.stderr)
        return 2
    model_capture.write_config(root, **{keys[a.key]: a.value == "on"})
    print(f"{a.key}: {a.value}")
    if a.value == "on" and a.key == "model-capture":
        print("note: prompts the pattern triggers miss will be sent (redacted) to the model via your `claude` login")
    return 0


def cmd_export(con, a) -> int:
    rows = [dict(r) for r in store.list_memories(con, include_stale=True)]
    for r in rows:
        r["provenance"] = json.loads(r["provenance"] or "{}")
    out = json.dumps(rows, indent=2)
    if a.file:
        with open(a.file, "w") as fh:
            fh.write(out + "\n")
        print(f"exported {len(rows)} memories to {a.file}")
    else:
        print(out)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="memcode", description="Inspect and control the memcode store.")
    ap.add_argument("--root", help="repo root (default: CLAUDE_PROJECT_DIR / git toplevel / cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("--all", action="store_true")
    p = sub.add_parser("show"); p.add_argument("id", type=int)
    p = sub.add_parser("forget"); p.add_argument("ids", type=int, nargs="+")
    p = sub.add_parser("add"); p.add_argument("text"); p.add_argument("--path")
    sub.add_parser("stats")
    p = sub.add_parser("sessions"); p.add_argument("-n", type=int, default=10)
    sub.add_parser("salience")
    p = sub.add_parser("config"); p.add_argument("key", nargs="?"); p.add_argument("value", nargs="?")
    p = sub.add_parser("export"); p.add_argument("file", nargs="?")
    sub.add_parser("prune-stale")
    a = ap.parse_args(argv)
    root = store.resolve_root(a.root)
    con = store.connect(root)
    try:
        if a.cmd == "add":
            return cmd_add(con, a, root)
        if a.cmd == "config":
            return cmd_config(con, a, root)
        return {"list": cmd_list, "show": cmd_show, "forget": cmd_forget, "stats": cmd_stats,
                "export": cmd_export, "sessions": cmd_sessions, "salience": cmd_salience, "prune-stale": cmd_prune_stale}[a.cmd](con, a)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
