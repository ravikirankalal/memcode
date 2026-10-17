"""Offline tests of the hier1 benchmark harness (bench/live/hier1_candidates.py). No network, no model calls."""
import re
import unittest

from bench.live import hier1_candidates as h
from bench.live import metrics

# A typical no-memory answer (must trap) and one that follows the needed memory (must not), per scenario.
# Edit=True: the agent edits an existing file, so the trap sees an Edit fragment, not a whole file.
SAMPLES = {
    "h_pricing_epoch": ("def tier_for(quantity):\n    return 'single'\n",
                        "EPOCH = 7\n\n\ndef tier_for(quantity):\n    return 'single'\n", False),
    "h_checkout_footer": ("def wallet_balance(entries):\n    return 0\n",
                          "def wallet_balance(entries):\n    return 0\n\n# owner: checkout-core\n", False),
    "h_insights_schema": ("def sparkline(values, width):\n    return []\n",
                          "SCHEMA = \"ins-3\"\n\n\ndef sparkline(values, width):\n    return []\n", False),
    "c_repo_header": ("import secrets\n\n\ndef make_code(digits):\n    return ''\n",
                      "# shopfront: managed\nimport secrets\n\n\ndef make_code(digits):\n    return ''\n", False),
    "h_repo_reviewed": ("def label(lines):\n    return '^XA^XZ'\n",
                        "REVIEWED = False\n\n\ndef label(lines):\n    return '^XA^XZ'\n", False),
    "c_jobs_run_id": ("from fulfil.carriers.rates import quote\n\n\ndef refresh_rates(carriers, weight_g):\n    return []\n",
                      "from fulfil.carriers.rates import quote\n\n\ndef refresh_rates(\n    carriers,\n    weight_g,\n"
                      "    run_id,\n):\n    return []\n", False),
    "c_auth_audit": ("from members.auth.sessions import SESSIONS\n\n\ndef is_locked(member_id, failures):\n    return False\n",
                     "AUDIT_TAG = 'auth'\n\n\ndef is_locked(member_id, failures):\n    return False\n", False),
    "c_alerts_prefix": ("def format_message(severity, description):\n    return ''\n",
                        "def alert_format(severity, description):\n    return ''\n", True),
    "c_avatar_prefix": ("def largest_size(limit):\n    return 32\n",
                        "def av_largest_size(limit):\n    return 32\n", True),
}


def _events(path, text, edit):
    inp = ({"file_path": path, "old_string": "X", "new_string": text} if edit else {"file_path": path, "content": text})
    return [{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit" if edit else "Write",
                                                            "input": inp}]}}]


class Scenarios(unittest.TestCase):
    def test_well_formed(self):
        names = [s["name"] for s in h.SCENARIOS]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(sorted(names), sorted(SAMPLES))
        for sc in h.SCENARIOS:
            for k in ("name", "shape", "needed", "needed_scope", "later", "trap_regex", "trap_on", "trap_path", "key",
                      "token"):
                self.assertTrue(sc.get(k) is not None, (sc["name"], k))
            self.assertEqual(sc["trap_on"], "content")
            hist = h.history(sc)
            self.assertEqual(sum(x["needed"] for x in hist), 1, sc["name"])
            needed = next(x for x in hist if x["needed"])
            self.assertEqual(needed["scope"], sc["needed_scope"], sc["name"])
            self.assertTrue(h.in_chain(needed["scope"], h.target_path(sc)), sc["name"])   # needed applies to the target
            self.assertIn(needed, h.relevant(sc))
            self.assertIn(sc["needed"], h.oracle_all(sc))
            self.assertIn(sc["key"], sc["needed"])
        texts = [t for _, t, _ in h.RULES] + [t for _, t, _, _ in h.NOTES]
        self.assertEqual(len(texts), len(set(texts)), "duplicate memory text")
        self.assertGreaterEqual(len(h.RULES), 60)
        dirs = {s for s, _, _ in h.RULES if s}
        self.assertGreaterEqual(len(dirs), 12)

    def test_prompts_name_the_target_except_no_path_shape(self):
        from memcode import retrieval
        for sc in h.SCENARIOS:
            tp = h.target_path(sc)
            if sc["shape"] == "no_path_in_prompt":
                self.assertEqual(retrieval.path_tokens(sc["later"]), set(), sc["name"])
                words = set(re.findall(r"[a-z]+", sc["later"].lower()))
                for part in tp.split("/")[:-1]:        # no dir word either (hier treats a dir basename as a mention)
                    self.assertNotIn(part, words, (sc["name"], part))
                self.assertTrue(sc.get("first_touch"))
            else:
                self.assertIn(tp, sc["later"], sc["name"])
            self.assertTrue(re.search(sc["trap_path"], "/tmp/r/" + tp), sc["name"])
            self.assertFalse(re.search(sc["trap_path"], "/tmp/r/x" + tp.replace("/", "_")), sc["name"])

    def test_conventions_not_visible_in_starter_repo(self):
        for sc in h.SCENARIOS:
            tok = sc["token"]
            for path, content in h.FILES.items():
                self.assertNotIn(tok, content, (sc["name"], path))
                self.assertNotIn(tok, path, (sc["name"], path))
            self.assertNotIn(tok, sc["later"], sc["name"])

    def test_traps_fire_on_violation_and_not_on_compliance(self):
        for sc in h.SCENARIOS:
            bad, good, edit = SAMPLES[sc["name"]]
            path = "/tmp/repo/" + h.target_path(sc)
            m = lambda text, p=path: metrics.metrics(_events(p, text, edit), sc["trap_regex"], sc["trap_on"],
                                                     sc["trap_path"])["trap_hit"]
            self.assertTrue(m(bad), (sc["name"], "violation not trapped"))
            self.assertFalse(m(good), (sc["name"], "compliant answer trapped"))
            # a violation in ANOTHER file is never judged
            self.assertFalse(m(bad, "/tmp/repo/other/place.py"), sc["name"])


class Offline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = {sc["name"]: h.offline_check(sc) for sc in h.SCENARIOS}

    def test_flat_arm_matches_design(self):
        """Controls are surfaced by flat ranking; every other shape is not (that is what makes it a test of hier)."""
        for sc in h.SCENARIOS:
            o = self.res[sc["name"]]
            self.assertEqual(o["flat_surfaced"], bool(sc.get("control")), sc["name"])
            self.assertEqual(o["flat_surfaced_by_id"], o["flat_surfaced_by_text"], sc["name"])

    def test_measures_present_and_consistent(self):
        for name, o in self.res.items():
            for arm in ("flat", "hier"):
                self.assertGreater(o[f"{arm}_pinned_tokens"], 0, name)
                self.assertEqual(o[f"{arm}_total_tokens"] >= o[f"{arm}_pinned_tokens"], True, name)
                self.assertEqual(o[f"{arm}_shown_relevant"] + o[f"{arm}_shown_irrelevant"], o[f"{arm}_shown"], name)
                self.assertLessEqual(o[f"{arm}_shown_relevant"], o[f"{arm}_relevant_total"], name)

    def test_hier_equals_flat_without_the_feature(self):
        """hier_flag_present=False must mean identical arms (made visible, never silently different)."""
        for name, o in self.res.items():
            if o["hier_flag_present"]:
                continue
            for k in o:
                if k.startswith("flat_"):
                    self.assertEqual(o[k], o["hier_" + k[5:]], (name, k))

    def test_pilot_pool_shape(self):
        for sc in h.pilot_pool():
            for k in ("name", "files", "later", "trap_regex", "trap_on", "trap_path", "oracle"):
                self.assertIn(k, sc)
            self.assertIn(sc["needed"], sc["oracle"])


if __name__ == "__main__":
    unittest.main()
