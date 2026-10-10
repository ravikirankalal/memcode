"""Gate 2b candidates (salience2): a NEW set for the split ranking (MEMCODE_RANK=split), which was designed after
salience1 and therefore cannot be judged on it.

Fresh directories and conventions, and history shapes salience1 did not have, chosen to stress split ranking:
  costly          needed rule is the oldest of seven and was restated twice (the salience1 shape, new content)
  costly_once     needed rule restated only ONCE (decayed weight < PROMOTE_MIN): split cannot promote it
  costly_crowded  needed rule restated twice, but three other relevant rules were restated too, all competing for
                  split's two extra slots
  costly_wide     nine relevant rules; needed rule restated three times
  control         needed rule is cheap and mid-aged; three competitors restated
  control_heavy   needed rule is cheap and mid-aged; FOUR competitors restated
  control_newest  needed rule is the newest of seven; two competitors restated
Seeding, distractors and offline_check are shared with salience1 (each scenario spells out its `history`).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from bench.live import salience1_candidates as s1   # noqa: E402
from bench.live.pressure import REPO                # noqa: E402

FILES = dict(REPO, **{
    "inventory/__init__.py": "", "inventory/stock.py": "STOCK = {}\n",
    "notify/__init__.py": "", "notify/email.py": "def send(to, body):\n    return (to, body)\n",
    "payments/__init__.py": "", "payments/charge.py": "def charge(amount_cents, card, idempotency_key):\n    return {'ok': True}\n",
    "shipping/__init__.py": "", "shipping/rates.py": "def ship_flat_rate():\n    return 500\n",
    "export/__init__.py": "", "export/csv_out.py": "import csv\n",
    "auth/__init__.py": "", "auth/session.py": "SESSIONS = {}\n",
    "geo/__init__.py": "", "geo/points.py": "def point(lat, lon):\n    return (lat, lon)\n",
})

TEMPLATES = [
    "Functions in {d}/ carry full type hints on parameters and return values.",
    "Public functions in {d}/ have a one-line docstring.",
    "Modules in {d}/ keep no module-level mutable state.",
    "Functions in {d}/ never print; they return values or raise.",
    "Functions in {d}/ stay under 40 lines; split helpers out instead.",
    "Errors in {d}/ are raised as ValueError with a message naming the bad argument.",
    "Functions in {d}/ do not mutate their arguments.",
    "Modules in {d}/ import only from the standard library.",
]

BASE = [
    {"name": "t_inventory_owner", "kind": "costly", "dir": "inventory",
     "target": "Every new module under inventory/ defines a module-level constant OWNER = \"team-stock\".",
     "later": "Create inventory/restock.py with a function needs_restock(item, threshold) that says whether an item is below its threshold.",
     "trap_regex": r"\A(?!.*OWNER\s*=\s*[\"']team-stock[\"'])", "trap_on": "content", "trap_path": r"(^|/)inventory/restock\.py$",
     "oracle": "Rule: every new module under inventory/ defines a module-level constant OWNER = \"team-stock\"."},
    {"name": "t_notify_header", "kind": "costly_once", "dir": "notify",
     "target": "Every new module under notify/ starts with the exact line '# owner: notify-team'.",
     "later": "Create notify/sms.py with a function send_sms(number, text) that returns a message record.",
     "trap_regex": r"\A(?!# owner: notify-team)", "trap_on": "content", "trap_path": r"(^|/)notify/sms\.py$",
     "oracle": "Rule: every new module under notify/ starts with the exact line '# owner: notify-team'."},
    {"name": "t_payments_idem", "kind": "costly_crowded", "dir": "payments",
     "target": "Every function in payments/ takes a parameter named idempotency_key.",
     "later": "Add a function to payments/charge.py that refunds part of a charge.",
     "trap_regex": r"def \w+\((?![^)]*idempotency_key)", "trap_on": "content", "trap_path": r"(^|/)payments/charge\.py$",
     "oracle": "Rule: every function in payments/ takes a parameter named idempotency_key."},
    {"name": "t_auth_footer", "kind": "costly_wide", "dir": "auth",
     "target": "New modules under auth/ end with the exact line '# reviewed-by: security'.",
     "later": "Create auth/tokens.py with a function make_token(user_id) that returns a random token string.",
     "trap_regex": r"\A(?!.*# reviewed-by: security\s*\Z)", "trap_on": "content", "trap_path": r"(^|/)auth/tokens\.py$",
     "oracle": "Rule: new modules under auth/ end with the exact line '# reviewed-by: security'."},
    {"name": "t_shipping_prefix", "kind": "control", "dir": "shipping",
     "target": "Functions defined in shipping/ are named with a ship_ prefix, for example ship_flat_rate.",
     "later": "Add a function to shipping/rates.py that computes the shipping cost from a parcel's weight in grams.",
     "trap_regex": r"def (?!ship_)\w+\(", "trap_on": "content", "trap_path": r"(^|/)shipping/rates\.py$",
     "oracle": "Rule: functions defined in shipping/ are named with a ship_ prefix, e.g. ship_by_weight."},
    {"name": "t_geo_srid", "kind": "control_heavy", "dir": "geo",
     "target": "Every new module under geo/ defines a module-level constant SRID = 4326.",
     "later": "Create geo/distance.py with a function haversine(a, b) that returns the distance in metres between two points.",
     "trap_regex": r"\A(?!.*SRID\s*=\s*4326\b)", "trap_on": "content", "trap_path": r"(^|/)geo/distance\.py$",
     "oracle": "Rule: every new module under geo/ defines a module-level constant SRID = 4326."},
    {"name": "t_export_version", "kind": "control_newest", "dir": "export",
     "target": "Every new module under export/ defines __version__ = '1' at module level.",
     "later": "Create export/json_out.py with a function to_json(rows) that serialises a list of dicts.",
     "trap_regex": r"\A(?!.*__version__\s*=\s*[\"']1[\"'])", "trap_on": "content", "trap_path": r"(^|/)export/json_out\.py$",
     "oracle": "Rule: every new module under export/ defines __version__ = '1' at module level."},
]


def _h(text, age, repeats=(), needed=False):
    return {"text": text, "age": age, "repeats": list(repeats), "needed": needed}


def history(sc: dict) -> list[dict]:
    d, kind, tgt = sc["dir"], sc["kind"], sc["target"]
    comp = [t.format(d=d) for t in TEMPLATES]
    if kind == "costly":            # oldest, restated 21 and 5 days ago
        return [_h(tgt, 50, (21, 5), True)] + [_h(c, a) for c, a in zip(comp, (33, 26, 19, 11, 7, 3))]
    if kind == "costly_once":       # oldest, restated once 6 days ago (decayed weight ~0.74)
        return [_h(tgt, 40, (6,), True)] + [_h(c, a) for c, a in zip(comp, (30, 24, 17, 12, 6, 2))]
    if kind == "costly_crowded":    # needed + three other restated rules, all older than the four cheap ones
        return ([_h(tgt, 44, (20, 9), True)]
                + [_h(c, a, r) for c, a, r in zip(comp[:3], (40, 37, 35), ((15, 4), (18, 3), (12, 2)))]
                + [_h(c, a) for c, a in zip(comp[3:6], (10, 6, 2))])
    if kind == "costly_wide":       # nine relevant, needed restated three times
        return [_h(tgt, 60, (30, 14, 4), True)] + [_h(c, a) for c, a in zip(comp, (45, 38, 29, 22, 15, 9, 5, 1))]
    if kind == "control":           # needed cheap, mid-aged; the three oldest competitors restated
        return ([_h(tgt, 11, (), True)]
                + [_h(c, a, (20, 6)) for c, a in zip(comp[:3], (34, 28, 21))]
                + [_h(c, a) for c, a in zip(comp[3:6], (14, 7, 3))])
    if kind == "control_newest":    # needed is the newest; two competitors restated
        return ([_h(tgt, 3.5, (), True)]          # newest of the seven, still older than the distractor rules
                + [_h(c, a, (16, 5)) for c, a in zip(comp[:2], (30, 25))]
                + [_h(c, a) for c, a in zip(comp[2:6], (20, 14, 8, 4))])
    if kind == "control_heavy":     # needed cheap, mid-aged; FOUR competitors restated
        return ([_h(tgt, 9, (), True)]
                + [_h(c, a, (19, 5)) for c, a in zip(comp[:4], (36, 30, 24, 16))]
                + [_h(c, a) for c, a in zip(comp[4:6], (6, 2))])
    raise ValueError(kind)


CANDIDATES = [dict(b, files=dict(FILES), history=history(b), n_rules=s1.N_RULES, n_notes=s1.N_NOTES, tuned_on=False)
              for b in BASE]


def oracle_all(sc: dict) -> str:
    return "Project rules: " + " ".join(h["text"] for h in sc["history"])


if __name__ == "__main__":
    for sc in CANDIDATES:
        o = s1.offline_check(sc)
        print(f"{sc['name']:20s} {sc['kind']:15s} recency={o['relevance_surfaced']!s:5s} "
              f"salience={o['salience_surfaced']!s:5s} split={o['split_surfaced']!s:5s} "
              f"ranks r/s/sp={o['relevance_rank']}/{o['salience_rank']}/{o['split_rank']} injected_split={o['split_injected']}")
