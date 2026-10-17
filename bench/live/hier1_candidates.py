"""Candidates for the hier1 set: does SCOPE HIERARCHY (MEMCODE_HIER: repo -> directory -> file) put the needed memory
in front of the agent where today's flat ranking does not, does it lose anything flat had, and what does it cost in
injected tokens?

One project ("shopfront"): six top-level areas with sub-directories (one three levels deep), 76 user rules (5 repo-wide,
the rest naming the directory they apply to, "Every new module under checkout/ ...") and 29 file notes. Every scenario
seeds the SAME store; scenarios differ only in the task (the later prompt) and in which memory the judged trap needs.
Today every captured rule is stored repo-wide (anchor_path=''), so flat ranking sees a rule's scope only through the
path it names (retrieval SCOPE_W, term overlap); the session-start block shows the newest MAX_RULES=20 rules, whatever
directory they name. With MEMCODE_HIER (impl-scope's semantics, bulletin 2026-10-16): rules get scope_path = the dir
they name (a named file maps to its dir); the start block lists only repo-scope rules; retrieval keeps repo memories
and memories on the scope chain of the prompt's paths (or named by it), gives each level ONE slot nearest first, then
fills the rest of TOP_K=5 by score.

Shapes (needed memory -> flat -> hier, predicted from the mechanism; the frozen PREDICTIONS come from the code):
  nearest_crowded          rule of the task's own dir (catalog/pricing/), sharing few task words; the parent's rules
                           share the task's domain words -> flat miss. Hier: one slot per level, then score -> miss too.
  parent_rule              rule of the PARENT dir (checkout/) while working in checkout/payments/ (six rules of its
                           own, all outranking it on path words) -> flat miss. Hier: parent level gets a slot, and the
                           needed rule is the newest of its three -> hit. (Sensitivity, offline only: as the oldest of
                           its level it would miss under hier too.)
  grandparent_rule         rule of insights/ while working in insights/dashboards/widgets/ -> flat miss; hier hit.
  repo_wide_old            repo-wide rule older than the newest 20 rules, no shared words -> flat miss (start-block
                           cap, no retrieval signal). Hier: start block lists only the 5 repo rules -> hit.
  repo_wide_recent         CONTROL: repo-wide rule among the newest 20 -> flat hit. Hier must keep it.
  two_dirs                 CONTROL: task names two dirs (the other one first); needed rule of the target's dir ->
                           flat hit (retrieval). Hier pools both chains -> should keep it.
  rule_names_sibling_file  CONTROL: a recent rule naming members/auth/sessions.py that applies to the modules reading
                           it; task creates members/auth/lockout.py -> flat hit (start block). Hier: scope = dir
                           members/auth -> must arrive by retrieval.
  no_path_in_prompt        CONTROL, where hier is most likely to LOSE: the prompt names no path or dir word ("the module
                           that defines CHANNELS"); needed rule of ops/alerts/, recent -> flat hit (start block). Hier:
                           not in the start block, not eligible at prompt time -> offline: NOT surfaced. Live depends on
                           the planned first-touch injection (rules of a dir injected when the agent first touches it);
                           extra_context() simulates it once a function exists (the agent reads channels.py first).
  file_note                CONTROL: note anchored to the target file (memory_add style), cut from the start block by
                           newer notes -> flat hit (anchor named in the prompt). Hier: file level comes first -> hit.

Design history (honesty): the set was designed from the posted PLAN; making the parent/grandparent needed rules the
newest of their level was decided from the plan's "allocate by level" wording (favourable to hier); two_dirs ties and
the no_path_in_prompt control were set after impl-scope described the exact allocation (no_path_in_prompt is
unfavourable to hier). The set is frozen before the implementation lands.

Arms (offline_check): "flat" = memcode defaults with retrieval on (MEMCODE_RETRIEVAL=1, MEMCODE_RANK unset = split);
"hier" = flat + HIER_ENV. Until the hierarchy code exists in the measured checkout, "hier" equals "flat" and every
result carries hier_flag_present=False so that is visible, never silently wrong. Everything the hierarchy feature adds
is reached through the ADAPTER section, so a renamed flag or function is a one-place change. HIER1_MEMCODE_SRC=<dir>
measures another checkout's memcode package (for example an exported copy of the merged branch).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
if os.environ.get("HIER1_MEMCODE_SRC"):          # compute predictions against another checkout's memcode (read-only)
    sys.path.insert(0, os.environ["HIER1_MEMCODE_SRC"])

DAY = 86400.0

# ---------------------------------------------------------------------------------------------- starter repo
# No file may reveal a convention a scenario judges (tests/test_hier_bench.py greps each scenario's key token).
FILES = {
    "README.md": "Shopfront service.\n",
    "catalog/__init__.py": "", "catalog/products.py": "PRODUCTS = {}\n",
    "catalog/pricing/__init__.py": "", "catalog/pricing/base.py": "BASE_PRICES = {}\n",
    "catalog/media/__init__.py": "", "catalog/media/images.py": "IMAGE_ROOT = 'media'\n",
    "checkout/__init__.py": "", "checkout/cart.py": "CART = {}\n",
    "checkout/payments/__init__.py": "", "checkout/payments/cards.py": "CARD_BRANDS = ('visa', 'mastercard')\n",
    "checkout/coupons/__init__.py": "", "checkout/coupons/codes.py": "CODES = {}\n",
    "fulfil/__init__.py": "", "fulfil/warehouses.py": "WAREHOUSES = ('ams', 'fra')\n",
    "fulfil/carriers/__init__.py": "",
    "fulfil/carriers/rates.py": "def quote(carrier, weight_g):\n    return {'carrier': carrier, 'weight_g': weight_g}\n",
    "fulfil/labels/__init__.py": "", "fulfil/labels/fonts.py": "FONTS = ('A', 'B')\n",
    "members/__init__.py": "", "members/directory.py": "MEMBERS = {}\n",
    "members/auth/__init__.py": "", "members/auth/sessions.py": "SESSIONS = {}\n",
    "members/profiles/__init__.py": "", "members/profiles/avatar.py": "AVATAR_SIZES = (32, 64, 128, 256)\n",
    "insights/__init__.py": "", "insights/store.py": "EVENTS = []\n",
    "insights/dashboards/__init__.py": "", "insights/dashboards/layout.py": "COLUMNS = 12\n",
    "insights/dashboards/widgets/__init__.py": "", "insights/dashboards/widgets/table.py": "ROW_LIMIT = 50\n",
    "ops/__init__.py": "", "ops/config.py": "ENV = 'prod'\n",
    "ops/jobs/__init__.py": "", "ops/jobs/schedule.py": "SCHEDULE = {}\n",
    "ops/alerts/__init__.py": "", "ops/alerts/channels.py": "CHANNELS = ('email', 'pager')\n",
}

# ---------------------------------------------------------------------------------------------- memories
# (scope, text, age in days). scope '' = repo-wide; 'dir/' = the directory the user named. The scope is ground truth
# for scoring relevance; how memcode stores it is up to the arm (see seed_store).
N = {  # the needed memories, by scenario
    "nearest": "Every new module under catalog/pricing/ defines a module-level constant EPOCH = 7.",
    "parent": "New modules under checkout/ end with the exact line '# owner: checkout-core'.",
    "grandparent": "Every new module under insights/ defines a module-level constant SCHEMA = 'ins-3'.",
    "repo_recent": "Every new Python module in this repo starts with the exact line '# shopfront: managed'.",
    "repo_old": "Every new Python module in this repo defines a module-level constant REVIEWED = False.",
    "two_dirs": "Every function in ops/jobs/ takes a parameter named run_id.",
    "file_note": ("Avatar templates find helpers in members/profiles/avatar.py only by the av_ name prefix; get_url "
                  "stayed invisible until it was renamed av_get_url."),
    "no_path": "Functions in ops/alerts/ are named with an alert_ prefix, for example alert_route.",
    "sibling_file": "Modules that read the session store in members/auth/sessions.py define AUDIT_TAG = 'auth' at module level.",
}
# Ground-truth scope of each needed memory where the text alone would mislead (the sibling-file rule names
# members/auth/sessions.py but applies to the modules that read it, i.e. to members/auth/).
TRUE_SCOPE = {N["sibling_file"]: "members/auth/"}

RULES = [
    ("", N["repo_recent"], 2.5),
    ("", N["repo_old"], 60),
    ("", "Use pathlib for filesystem paths in this repo, never os.path string joins.", 55),
    ("", "Never add third-party dependencies to this repo without asking first.", 50),
    ("", "Prefer small pure functions in this repo; keep I/O at the edges.", 45),

    ("catalog/", "Prices in catalog/ are integer cents; never store or return a float price.", 30),
    ("catalog/", "Quantities in catalog/ are validated as positive integers before any lookup.", 28),
    ("catalog/", "Names returned by catalog/ functions are lowercase ASCII strings.", 26),
    ("catalog/", "Functions in catalog/ that work on an order take it as their first argument.", 22),
    ("catalog/", "Modules in catalog/ keep no module-level mutable state.", 35),
    ("catalog/", "Public functions in catalog/ have a one-line docstring.", 33),
    ("catalog/pricing/", N["nearest"], 48),
    ("catalog/pricing/", "Tier boundaries in catalog/pricing/ live in module-level tuples, not literals inside functions.", 20),
    ("catalog/pricing/", "Functions in catalog/pricing/ return prices in integer cents and never round with float math.", 18),
    ("catalog/pricing/", "Functions in catalog/pricing/ raise ValueError for a negative quantity.", 16),
    ("catalog/media/", "Image paths in catalog/media/ are relative to IMAGE_ROOT.", 4.0),
    ("catalog/media/", "Thumbnails in catalog/media/ are generated lazily, never at import time.", 3.8),
    ("catalog/media/", "Functions in catalog/media/ accept bytes, never file objects.", 3.6),
    ("catalog/media/", "Image sizes in catalog/media/ are (width, height) tuples of ints.", 3.4),

    ("checkout/", "Functions in checkout/ never read the clock directly; they take now as a parameter.", 41),
    ("checkout/", "Modules in checkout/ import only from the standard library.", 38),
    ("checkout/", N["parent"], 27),
    ("checkout/payments/", "Amounts in checkout/payments/ are integer cents, never floats.", 15),
    ("checkout/payments/", "Functions in checkout/payments/ never log card numbers or wallet tokens.", 14),
    ("checkout/payments/", "Functions in checkout/payments/ take entries as an iterable and never mutate it.", 13),
    ("checkout/payments/", "Credit and debit kinds in checkout/payments/ are compared as lowercase strings.", 12),
    ("checkout/payments/", "Public functions in checkout/payments/ carry full type hints.", 11),
    ("checkout/payments/", "A balance computed in checkout/payments/ never goes negative silently; raise ValueError instead.", 10),
    ("checkout/coupons/", "Coupon codes in checkout/coupons/ are uppercase and 8 characters long.", 3.2),
    ("checkout/coupons/", "Discounts in checkout/coupons/ are whole percentages between 1 and 90.", 3.0),
    ("checkout/coupons/", "Functions in checkout/coupons/ return a new cart dict instead of modifying the one passed in.", 2.8),
    ("checkout/coupons/", "Expired coupons in checkout/coupons/ are rejected with ValueError('expired').", 2.6),

    ("fulfil/", "Weights in fulfil/ are integer grams.", 32),
    ("fulfil/", "Functions in fulfil/ take the warehouse code as a keyword argument.", 29),
    ("fulfil/", "Modules in fulfil/ keep no module-level mutable state.", 25),
    ("fulfil/", "Public functions in fulfil/ have a one-line docstring.", 21),
    ("fulfil/carriers/", "Carrier names in fulfil/carriers/ are lowercase slugs.", 19),
    ("fulfil/carriers/", "Functions in fulfil/carriers/ never call the network directly; they build request dicts.", 17),
    ("fulfil/carriers/", "Service levels in fulfil/carriers/ are the strings standard, express or freight.", 9),
    ("fulfil/labels/", "Label text in fulfil/labels/ is uppercase ASCII.", 8),
    ("fulfil/labels/", "Functions in fulfil/labels/ return str, never bytes.", 7),
    ("fulfil/labels/", "Label widths in fulfil/labels/ are measured in dots at 203 dpi.", 6),
    ("fulfil/labels/", "Functions in fulfil/labels/ accept address lines as a list of str.", 5),

    ("members/", "Member ids in members/ are strings, never ints.", 36),
    ("members/", "Functions in members/ never return password hashes.", 30.5),
    ("members/", "Modules in members/ keep no module-level mutable state.", 23),
    ("members/", "Public functions in members/ have a one-line docstring.", 19.5),
    ("members/auth/", "Tokens and codes in members/auth/ come from the secrets module, never random.", 2.2),
    ("members/auth/", "Functions in members/auth/ compare secrets with hmac.compare_digest.", 2.1),
    ("members/auth/", "Session lifetimes in members/auth/ are integers in seconds.", 1.9),
    ("members/auth/", "Functions in members/auth/ never log the code or token they create.", 1.8),
    ("members/auth/", N["sibling_file"], 3.1),
    ("members/profiles/", "Display names in members/profiles/ are trimmed and at most 40 characters.", 9.5),
    ("members/profiles/", "Functions in members/profiles/ return copies of profile dicts, never the stored dict.", 8.5),
    ("members/profiles/", "Avatar sizes in members/profiles/ are square pixel edges taken from AVATAR_SIZES.", 7.5),

    ("insights/", "Timestamps in insights/ are UTC epoch seconds as int.", 37),
    ("insights/", "Modules in insights/ import only from the standard library.", 32.5),
    ("insights/", N["grandparent"], 23.5),
    ("insights/dashboards/", "Layouts in insights/dashboards/ use a 12-column grid.", 14.5),
    ("insights/dashboards/", "Functions in insights/dashboards/ take width as an int number of columns.", 13.5),
    ("insights/dashboards/", "Functions in insights/dashboards/ return plain dicts that serialise to JSON.", 12.5),
    ("insights/dashboards/widgets/", "Widgets in insights/dashboards/widgets/ never return None; they return an empty list instead.", 11.5),
    ("insights/dashboards/widgets/", "Numbers scaled in insights/dashboards/widgets/ are rounded with round(), never truncated with int().", 10.5),
    ("insights/dashboards/widgets/", "Functions in insights/dashboards/widgets/ accept values as any iterable of numbers.", 9.8),

    ("ops/", "Functions in ops/ read settings from ops/config.py, never from environment variables.", 33.5),
    ("ops/", "Modules in ops/ log through the logging module, never print.", 26.5),
    ("ops/", "Scripts in ops/ exit with status 2 on bad arguments.", 20.5),
    ("ops/jobs/", N["two_dirs"], 8.8),
    ("ops/jobs/", "Jobs in ops/jobs/ are idempotent: a second run changes nothing.", 15.5),
    ("ops/jobs/", "Functions in ops/jobs/ log their start and end through the logging module.", 12),
    ("ops/alerts/", "Alert messages in ops/alerts/ are at most 120 characters.", 1.6),
    ("ops/alerts/", N["no_path"], 1.5),
    ("ops/alerts/", "Pager alerts in ops/alerts/ are only sent for severity 'critical'.", 1.4),
]

# (trigger, text, anchor file, age in days): notes anchored to one file, as memory_add / fail_to_fix / retry write them
NOTES = [
    ("manual", N["file_note"], "members/profiles/avatar.py", 40),
    ("manual", "AVATAR_SIZES must stay sorted ascending; the CDN picks the first size that fits.", "members/profiles/avatar.py", 12),
    ("retry", "Image tests flaked on a missing cache directory; create media/.cache before running them.", "catalog/media/images.py", 5),
    ("manual", "CART is shared by the web workers; copy it before changing it inside a request.", "checkout/cart.py", 18),
    ("fail_to_fix", "`python3 -m pytest -q tests/test_rates.py` failed and passed after editing fulfil/carriers/rates.py. "
                    "Fix was in fulfil/carriers/rates.py.", "fulfil/carriers/rates.py", 7),
    ("manual", "EVENTS grows without bound in long runs; batch jobs trim it.", "insights/store.py", 22),
    ("retry", "Editing SCHEDULE needed two tries because its keys must be cron strings.", "ops/jobs/schedule.py", 3),
    ("manual", "SESSIONS is keyed by member id string.", "members/auth/sessions.py", 26),
    ("fail_to_fix", "`python3 -m pytest -q` failed and passed after editing catalog/pricing/base.py. "
                    "Fix was in catalog/pricing/base.py.", "catalog/pricing/base.py", 9),
    ("manual", "COLUMNS must stay 12; the frontend grid is hard-coded to it.", "insights/dashboards/layout.py", 16),
    ("retry", "Font 'B' renders wider than 'A'; label widths were recomputed after switching fonts.", "fulfil/labels/fonts.py", 4),
    ("retry", "PRODUCTS loads lazily; the first lookup after a restart is slow, so warm it in tests.", "catalog/products.py", 11),
    ("manual", "BASE_PRICES is filled from the nightly feed; never edit it by hand.", "catalog/pricing/base.py", 21),
    ("fail_to_fix", "`python3 -m pytest -q tests/test_images.py` failed and passed after editing catalog/media/images.py. "
                    "Fix was in catalog/media/images.py.", "catalog/media/images.py", 6),
    ("manual", "CARD_BRANDS order is shown to users as-is; keep visa first.", "checkout/payments/cards.py", 19),
    ("retry", "CODES needed a reload after the coupon import script ran twice.", "checkout/coupons/codes.py", 8),
    ("fail_to_fix", "`python3 -m pytest -q tests/test_cart.py` failed and passed after editing checkout/cart.py. "
                    "Fix was in checkout/cart.py.", "checkout/cart.py", 13),
    ("manual", "WAREHOUSES codes match the carrier portal; ams and fra only for now.", "fulfil/warehouses.py", 24),
    ("retry", "The label preview needed two runs because FONTS was cached by the printer driver.", "fulfil/labels/fonts.py", 10),
    ("manual", "MEMBERS is rebuilt from the CRM export every hour.", "members/directory.py", 28),
    ("fail_to_fix", "`python3 -m pytest -q tests/test_sessions.py` failed and passed after editing members/auth/sessions.py. "
                    "Fix was in members/auth/sessions.py.", "members/auth/sessions.py", 15),
    ("retry", "Uploading a test avatar failed twice until the CDN sandbox token was refreshed.", "members/profiles/avatar.py", 17),
    ("fail_to_fix", "`python3 -m pytest -q tests/test_store.py` failed and passed after editing insights/store.py. "
                    "Fix was in insights/store.py.", "insights/store.py", 20),
    ("retry", "The dashboard snapshot test needed a second run after COLUMNS changed.", "insights/dashboards/layout.py", 9),
    ("manual", "ROW_LIMIT is also enforced by the API gateway; raising it here alone does nothing.", "insights/dashboards/widgets/table.py", 14),
    ("manual", "ENV is overwritten by the deploy script; tests must not depend on it.", "ops/config.py", 30),
    ("fail_to_fix", "`python3 -m pytest -q tests/test_schedule.py` failed and passed after editing ops/jobs/schedule.py. "
                    "Fix was in ops/jobs/schedule.py.", "ops/jobs/schedule.py", 2),
    ("retry", "Pager test alerts went to the real rota once; use the 'email' channel in tests.", "ops/alerts/channels.py", 2.5),
    ("manual", "quote() is also called by the partner API; keep its signature stable.", "fulfil/carriers/rates.py", 23),
]

# ---------------------------------------------------------------------------------------------- scenarios
# key: regex over INJECTED TEXT that shows the needed memory reached the agent (fallback when a feature re-renders lines)
SCENARIOS = [
    {"name": "h_pricing_epoch", "token": "EPOCH", "shape": "nearest_crowded", "needed": N["nearest"], "needed_scope": "catalog/pricing/",
     "later": ("Create catalog/pricing/tiers.py with a function tier_for(quantity) that returns the name of the price "
               "tier for an order quantity: 'single' below 10, 'pack' below 100, otherwise 'bulk'."),
     "trap_regex": r"\A(?!.*\bEPOCH\s*=\s*7\b)", "trap_on": "content", "trap_path": r"(^|/)catalog/pricing/tiers\.py$",
     "key": r"EPOCH = 7"},
    {"name": "h_checkout_footer", "token": "checkout-core", "shape": "parent_rule", "needed": N["parent"], "needed_scope": "checkout/",
     "later": ("Create checkout/payments/wallet.py with a function wallet_balance(entries) that returns the balance in "
               "cents of a list of wallet entries, each a dict with 'cents' and 'kind' ('credit' or 'debit')."),
     "trap_regex": r"\A(?!.*# owner: checkout-core\s*\Z)", "trap_on": "content",
     "trap_path": r"(^|/)checkout/payments/wallet\.py$", "key": r"# owner: checkout-core"},
    {"name": "h_insights_schema", "token": "ins-3", "shape": "grandparent_rule", "needed": N["grandparent"], "needed_scope": "insights/",
     "later": ("Create insights/dashboards/widgets/sparkline.py with a function sparkline(values, width) that scales a "
               "list of numbers to integer bar heights between 0 and width."),
     "trap_regex": r"\A(?!.*\bSCHEMA\s*=\s*[\"']ins-3[\"'])", "trap_on": "content",
     "trap_path": r"(^|/)insights/dashboards/widgets/sparkline\.py$", "key": r"SCHEMA = 'ins-3'"},
    {"name": "c_repo_header", "token": "shopfront: managed", "shape": "repo_wide_recent", "control": True, "needed": N["repo_recent"], "needed_scope": "",
     "later": ("Create members/auth/otp.py with a function make_code(digits) that returns a random numeric one-time "
               "code with the given number of digits."),
     "trap_regex": r"\A(?!# shopfront: managed)", "trap_on": "content", "trap_path": r"(^|/)members/auth/otp\.py$",
     "key": r"# shopfront: managed"},
    {"name": "h_repo_reviewed", "token": "REVIEWED", "shape": "repo_wide_old", "needed": N["repo_old"], "needed_scope": "",
     "later": ("Create fulfil/labels/zpl.py with a function label(lines) that returns a ZPL label string that prints "
               "each address line on its own row."),
     "trap_regex": r"\A(?!.*\bREVIEWED\s*=\s*False\b)", "trap_on": "content", "trap_path": r"(^|/)fulfil/labels/zpl\.py$",
     "key": r"REVIEWED = False"},
    {"name": "c_jobs_run_id", "token": "run_id", "shape": "two_dirs", "control": True, "needed": N["two_dirs"], "needed_scope": "ops/jobs/",
     "later": ("Using quote() from fulfil/carriers/rates.py, create ops/jobs/rate_refresh.py with a function "
               "refresh_rates(carriers, weight_g) that returns a list with one quote per carrier."),
     "trap_regex": r"def \w+\((?![^)]*\brun_id\b)", "trap_on": "content", "trap_path": r"(^|/)ops/jobs/rate_refresh\.py$",
     "key": r"run_id"},
    {"name": "c_auth_audit", "token": "AUDIT_TAG", "shape": "rule_names_sibling_file", "control": True, "needed": N["sibling_file"],
     "needed_scope": "members/auth/",
     "later": ("Create members/auth/lockout.py with a function is_locked(member_id, failures) that reads the member's "
               "session from the session store and says whether they are locked out after 5 failed logins."),
     "trap_regex": r"\A(?!.*\bAUDIT_TAG\s*=\s*[\"']auth[\"'])", "trap_on": "content",
     "trap_path": r"(^|/)members/auth/lockout\.py$", "key": r"AUDIT_TAG = 'auth'"},
    {"name": "c_alerts_prefix", "token": "alert_", "shape": "no_path_in_prompt", "control": True, "needed": N["no_path"],
     "needed_scope": "ops/alerts/",
     "later": ("A pager message needs a formatter: add a function to the module that defines CHANNELS which builds the "
               "message text from a severity and a description."),
     "trap_regex": r"def (?!alert_)\w+\(", "trap_on": "content", "trap_path": r"(^|/)ops/alerts/channels\.py$",
     "key": r"alert_ prefix", "first_touch": True},
    {"name": "c_avatar_prefix", "token": "av_", "shape": "file_note", "control": True, "needed": N["file_note"],
     "needed_scope": "members/profiles/avatar.py",
     "later": ("Add a function to members/profiles/avatar.py that returns the largest avatar size that is not above a "
               "given pixel limit."),
     "trap_regex": r"def (?!av_)\w+\(", "trap_on": "content", "trap_path": r"(^|/)members/profiles/avatar\.py$",
     "key": r"av_ name prefix"},
]


def target_path(sc: dict) -> str:
    """The file the task creates or edits (the trap judges only this file)."""
    m = re.search(r"\(\^\|/\)(.+)\$$", sc["trap_path"])
    return m.group(1).replace("\\.", ".")


def in_chain(scope: str, path: str) -> bool:
    """Ground truth: does a memory scoped to `scope` apply to `path`? ('' = repo-wide, 'd/' = directory, else file)."""
    if scope == "":
        return True
    if scope.endswith("/"):
        return path.startswith(scope)
    return path == scope


def history(sc: dict | None = None) -> list[dict]:
    """Every memory in the store, as one list: {kind, trigger, text, scope, anchor, age, needed}."""
    needed = sc["needed"] if sc else None
    out = [{"kind": "rule", "trigger": "correction", "text": t, "scope": TRUE_SCOPE.get(t, s), "anchor": "", "age": a,
            "needed": t == needed} for s, t, a in RULES]
    out += [{"kind": "note", "trigger": g, "text": t, "scope": f, "anchor": f, "age": a, "needed": t == needed}
            for g, t, f, a in NOTES]
    return out


def relevant(sc: dict) -> list[dict]:
    """The memories that apply to the task's target file (repo-wide, its directory chain, the file itself)."""
    p = target_path(sc)
    return [h for h in sc.get("history") or history(sc) if in_chain(h["scope"], p)]


def oracle_all(sc: dict) -> str:
    """All memories that apply to the target file, in the prompt (the oracle pilot: traps must then be ~0)."""
    rel = relevant(sc)
    rules = " ".join(h["text"] for h in rel if h["kind"] == "rule")
    notes = " ".join(h["text"] for h in rel if h["kind"] == "note")
    return "Project rules: " + rules + (f" Notes: {notes}" if notes else "")


# ---------------------------------------------------------------------------------------------- ADAPTER
# Everything the hierarchy feature adds is reached through this section. Update here once impl-scope posts the final
# names on the bulletin; nothing else in this file needs to change.
HIER_ENV = {"MEMCODE_HIER": "1"}
FLAT_ENV = {"MEMCODE_RETRIEVAL": "1", "MEMCODE_HIER": "0"}   # hierarchy is on by default since 0.8.0


def hier_flag_present() -> bool:
    """True when the memcode being measured implements the hierarchy (memcode.scope exists and the flag is read), so
    the 'hier' arm can differ from 'flat'. False means hier == flat by construction: report it, do not score it."""
    try:
        import memcode
        src = Path(memcode.__file__).resolve().parent
    except ImportError:
        return False
    flag = next(iter(HIER_ENV))
    return (src / "scope.py").is_file() and any(flag in p.read_text(errors="replace") for p in src.glob("*.py"))


def memcode_source() -> str:
    """Which memcode checkout is being measured (for the report)."""
    import memcode
    return str(Path(memcode.__file__).resolve().parent)


def scope_of(con, mid: int) -> str | None:
    """scope_path the store gave a memory (None before the schema has the column)."""
    try:
        r = con.execute("SELECT scope_path FROM memories WHERE id=?", (mid,)).fetchone()
    except Exception:          # noqa: BLE001  (old schema)
        return None
    return r[0] if r else None


FIRST_TOUCH = (("engine", "first_touch"), ("scope", "first_touch"), ("engine", "file_context"),
               ("scope", "file_context"), ("scope", "touch_context"))


def first_touch_fn():
    """The planned first-touch injection (rules of a dir injected when the agent first Reads/Edits a file in it), if
    the measured memcode has one. Called as f(con, root, session, rel_path) -> context text."""
    rfp = _optional("scope", "rules_for_path")           # landed name: (con, session, path, root) -> (text, ids)
    if rfp:
        return lambda con, root, session, rel: rfp(con, session, rel, root)[0]
    return next((f for f in (_optional(m, n) for m, n in FIRST_TOUCH) if f), None)


def extra_context(con, root: str, session: str, sc: dict) -> str:
    """Text a NEW injection point adds when the agent first touches the target file (simulated: the agent reads or
    writes exactly the target file after the prompt). '' when the measured memcode has no such point. Counted
    separately (extra_tokens) and reported apart from prompt-time surfacing. Only meaningful on the hier arm; it is
    called on both arms so a flag-off no-op is visible too."""
    f = first_touch_fn()
    return (f(con, root, session, target_path(sc)) or "") if f else ""


def _optional(mod: str, fn: str):
    try:
        m = __import__(f"memcode.{mod}", fromlist=[fn])
    except ImportError:
        return None
    return getattr(m, fn, None)


# ---------------------------------------------------------------------------------------------- seeding
def seed_store(repo: Path, sc: dict, now: float | None = None) -> int:
    """Seed .memcode with the shared history (ages relative to now), exactly as capture writes memories today: user
    rules as trigger 'correction', anchor '' ; notes anchored to their file with its content hash. Scope is NOT set
    here: engine.session_start -> maintenance.run -> scope.rescope_new assigns it (both arms), as it would for a store
    captured before the upgrade. Returns the needed memory's id."""
    from memcode import store
    now = time.time() if now is None else now
    con = store.connect(repo)
    nid = None
    try:
        for h in sc.get("history") or history(sc):
            ts = now - h["age"] * DAY
            if h["kind"] == "rule":
                mid = store.add_memory(con, "correction", f"Rule from user correction: {h['text']}", "", None,
                                       {"source": "seed"}, 0.7, commit=False)
            else:
                f = repo / h["anchor"]
                ah = store.sha1(f.read_bytes()) if f.is_file() else None
                mid = store.add_memory(con, h["trigger"], h["text"], h["anchor"], ah, {"source": "seed"}, 0.6,
                                       commit=False)
            con.execute("UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (ts, ts, mid))
            if h["needed"]:
                nid = mid
        con.commit()
    finally:
        con.close()
    return nid


def write_files(repo: Path, sc: dict) -> None:
    for n, c in (sc.get("files") or FILES).items():
        (repo / n).parent.mkdir(parents=True, exist_ok=True)
        (repo / n).write_text(c)


# ---------------------------------------------------------------------------------------------- offline check
def _with_env(env: dict):
    """Context: strip every inherited MEMCODE_* variable, set exactly `env` (as run.py does per arm), restore after."""
    class _Ctx:
        def __enter__(self):
            self.old = {k: v for k, v in os.environ.items() if k.startswith("MEMCODE_")}
            for k in self.old:
                del os.environ[k]
            os.environ.update(env)

        def __exit__(self, *a):
            for k in [k for k in os.environ if k.startswith("MEMCODE_")]:
                del os.environ[k]
            os.environ.update(self.old)
    return _Ctx()


def measure(sc: dict, env: dict, session: str = "hier1-later") -> dict:
    """Run the real hook path in-process on a freshly seeded store: engine.session_start (pinned block, recorded in
    injections), engine.prompt for the later prompt (retrieval, recorded), plus any extra injection point. Returns what
    reached the agent and what it cost."""
    from memcode import engine, store
    from memcode.pinned import TOKEN_DIVISOR
    d = Path(tempfile.mkdtemp(prefix="hier1-"))
    try:
        with _with_env(env):
            write_files(d, sc)
            nid = seed_store(d, sc)
            con = store.connect(d)
            try:
                pinned_text = engine.session_start(con, str(d), session)
                needed_scope = scope_of(con, nid)
                pinned_ids = {r[0] for r in con.execute(
                    "SELECT memory_id FROM injections WHERE session=? AND source='pinned'", (session,))}
                ctx = engine.prompt(con, str(d), session, sc["later"])
                prompt_ids = {r[0] for r in con.execute(
                    "SELECT memory_id FROM injections WHERE session=? AND source!='pinned'", (session,))}
                extra = extra_context(con, str(d), session, sc)
                touch_ids = {r[0] for r in con.execute(
                    "SELECT memory_id FROM injections WHERE session=? AND source!='pinned'", (session,))} - prompt_ids
                rows = {r["id"]: dict(r) for r in con.execute("SELECT id, text FROM memories")}
            finally:
                con.close()
    finally:
        shutil.rmtree(d, ignore_errors=True)
    hist = sc.get("history") or history(sc)
    text_to_h = {h["text"]: h for h in hist}
    p = target_path(sc)

    def h_of(mid):
        t = rows[mid]["text"].replace("Rule from user correction: ", "", 1)
        return text_to_h.get(t)

    shown = pinned_ids | prompt_ids | touch_ids
    rel_shown = sum(1 for i in shown if h_of(i) and in_chain(h_of(i)["scope"], p))
    all_text = "\n".join((pinned_text, ctx, extra))
    key = re.compile(re.escape(sc["key"]) if not sc["key"].startswith("re:") else sc["key"][3:])
    return {
        "needed_pinned": nid in pinned_ids,
        "needed_retrieved": nid in prompt_ids,
        "needed_first_touch": nid in touch_ids or bool(extra and key.search(extra)),
        "surfaced_at_prompt": nid in pinned_ids | prompt_ids or bool(key.search(pinned_text + "\n" + ctx)),
        "surfaced_by_id": nid in shown,
        "surfaced_by_text": bool(key.search(all_text)),
        "first_touch_present": first_touch_fn() is not None,
        "pinned_tokens": round(len(pinned_text) / TOKEN_DIVISOR),
        "retrieval_tokens": round(len(ctx) / TOKEN_DIVISOR),
        "extra_tokens": round(len(extra) / TOKEN_DIVISOR),
        "total_tokens": round(len(pinned_text + ctx + extra) / TOKEN_DIVISOR),
        "shown": len(shown), "shown_relevant": rel_shown, "shown_irrelevant": len(shown) - rel_shown,
        "relevant_total": len(relevant(sc)), "retrieved": len(prompt_ids),
        "needed_scope_path": needed_scope,
    }


def flat_rank(sc: dict) -> dict:
    """Diagnostics for the flat arm: the needed memory's retrieval rank among all scored memories, and how many
    scored memories are relevant (in the target's scope chain) vs not."""
    from memcode import engine, retrieval, store
    d = Path(tempfile.mkdtemp(prefix="hier1-"))
    try:
        with _with_env(FLAT_ENV):
            write_files(d, sc)
            nid = seed_store(d, sc)
            con = store.connect(d)
            try:
                engine.session_start(con, str(d), "s")
                scored = retrieval.score(con, str(d), "s", sc["later"])
                p = target_path(sc)
                text_to_h = {h["text"]: h for h in (sc.get("history") or history(sc))}
                scope = lambda r: text_to_h[r["text"].replace("Rule from user correction: ", "", 1)]["scope"]
                return {"rank": next((i for i, (_, r) in enumerate(scored) if r["id"] == nid), None),
                        "scored": len(scored),
                        "scored_relevant": sum(1 for _, r in scored if in_chain(scope(r), p)),
                        "top": [(round(s, 2), scope(r) or "(repo)") for s, r in scored[:8]]}
            finally:
                con.close()
    finally:
        shutil.rmtree(d, ignore_errors=True)


def offline_check(sc: dict) -> dict:
    """Deterministic per-arm prediction: does the needed memory reach the agent, and at what token cost?"""
    out = {"shape": sc["shape"], "control": bool(sc.get("control")), "hier_flag_present": hier_flag_present()}
    for arm, env in (("flat", dict(FLAT_ENV)), ("hier", dict(FLAT_ENV, **HIER_ENV))):
        for k, v in measure(sc, env).items():
            out[f"{arm}_{k}"] = v
        out[f"{arm}_surfaced"] = out[f"{arm}_surfaced_by_id"] or out[f"{arm}_surfaced_by_text"]
    return out


# ---------------------------------------------------------------------------------------------- pilots and freezing
def pilot_pool() -> list[dict]:
    """Scenarios in the shape bench/live/pilot.one expects (files, later, trap_*, oracle with ALL relevant memories)."""
    return [dict(sc, files=dict(FILES), oracle=oracle_all(sc)) for sc in SCENARIOS]


def freeze(sc: dict) -> dict:
    """Self-contained scenario for the frozen set: files and the whole seeded history spelled out."""
    return dict(sc, files=dict(FILES), history=history(sc), set="hier1", tuned_on=False)


if __name__ == "__main__":
    print(f"memcode under test: {memcode_source()}  hier flag present: {hier_flag_present()}")
    for sc in SCENARIOS:
        o = offline_check(sc)
        print(f"{sc['name']:18s} {sc['shape']:24s} flat={o['flat_surfaced']!s:5s} (pin={o['flat_needed_pinned']!s:5s} "
              f"ret={o['flat_needed_retrieved']!s:5s}) hier={o['hier_surfaced']!s:5s} (pin={o['hier_needed_pinned']!s:5s} "
              f"ret={o['hier_needed_retrieved']!s:5s} touch={o['hier_needed_first_touch']!s:5s}) tokens flat/hier={o['flat_total_tokens']}/{o['hier_total_tokens']} "
              f"shown rel/irrel flat {o['flat_shown_relevant']}/{o['flat_shown_irrelevant']} "
              f"hier {o['hier_shown_relevant']}/{o['hier_shown_irrelevant']} of {o['flat_relevant_total']} relevant")
        if "-v" in sys.argv:
            print("   ", json.dumps(flat_rank(sc)))
