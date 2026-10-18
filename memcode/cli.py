"""`python3 -m memcode <command>`: inspect and control the memory store.

  list [--all]        memories (stale hidden unless --all)
  show ID             one memory with provenance
  forget ID...        delete memories (and their retrievals / salience rows)
  add TEXT [--path P] record a manual memory (redacted, path confined to the repo)
  stats               counts by trigger, stale, retrievals, events
  sessions [-n N]     per-session counters: rules/notes injected, captured, repeated corrections
  why ID              salience score and the evidence behind it
  sync-rules [T...]   write the memory block into another agent's instruction file (default target: agents)
  setup AGENT         print the config that wires memcode into codex or gemini
  facts [--backfill [--force]]  facts: commands, repo, environment, inferences (backfill from the event log)
  fact set KEY VALUE | fact rm KEY   add or remove a fact by hand
  salience            shadow-mode scores per memory (logged each session start; not used for ranking)
  config [KEY on|off] show or set options (model-capture: opt-in model-based rule capture)
  export [FILE]       JSON dump (stdout if no FILE)
  prune-stale         delete all stale memories
  history [-n N]      what the memory agent (transcript capture) added, updated or retired, with the old text
  rescope             recompute every memory's scope; `list --scope DIR` lists memories scoped under DIR
  consolidate [--dry-run|--undo]  group redundant agent notes under one lesson (MEMCODE_CONSOLIDATE=1 does it
                      at session start and shows lessons instead of their notes)
  budget N [--dry-run]  evict down to N memories (MEMCODE_STORE_BUDGET=N does it at session start)
  label ID [+x] [-y]  show or edit a memory's topic labels; `list --label X` filters by label

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
    if n:
        from . import activity
        activity.note(con, "forgot", f"forgot {n} memor{'y' if n == 1 else 'ies'}", n)
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
    from . import activity
    activity.saved(con, "manual", a.text, rel)
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


def cmd_why(con, a) -> int:
    from . import salience
    r = con.execute("SELECT * FROM memories WHERE id=?", (a.id,)).fetchone()
    if not r:
        print(f"no memory #{a.id}", file=sys.stderr)
        return 1
    dims = salience.compute(con, r)
    print(f"#{r['id']} salience {salience.score(con, r):.2f}  "
          + "  ".join(f"{k} {v:.2f}" for k, v in dims.items()))
    print(salience.explain(con, r))
    return 0


def cmd_sync_rules(con, a, root) -> int:
    from . import engine, export_rules
    engine.session_start(con, root, "sync-rules", prepare_only=True)    # fresh map and staleness first
    for t, changed in export_rules.sync(con, root, a.targets or ["agents"]).items():
        rel = export_rules.TARGETS[t][0]
        print(f"{t}: {rel} {'updated' if changed else 'unchanged'}")
        if export_rules.TARGETS[t][1] == "block" and export_rules.tracked(root, rel):
            print(f"  note: {rel} is tracked by git, so this block is shared when you commit it; review it first "
                  f"(memcode share is the reviewed way to share memories)")
    return 0


def cmd_facts(con, a, root) -> int:
    from . import engine, facts
    if a.backfill:
        n = facts.backfill(con, root, force=a.force)
        print(f"backfilled from the event log: {n} fact updates")
    engine.session_start(con, root, "facts-cli", prepare_only=True)
    facts.scan_repo(con, root)
    facts.infer(con)
    rows = facts.list_facts(con)
    if not rows:
        print("no facts yet")
        return 0
    cat = None
    for r in rows:
        if r["category"] != cat:
            cat = r["category"]
            print(f"\n[{cat}]")
        stats = f"  runs {r['runs']} ok {r['ok']} fail {r['fail']}" if r["category"] in ("command", "env") else ""
        role = f"{r['role']}: " if r["role"] else ""
        print(f"  {role}{r['value']}  ({r['source']}){stats}")
    print("\nshown at session start:")
    for line in facts.lines(con):
        print("  " + line)
    return 0


def cmd_fact(con, a) -> int:
    from . import facts
    if a.action == "set":
        if not a.value:
            print("usage: memcode fact set KEY VALUE", file=sys.stderr)
            return 2
        print(f"set {facts.set_user(con, a.key, ' '.join(a.value))}")
        return 0
    n = facts.remove(con, a.key)
    print(f"removed {n}")
    return 0 if n else 1


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
    keys = {"model-capture": "model_capture", "retrieval": "retrieval", "hierarchy": "hierarchy",
            "transcript-capture": "transcript_capture"}
    if a.key is None:
        cfg = model_capture.read_config(root)
        print(f"model-capture: {'on' if model_capture.enabled(root) else 'off'}"
              f" (config {'on' if cfg.get('model_capture') else 'off'}; env MEMCODE_MODEL_CAPTURE overrides)")
        print(f"capture model: {os.environ.get('MEMCODE_CAPTURE_MODEL') or model_capture.DEFAULT_MODEL}")
        from . import retrieval
        print(f"retrieval: {'on' if retrieval.enabled(root) else 'off'}"
              f" (config {'on' if cfg.get('retrieval') else 'off'}; env MEMCODE_RETRIEVAL overrides)")
        from . import scope
        print(f"hierarchy: {'on' if scope.hier_enabled() else 'off'}"
              f" (config {'off' if cfg.get('hierarchy') is False else 'on'}; env MEMCODE_HIER overrides)")
        from . import transcript_capture
        print(f"transcript-capture: {'on' if transcript_capture.enabled(root) else 'off'}"
              f" (config {'off' if cfg.get('transcript_capture') is False else 'on'}; env MEMCODE_TRANSCRIPT_CAPTURE"
              " overrides; needs the claude CLI)")
        return 0
    if a.key not in keys or a.value not in ("on", "off"):
        print("usage: memcode config model-capture|retrieval|hierarchy|transcript-capture on|off", file=sys.stderr)
        return 2
    model_capture.write_config(root, **{keys[a.key]: a.value == "on"})
    print(f"{a.key}: {a.value}")
    if a.value == "on" and a.key == "transcript-capture":
        print("note: each finished turn's condensed, redacted transcript will be sent to the model via your `claude` login")
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


# --- scope (A) ---
def cmd_rescope(con, a, root) -> int:
    """`memcode rescope`: recompute every memory's scope (repo / dir / file / symbol) from its anchor and rule text."""
    from . import engine, scope
    engine.session_start(con, root, "rescope-cli", prepare_only=True)     # fresh `paths` first
    st = scope.rescope_all(con, root)
    print(f"rescoped {st['updated']} of {st['checked']} memories; now: "
          + (", ".join(f"{k} {v}" for k, v in sorted(st["kinds"].items())) or "none"))
    return 0


def cmd_list_scope(con, a) -> int:
    """`memcode list --scope DIR`: memories scoped at DIR or inside it (`--scope .` = repo-wide ones)."""
    from . import scope
    rows = scope.list_scoped(con, a.scope, include_stale=a.all)
    if not rows:
        print(f"no memories scoped under {scope.norm(a.scope) or '(repo)'}")
    for r in rows:
        flag = " [stale]" if r["stale"] else ""
        where = (r["scope_path"] or "/") + ("/" if r["scope_kind"] == "dir" else "")
        print(f"#{r['id']:<4} {r['trigger']:<9} {r['scope_kind']:<6} {where:<24} {r['text']}{flag}")
    return 0
# --- end scope (A) ---


def cmd_history(con, a) -> int:
    """`memcode history [-n N]`: what the memory agent (transcript capture) added, updated or retired."""
    from . import transcript_capture
    transcript_capture.ensure(con)
    rows = con.execute("SELECT * FROM memory_log ORDER BY id DESC LIMIT ?", (a.n,)).fetchall()
    if not rows:
        print("no memory-agent changes yet")
    for r in rows:
        before = json.loads(r["before"])["text"] if r["before"] else ""
        print(f"{_fmt_ts(r['ts'])}  {r['op']:<7} #{r['memory_id']}  {r['after'] or ''}")
        if before:
            print(f"{'':18}was: {before}")
        if r["evidence"]:
            print(f"{'':18}evidence: \"{r['evidence']}\"")
    return 0


# --- abstraction (B) ---
def cmd_consolidate(con, a) -> int:
    """`memcode consolidate [--dry-run | --undo]`: group redundant agent notes under one lesson each."""
    from . import consolidate
    if a.undo:
        print(f"removed {consolidate.undo(con)} lessons; their notes are top-level again")
        return 0
    st = consolidate.run(con, dry_run=a.dry_run)
    print(("would: " if a.dry_run else "") + f"{st['lessons']} lessons over {st['children']} notes "
          f"(created {st['created']}, updated {st['updated']}, dissolved {st['dissolved']}; "
          f"{st['candidates']} candidate notes)")
    if not consolidate.enabled():
        print("note: injection still shows the individual notes until MEMCODE_CONSOLIDATE=1")
    return 0


def cmd_budget(con, a) -> int:
    """`memcode budget N [--dry-run]`: evict down to N memories (user rules and lessons are kept)."""
    from . import budget
    st = budget.enforce(con, a.cap, time.time(), dry_run=a.dry_run)
    why = ", ".join(f"{k} {v}" for k, v in st["evicted"].items() if v) or "nothing"
    print(("would evict: " if a.dry_run else "evicted: ") + why + f"; {st['before']} -> {st['after']} memories"
          + (" (still over the cap: only protected memories left)" if st["over_cap"] else ""))
    return 0


def cmd_label(con, a) -> int:
    """`memcode label ID [+x] [-y]`: show or edit a memory's topic labels."""
    from . import labels
    if a.changes:
        labs = labels.edit(con, a.id, a.changes)
    else:
        r = con.execute("SELECT * FROM memories WHERE id=?", (a.id,)).fetchone()
        if r is None:
            raise ValueError(f"no memory #{a.id}")
        labs = labels.of(r)
    print(f"#{a.id}: " + (", ".join(labs) or "(no labels)"))
    return 0


def cmd_list_label(con, a) -> int:
    from . import labels
    rows = [r for r in store.list_memories(con, include_stale=a.all) if labels.has(r, a.label)]
    if not rows:
        print(f"no memories labelled {a.label}")
    for r in rows:
        flag = " [stale]" if r["stale"] else ""
        print(f"#{r['id']:<4} {r['trigger']:<9} {(r['anchor_path'] or '/'):<20} {r['text']}{flag}")
    return 0
# --- end abstraction (B) ---


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
    p = sub.add_parser("why"); p.add_argument("id", type=int)
    p = sub.add_parser("sync-rules"); p.add_argument("targets", nargs="*")
    p = sub.add_parser("setup"); p.add_argument("agent")
    p = sub.add_parser("facts"); p.add_argument("--backfill", action="store_true"); p.add_argument("--force", action="store_true")
    p = sub.add_parser("fact"); p.add_argument("action", choices=("set", "rm")); p.add_argument("key")
    p.add_argument("value", nargs="*")
    p = sub.add_parser("config"); p.add_argument("key", nargs="?"); p.add_argument("value", nargs="?")
    p = sub.add_parser("export"); p.add_argument("file", nargs="?")
    p = sub.add_parser("history", help="what the memory agent added, updated or retired"); p.add_argument("-n", type=int, default=20)
    sub.add_parser("prune-stale")
    # --- scope (A) ---
    sub.add_parser("rescope", help="recompute every memory's scope (repo/dir/file/symbol)")
    sub.choices["list"].add_argument("--scope", metavar="DIR", help="only memories scoped at DIR or inside it ('.' = repo)")
    # --- end scope (A) ---
    # --- abstraction (B) ---
    p = sub.add_parser("consolidate", help="group redundant agent notes under one lesson")
    p.add_argument("--dry-run", action="store_true"); p.add_argument("--undo", action="store_true")
    p = sub.add_parser("budget", help="evict down to N memories")
    p.add_argument("cap", type=int, metavar="N"); p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("label", help="show or edit a memory's labels: label ID +perf -style")
    p.add_argument("id", type=int); p.add_argument("changes", nargs=argparse.REMAINDER)
    sub.choices["list"].add_argument("--label", help="only memories with this topic label")
    # --- end abstraction (B) ---
    if not (sys.argv[1:] if argv is None else argv):
        ap.print_help()                         # bare `memcode` / `/memcode:cli`: show what is available
        return 0
    a = ap.parse_args(argv)
    if a.cmd == "setup":                       # needs no store
        from . import setup
        try:
            print(setup.render(a.agent))
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        return 0
    root = store.resolve_root(a.root)
    from . import scope
    scope.apply_config(root)
    con = store.connect(root)
    try:
        # --- scope (A) ---
        if a.cmd == "rescope":
            return cmd_rescope(con, a, root)
        if a.cmd == "list" and getattr(a, "scope", None) is not None:
            return cmd_list_scope(con, a)
        # --- end scope (A) ---
        # --- abstraction (B) ---
        if a.cmd in ("consolidate", "budget", "label"):
            return {"consolidate": cmd_consolidate, "budget": cmd_budget, "label": cmd_label}[a.cmd](con, a)
        if a.cmd == "list" and getattr(a, "label", None):
            return cmd_list_label(con, a)
        # --- end abstraction (B) ---
        if a.cmd == "add":
            return cmd_add(con, a, root)
        if a.cmd == "config":
            return cmd_config(con, a, root)
        if a.cmd == "facts":
            return cmd_facts(con, a, root)
        if a.cmd == "fact":
            return cmd_fact(con, a)
        if a.cmd == "sync-rules":
            return cmd_sync_rules(con, a, root)
        return {"list": cmd_list, "show": cmd_show, "forget": cmd_forget, "stats": cmd_stats,
                "export": cmd_export, "history": cmd_history, "sessions": cmd_sessions, "salience": cmd_salience, "why": cmd_why, "prune-stale": cmd_prune_stale}[a.cmd](con, a)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
