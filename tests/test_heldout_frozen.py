import hashlib
import json
import unittest

from bench.live.heldout import FROZEN_SHA256, HELDOUT


class Frozen(unittest.TestCase):
    def test_hash_unchanged(self):
        self.assertEqual(hashlib.sha256(json.dumps(HELDOUT, sort_keys=True).encode()).hexdigest(), FROZEN_SHA256,
                         "held-out set changed: add a NEW set instead of editing this one")

    def test_not_tuned_flag_and_names(self):
        self.assertEqual(sorted(s["name"] for s in HELDOUT), ["h_camel_case", "h_check_files", "h_single_quotes", "h_tabs"])
        self.assertTrue(all(s["tuned_on"] is False for s in HELDOUT))


if __name__ == "__main__":
    unittest.main()


class Frozen2(unittest.TestCase):
    def test_hash_unchanged(self):
        from bench.live.heldout2 import FROZEN_SHA256 as H2, HELDOUT2
        self.assertEqual(hashlib.sha256(json.dumps(HELDOUT2, sort_keys=True).encode()).hexdigest(), H2,
                         "heldout2 changed: add a NEW set instead of editing this one")
        self.assertEqual(sorted(s["name"] for s in HELDOUT2),
                         ["k_dataclass", "k_header", "k_main_block", "k_module_imports", "k_pathlib"])
        self.assertTrue(all(s["tuned_on"] is False for s in HELDOUT2))


class Frozen3(unittest.TestCase):
    def test_hash_unchanged_and_shape(self):
        from bench.live.heldout3 import FROZEN_SHA256 as H3, HELDOUT3
        self.assertEqual(hashlib.sha256(json.dumps(HELDOUT3, sort_keys=True).encode()).hexdigest(), H3,
                         "heldout3 changed: add a NEW set instead of editing this one")
        self.assertEqual(sorted(s["name"] for s in HELDOUT3),
                         ["m_four_rules", "m_rules_and_distractors", "m_stated_as_info", "m_supersede",
                          "m_three_across_sessions"])
        self.assertTrue(all(s["tuned_on"] is False and s.get("oracle") for s in HELDOUT3))


class Frozen4(unittest.TestCase):
    def test_hash_unchanged_and_shape(self):
        from bench.live.heldout4 import FROZEN_SHA256 as H4, HELDOUT4
        self.assertEqual(hashlib.sha256(json.dumps(HELDOUT4, sort_keys=True).encode()).hexdigest(), H4,
                         "heldout4 changed: add a NEW set instead of editing this one")
        self.assertEqual(sorted(s["name"] for s in HELDOUT4),
                         ["n_info_header", "n_info_tabs", "n_mixed", "n_text_gap_main", "n_text_gap_two_rules"])
        self.assertTrue(all(s["tuned_on"] is False and s.get("oracle") for s in HELDOUT4))


class FrozenPressure1(unittest.TestCase):
    def test_hash_and_predictions(self):
        from bench.live.pressure1 import FROZEN_SHA256 as HP, PREDICTIONS, PRESSURE1
        self.assertEqual(hashlib.sha256(json.dumps(PRESSURE1, sort_keys=True).encode()).hexdigest(), HP,
                         "pressure1 changed: add a NEW set instead of editing this one")
        self.assertEqual(sorted(PREDICTIONS), sorted(s["name"] for s in PRESSURE1))
        self.assertTrue(all(not p["target_pinned"] and p["retrieved_relevance"] for p in PREDICTIONS.values()))


class FrozenPressure2(unittest.TestCase):
    def test_hash_and_predictions(self):
        from bench.live.pressure2 import FROZEN_SHA256 as H, PREDICTIONS, PRESSURE2
        self.assertEqual(hashlib.sha256(json.dumps(PRESSURE2, sort_keys=True).encode()).hexdigest(), H,
                         "pressure2 changed: add a NEW set instead of editing this one")
        self.assertEqual(len(PRESSURE2), 8)
        self.assertTrue(all(not p["target_pinned"] and p["injected_relevance"] == 1 for p in PREDICTIONS.values()))
