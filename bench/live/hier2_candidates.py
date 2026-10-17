"""Candidates for the hier2 set: an UNTUNED confirmation of the scope hierarchy (hier1 was tuned on in Run 14b).

Same question and machinery as hier1 (bench/live/hier1_candidates.py: seeding, offline check, pilots), a different
project ("clinic": appointment booking, patients, billing, staff rota, reports, lab results), different rules, notes,
phrasing and traps. Written after Run 14b and frozen before any live run of the hier arms on it.

Shapes (needed memory -> flat -> hier, as for hier1):
  nearest_crowded        rule of the task's own dir (booking/slots/), old; booking/ rules share the task's words
  parent_rule            rule of billing/ while working in billing/claims/ (six claims rules of its own)
  grandparent_rule       rule of patients/ while working in patients/records/exports/
  repo_wide_old          repo-wide rule older than the newest 20 rules, no shared words with the task
  repo_wide_recent       CONTROL: repo-wide rule among the newest 20
  two_dirs               CONTROL: the task names another dir first; needed rule of the target dir
  edit_named_file        CONTROL (new): the task EDITS an existing file it names; needed rule of that file's dir
  no_path_in_prompt      CONTROL: the prompt names no path ("the module that defines REMINDER_HOURS"); recent rule
  file_note              CONTROL: note anchored to the file the task edits, named in the prompt
Arms (live, bench/live/hier1_gate.py --set hier2): flat / hier as in hier1, plus the two arms the DEFAULT question
needs, since per-prompt retrieval is off by default: default (0.7.0 defaults: no retrieval, no hier) and
hier_noret (MEMCODE_HIER=1, retrieval off: start block unsplit, first-touch injection and first-write refusal only).
"""
from __future__ import annotations

from bench.live import hier1_candidates as _H

FILES = {
    "README.md": "Clinic scheduling service.\n",
    "booking/__init__.py": "", "booking/calendar.py": "OPENING_HOURS = (8, 18)\n",
    "booking/slots/__init__.py": "", "booking/slots/grid.py": "SLOT_MINUTES = 15\n",
    "booking/reminders/__init__.py": "", "booking/reminders/timing.py": "REMINDER_HOURS = (48, 2)\n",
    "patients/__init__.py": "",
    "patients/directory.py": "def normalise(name):\n    return ' '.join(name.split()).title()\n",
    "patients/records/__init__.py": "", "patients/records/fields.py": "FIELDS = ('name', 'dob', 'allergies')\n",
    "patients/records/exports/__init__.py": "", "patients/records/exports/formats.py": "FORMATS = ('csv', 'json')\n",
    "billing/__init__.py": "", "billing/tariffs.py": "TARIFFS = {}\n",
    "billing/claims/__init__.py": "", "billing/claims/insurers.py": "INSURERS = ('aok', 'tk')\n",
    "billing/invoices/__init__.py": "", "billing/invoices/numbering.py": "PREFIX = 'INV'\n",
    "staff/__init__.py": "", "staff/roles.py": "ROLES = ('doctor', 'nurse', 'reception')\n",
    "staff/rota/__init__.py": "", "staff/rota/shifts.py": "SHIFT_LENGTHS = (4, 8, 12)\n",
    "reports/__init__.py": "", "reports/periods.py": "PERIODS = ('week', 'month')\n",
    "reports/charts/__init__.py": "",
    "reports/charts/bars.py": "BAR_WIDTH = 20\n\n\ndef chart_scale(values, width=BAR_WIDTH):\n"
                              "    top = max(values) or 1\n    return [round(v * width / top) for v in values]\n",
    "lab/__init__.py": "", "lab/panels.py": "PANELS = ('blood', 'urine')\n",
    "lab/results/__init__.py": "", "lab/results/units.py": "UNITS = {'glucose': 'mmol/L'}\n",
}

N = {
    "nearest": "Every new module under booking/slots/ defines a module-level constant SLOT_VERSION = 4.",
    "parent": "New modules under billing/ end with the exact line '# ledger: audited'.",
    "grandparent": "Every new module under patients/ defines a module-level constant PHI = True.",
    "repo_old": "Every new Python module in this repo defines a module-level constant LICENSE_ID = 'clinic-7'.",
    "repo_recent": "Every new Python module in this repo starts with the exact line '# clinic: generated'.",
    "two_dirs": "Every function in lab/results/ takes a keyword-only argument named lab_code.",
    "edit_named": "Every function added to reports/charts/ takes a keyword-only argument max_bars (None means no cap).",
    "no_path": "Functions in booking/reminders/ are named with a remind_ prefix, for example remind_text.",
    "file_note": ("The payroll export only picks up functions in staff/rota/shifts.py whose names end in _hours; "
                  "night_total was skipped until it was renamed night_hours."),
}

RULES = [
    ("", N["repo_recent"], 1.5),
    ("", N["repo_old"], 58),
    ("", "Use dataclasses for records passed between modules in this repo, not bare tuples.", 54),
    ("", "Never print patient data in this repo; log ids only.", 52),
    ("", "Keep functions in this repo under 40 lines; split longer ones.", 49),
    ("", "Dates in this repo are datetime.date objects, never strings.", 44),

    ("booking/", "Appointment slots in booking/ are (start, end) pairs in minutes since midnight.", 31),
    ("booking/", "Functions in booking/ that take a slot validate that start is before end.", 29),
    ("booking/", "Times in booking/ never cross midnight; reject a slot that would.", 27),
    ("booking/", "Functions in booking/ return new slot tuples instead of mutating lists passed in.", 24),
    ("booking/", "Public functions in booking/ have a one-line docstring.", 36),
    ("booking/slots/", N["nearest"], 47),
    ("booking/slots/", "Slot lengths in booking/slots/ are multiples of SLOT_MINUTES.", 19),
    ("booking/slots/", "Functions in booking/slots/ treat touching slots (end == start) as not overlapping.", 17),
    ("booking/reminders/", "Reminder texts in booking/reminders/ are at most 160 characters.", 1.3),
    ("booking/reminders/", N["no_path"], 1.2),
    ("booking/reminders/", "Reminders in booking/reminders/ are never sent for cancelled appointments.", 1.1),

    ("patients/", N["grandparent"], 25),
    ("patients/", "Patient ids in patients/ are strings of 8 digits.", 39),
    ("patients/", "Functions in patients/ never return allergies as None; use an empty tuple.", 34),
    ("patients/", "Modules in patients/ import only from the standard library.", 30),
    ("patients/records/", "Record fields in patients/records/ follow the order in FIELDS.", 16),
    ("patients/records/", "Functions in patients/records/ take the record as a dict and never mutate it.", 15),
    ("patients/records/", "Dates of birth in patients/records/ are ISO strings only at the export boundary.", 14),
    ("patients/records/exports/", "Exports in patients/records/exports/ write a header row first.", 13),
    ("patients/records/exports/", "Exports in patients/records/exports/ use the csv module, never manual string joins.", 12),
    ("patients/records/exports/", "Export functions in patients/records/exports/ return str and never write files themselves.", 11),
    ("patients/records/exports/", "Columns in patients/records/exports/ exclude allergies unless include_allergies=True.", 10),

    ("billing/", "Amounts in billing/ are integer cents.", 42),
    ("billing/", "Functions in billing/ round half up when converting from percentages.", 37),
    ("billing/", N["parent"], 26),
    ("billing/claims/", "Claims in billing/claims/ carry the insurer code in lowercase.", 9.5),
    ("billing/claims/", "Functions in billing/claims/ reject a claim with zero line items by raising ValueError.", 9),
    ("billing/claims/", "Claim totals in billing/claims/ are the sum of line items in cents, never recomputed from tariffs.", 8.5),
    ("billing/claims/", "Functions in billing/claims/ accept line items as an iterable of dicts with 'code' and 'cents'.", 8),
    ("billing/claims/", "Public functions in billing/claims/ carry full type hints.", 7.5),
    ("billing/claims/", "Claim ids in billing/claims/ are built as INSURER-YYYYMMDD-N.", 7),
    ("billing/invoices/", "Invoice numbers in billing/invoices/ start with PREFIX and are zero-padded to 6 digits.", 3.5),
    ("billing/invoices/", "Functions in billing/invoices/ never reuse a cancelled invoice number.", 3.3),
    ("billing/invoices/", "Invoice dates in billing/invoices/ are the treatment date, not today.", 3.1),

    ("staff/", "Staff ids in staff/ are strings, never ints.", 33),
    ("staff/", "Functions in staff/ never expose home addresses.", 28),
    ("staff/", "Public functions in staff/ have a one-line docstring.", 22),
    ("staff/rota/", "Shift lengths in staff/rota/ come from SHIFT_LENGTHS.", 6.5),
    ("staff/rota/", "Functions in staff/rota/ take the week start as a datetime.date keyword argument.", 6),
    ("staff/rota/", "Rotas in staff/rota/ never give one person two shifts in 11 hours.", 5.5),

    ("reports/", "Report periods in reports/ come from PERIODS.", 32),
    ("reports/", "Functions in reports/ return plain dicts or lists that serialise to JSON.", 23.5),
    ("reports/", "Modules in reports/ keep no module-level mutable state.", 21),
    ("reports/charts/", N["edit_named"], 4.5),
    ("reports/charts/", "Bar widths in reports/charts/ are ints between 1 and BAR_WIDTH.", 4.3),
    ("reports/charts/", "Functions in reports/charts/ accept values as any iterable of numbers.", 4.1),

    ("lab/", "Lab panel names in lab/ come from PANELS.", 35),
    ("lab/", "Functions in lab/ never round measured values; they keep the instrument's precision.", 20),
    ("lab/results/", N["two_dirs"], 2.4),
    ("lab/results/", "Results in lab/results/ carry their unit from UNITS.", 2.3),
    ("lab/results/", "Flags in lab/results/ are the strings 'low', 'normal' or 'high'.", 2.2),
    ("lab/results/", "Reference ranges in lab/results/ are (low, high) tuples of floats.", 2.1),
]

NOTES = [
    ("manual", N["file_note"], "staff/rota/shifts.py", 38),
    ("manual", "SHIFT_LENGTHS order is shown in the rota UI; keep 4 first.", "staff/rota/shifts.py", 12),
    ("retry", "Rota tests flaked on daylight-saving weeks; pin the week start in tests.", "staff/rota/shifts.py", 5),
    ("manual", "OPENING_HOURS is overridden per site by the deploy config.", "booking/calendar.py", 18),
    ("fail_to_fix", "`python3 -m pytest -q tests/test_grid.py` failed and passed after editing booking/slots/grid.py. "
                    "Fix was in booking/slots/grid.py.", "booking/slots/grid.py", 7),
    ("manual", "REMINDER_HOURS is read by the SMS gateway at startup; restart it after changes.", "booking/reminders/timing.py", 21),
    ("retry", "The patient import needed two runs because names had trailing tabs.", "patients/directory.py", 3),
    ("manual", "FIELDS order matches the paper intake form.", "patients/records/fields.py", 26),
    ("fail_to_fix", "`python3 -m pytest -q tests/test_formats.py` failed and passed after editing "
                    "patients/records/exports/formats.py. Fix was in patients/records/exports/formats.py.",
     "patients/records/exports/formats.py", 9),
    ("manual", "TARIFFS is loaded from the yearly fee schedule; never edit it by hand.", "billing/tariffs.py", 16),
    ("retry", "Insurer codes needed a reload after the portal renamed tk.", "billing/claims/insurers.py", 4),
    ("manual", "PREFIX is printed on paper invoices; changing it needs the accountant's sign-off.", "billing/invoices/numbering.py", 11),
    ("manual", "ROLES order drives the staff list sort.", "staff/roles.py", 24),
    ("fail_to_fix", "`python3 -m pytest -q tests/test_periods.py` failed and passed after editing reports/periods.py. "
                    "Fix was in reports/periods.py.", "reports/periods.py", 13),
    ("retry", "The chart snapshot test needed a second run after BAR_WIDTH changed.", "reports/charts/bars.py", 8),
    ("manual", "PANELS mirrors the lab's order form; add panels there first.", "lab/panels.py", 28),
    ("fail_to_fix", "`python3 -m pytest -q tests/test_units.py` failed and passed after editing lab/results/units.py. "
                    "Fix was in lab/results/units.py.", "lab/results/units.py", 2),
    ("manual", "UNITS uses SI units only; the US site converts on display.", "lab/results/units.py", 15),
    ("retry", "Calendar export failed twice until the ICS line length was capped at 75.", "booking/calendar.py", 10),
    ("manual", "normalise() is also used by the insurer import; keep its behaviour stable.", "patients/directory.py", 30),
    ("fail_to_fix", "`python3 -m pytest -q tests/test_shifts.py` failed and passed after editing staff/rota/shifts.py. "
                    "Fix was in staff/rota/shifts.py.", "staff/rota/shifts.py", 14),
    ("retry", "Reminder timing tests need a frozen clock; two runs failed at the hour boundary.", "booking/reminders/timing.py", 6),
]


def history(sc: dict | None = None) -> list[dict]:
    needed = sc["needed"] if sc else None
    out = [{"kind": "rule", "trigger": "correction", "text": t, "scope": s, "anchor": "", "age": a,
            "needed": t == needed} for s, t, a in RULES]
    out += [{"kind": "note", "trigger": g, "text": t, "scope": f, "anchor": f, "age": a, "needed": t == needed}
            for g, t, f, a in NOTES]
    return out


_SCENARIOS = [
    {"name": "h2_slots_version", "token": "SLOT_VERSION", "shape": "nearest_crowded", "needed": N["nearest"],
     "needed_scope": "booking/slots/",
     "later": ("Create booking/slots/overlap.py with a function overlaps(a, b) that says whether two appointment "
               "slots, each a (start, end) pair in minutes, overlap."),
     "trap_regex": r"\A(?!.*\bSLOT_VERSION\s*=\s*4\b)", "trap_on": "content",
     "trap_path": r"(^|/)booking/slots/overlap\.py$", "key": r"SLOT_VERSION = 4"},
    {"name": "h2_claims_ledger", "token": "ledger: audited", "shape": "parent_rule", "needed": N["parent"],
     "needed_scope": "billing/",
     "later": ("Create billing/claims/batch.py with a function batch_total(claims) that returns the total in cents of a "
               "list of claims, each a dict with a 'lines' list of {'code', 'cents'} dicts."),
     "trap_regex": r"\A(?!.*# ledger: audited\s*\Z)", "trap_on": "content",
     "trap_path": r"(^|/)billing/claims/batch\.py$", "key": r"# ledger: audited"},
    {"name": "h2_exports_phi", "token": "PHI", "shape": "grandparent_rule", "needed": N["grandparent"],
     "needed_scope": "patients/",
     "later": ("Create patients/records/exports/summary.py with a function summary_line(record) that returns one "
               "line of text with a patient's name and date of birth from a record dict."),
     "trap_regex": r"\A(?!.*\bPHI\s*=\s*True\b)", "trap_on": "content",
     "trap_path": r"(^|/)patients/records/exports/summary\.py$", "key": r"PHI = True"},
    {"name": "h2_repo_license", "token": "LICENSE_ID", "shape": "repo_wide_old", "needed": N["repo_old"],
     "needed_scope": "",
     "later": ("Create billing/invoices/totals.py with a function invoice_total(lines) that adds up the cents of a "
               "list of invoice lines and applies an optional percentage discount."),
     "trap_regex": r"\A(?!.*\bLICENSE_ID\s*=\s*[\"']clinic-7[\"'])", "trap_on": "content",
     "trap_path": r"(^|/)billing/invoices/totals\.py$", "key": r"LICENSE_ID = 'clinic-7'"},
    {"name": "c2_repo_header", "token": "clinic: generated", "shape": "repo_wide_recent", "control": True,
     "needed": N["repo_recent"], "needed_scope": "",
     "later": ("Create staff/rota/swap.py with a function can_swap(shift_a, shift_b) that says whether two staff "
               "members can swap shifts of equal length."),
     "trap_regex": r"\A(?!# clinic: generated)", "trap_on": "content", "trap_path": r"(^|/)staff/rota/swap\.py$",
     "key": r"# clinic: generated"},
    {"name": "c2_lab_code", "token": "lab_code", "shape": "two_dirs", "control": True, "needed": N["two_dirs"],
     "needed_scope": "lab/results/",
     "later": ("Using normalise() from patients/directory.py, create lab/results/report_name.py with a function "
               "result_title(patient_name, panel) that returns a title like 'Jane Doe - blood'."),
     "trap_regex": r"def \w+\((?![^)]*\*[^)]*\blab_code\b)", "trap_on": "content",
     "trap_path": r"(^|/)lab/results/report_name\.py$", "key": r"lab_code"},
    {"name": "c2_chart_rows", "token": "max_bars", "shape": "edit_named_file", "control": True,
     "needed": N["edit_named"], "needed_scope": "reports/charts/",
     "later": ("Add a function to reports/charts/bars.py that turns a dict of label -> count into rows for a bar "
               "chart, largest count first."),
     "trap_regex": r"def (?!chart_scale\b|_)\w+\((?![^)]*\*[^)]*\bmax_bars\b)", "trap_on": "content",
     "trap_path": r"(^|/)reports/charts/bars\.py$", "key": r"max_bars"},
    {"name": "c2_remind_prefix", "token": "remind_", "shape": "no_path_in_prompt", "control": True,
     "needed": N["no_path"], "needed_scope": "booking/reminders/",
     "later": ("Appointment reminders need their message text: add a function to the module that defines "
               "REMINDER_HOURS which builds the reminder text from a patient name and an appointment time."),
     "trap_regex": r"def (?!remind_)\w+\(", "trap_on": "content", "trap_path": r"(^|/)booking/reminders/timing\.py$",
     "key": r"remind_ prefix", "first_touch": True},
    {"name": "c2_shift_hours", "token": "_hours", "shape": "file_note", "control": True, "needed": N["file_note"],
     "needed_scope": "staff/rota/shifts.py",
     "later": ("Add a function to staff/rota/shifts.py that sums how long the night shifts in a list last, each "
               "shift a dict with 'start_hour' and 'length'."),
     "trap_regex": r"def (?!_)(?!\w*_hours\()\w+\(", "trap_on": "content", "trap_path": r"(^|/)staff/rota/shifts\.py$",
     "key": r"end in _hours"},
]

# Scenarios carry their own files and history, so every hier1 helper (seed_store, measure, offline_check, oracle_all)
# works on them unchanged.
SCENARIOS = [dict(sc, files=dict(FILES), history=history(sc)) for sc in _SCENARIOS]


def pilot_pool() -> list[dict]:
    return [dict(sc, oracle=_H.oracle_all(sc)) for sc in SCENARIOS]


def freeze(sc: dict) -> dict:
    return dict(sc, set="hier2", tuned_on=False)


if __name__ == "__main__":
    for sc in SCENARIOS:
        o = _H.offline_check(sc)
        print(f"{sc['name']:18s} {sc['shape']:20s} flat={o['flat_surfaced']!s:5s} hier={o['hier_surfaced']!s:5s} "
              f"(pin={o['hier_needed_pinned']!s:5s} ret={o['hier_needed_retrieved']!s:5s} "
              f"touch={o['hier_needed_first_touch']!s:5s}) flat pin/ret={o['flat_needed_pinned']}/{o['flat_needed_retrieved']} "
              f"tokens {o['flat_total_tokens']}/{o['hier_total_tokens']}")
