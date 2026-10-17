"""Offline checks of the hier2 set (bench/live/hier2_candidates.py). No network, no model calls."""
import unittest

from bench.live import hier1_candidates as h
from bench.live import hier2_candidates as h2
from bench.live import metrics

# per scenario: a typical no-memory answer (must trap), one that follows the needed memory (must not), Edit?
SAMPLES = {
    "h2_slots_version": ("def overlaps(a, b):\n    return a[0] < b[1] and b[0] < a[1]\n",
                         "SLOT_VERSION = 4\n\n\ndef overlaps(a, b):\n    return a[0] < b[1] and b[0] < a[1]\n", False),
    "h2_claims_ledger": ("def batch_total(claims):\n    return 0\n",
                         "def batch_total(claims):\n    return 0\n\n# ledger: audited\n", False),
    "h2_exports_phi": ("def summary_line(record):\n    return ''\n",
                       "PHI = True\n\n\ndef summary_line(record):\n    return ''\n", False),
    "h2_repo_license": ("def invoice_total(lines, discount=0):\n    return 0\n",
                        "LICENSE_ID = 'clinic-7'\n\n\ndef invoice_total(lines, discount=0):\n    return 0\n", False),
    "c2_repo_header": ("def can_swap(shift_a, shift_b):\n    return True\n",
                       "# clinic: generated\ndef can_swap(shift_a, shift_b):\n    return True\n", False),
    "c2_lab_code": ("def result_title(patient_name, panel):\n    return ''\n",
                    "def result_title(patient_name, panel, *, lab_code):\n    return ''\n", False),
    "c2_chart_rows": ("def chart_scale(values, width=BAR_WIDTH):\n    return []\n\n\ndef to_rows(counts):\n    return sorted(counts.items(), key=lambda kv: -kv[1])\n",
                      "def to_rows(counts, *, max_bars=None):\n    return sorted(counts.items(), key=lambda kv: -kv[1])\n",
                      True),
    "c2_remind_prefix": ("def reminder_text(name, when):\n    return ''\n",
                         "def remind_text(name, when):\n    return ''\n", True),
    "c2_shift_hours": ("def night_total(shifts):\n    return 0\n",
                       "def _overlap(a, b):\n    return 0\n\n\ndef night_hours(shifts):\n    return 0\n", True),
}


def _events(path, text, edit):
    inp = ({"file_path": path, "old_string": "X", "new_string": text} if edit else {"file_path": path, "content": text})
    return [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t", "name": "Edit" if edit else "Write",
                                                            "input": inp}]}}]


class Hier2(unittest.TestCase):
    def test_well_formed(self):
        self.assertEqual(sorted(s["name"] for s in h2.SCENARIOS), sorted(SAMPLES))
        texts = [t for _, t, _ in h2.RULES] + [t for _, t, _, _ in h2.NOTES]
        self.assertEqual(len(texts), len(set(texts)))
        for sc in h2.SCENARIOS:
            hist = sc["history"]
            self.assertEqual(sum(x["needed"] for x in hist), 1, sc["name"])
            needed = next(x for x in hist if x["needed"])
            self.assertEqual(needed["scope"], sc["needed_scope"], sc["name"])
            self.assertTrue(h.in_chain(needed["scope"], h.target_path(sc)), sc["name"])
            self.assertIn(sc["needed"], h.oracle_all(sc))
            self.assertRegex(sc["needed"], sc["key"])

    def test_traps_catch_and_pass(self):
        for sc in h2.SCENARIOS:
            bad, good, edit = SAMPLES[sc["name"]]
            path = "/r/" + h.target_path(sc)
            m = lambda t: metrics.metrics(_events(path, t, edit), sc["trap_regex"], "content", sc["trap_path"])["trap_hit"]  # noqa: E731
            self.assertTrue(m(bad), sc["name"])
            self.assertFalse(m(good), sc["name"])

    def test_starter_files_reveal_no_convention(self):
        blob = "\n".join(h2.FILES.values())
        for sc in h2.SCENARIOS:
            self.assertNotIn(sc["token"], blob, sc["name"])

    def test_edit_targets_exist(self):
        for sc in h2.SCENARIOS:
            if SAMPLES[sc["name"]][2]:
                self.assertIn(h.target_path(sc), h2.FILES, sc["name"])
            else:
                self.assertNotIn(h.target_path(sc), h2.FILES, sc["name"])


class Frozen(unittest.TestCase):
    def test_hash_unchanged(self):
        import hashlib
        import json
        from bench.live import hier2 as F
        payload = json.loads(json.dumps(F.SCENARIOS, sort_keys=True))
        self.assertEqual(hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(), F.FROZEN_SHA256,
                         "hier2 changed after freezing: add a NEW set instead")


if __name__ == "__main__":
    unittest.main()
