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
