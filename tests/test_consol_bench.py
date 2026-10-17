"""The consolidation benchmark itself: scenario well-formedness, traps, key texts, the deterministic harness with and
without the feature, label scoring. No model calls."""
import re
import unittest

from bench import consolidation_eval as ce
from bench.live import consol1_candidates as c1
from bench.live import metrics

SHAPES = {"gain_rule", "gain_note", "control_child_detail", "control_lookalike", "control_retry_detail"}


def _write(path, content):
    return [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Write", "input": {"file_path": path, "content": content}}]}}]


def _edit(path, new):
    return [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Edit", "input": {"file_path": path, "old_string": "x", "new_string": new}}]}}]


def _bash(*cmds):
    return [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": c}} for c in cmds]}}]


# (violating events, compliant events) per scenario, written the way an agent would
SAMPLES = {
    "g_pricing_header": (
        _write("/r/pricing/discounts.py", '"""Discounts."""\nfrom pricing.rules import round_cents\n\n\ndef apply_discount(price_cents, percent):\n    return round_cents(price_cents * (100 - percent) / 100)\n'),
        _write("/r/pricing/discounts.py", "# owner: pricing-core\nfrom pricing.rules import round_cents\n\n\ndef apply_discount(price_cents, percent):\n    return round_cents(price_cents * (100 - percent) / 100)\n")),
    "g_alerts_runid": (
        _edit("/r/alerts/rules.py", "def over_threshold(values):\n    return [k for k, v in values.items() if v > THRESHOLDS.get(k, 100)]\n"),
        _edit("/r/alerts/rules.py", "def over_threshold(\n    values,\n    run_id=None,\n):\n    return [k for k, v in values.items() if v > THRESHOLDS.get(k, 100)]\n")),
    "g_catalog_rev": (
        _write("/r/catalog/search.py", "from catalog.items import ITEMS\n\n\ndef find(prefix):\n    return [s for s in ITEMS if s.startswith(prefix)]\n"),
        _write("/r/catalog/search.py", "from catalog.items import ITEMS\n\nCATALOG_REV = 7\n\n\ndef find(prefix):\n    return [s for s in ITEMS if s.startswith(prefix)]\n")),
    "c_child_detail": (
        _write("/r/sessions/cache.py", "def cache_key(session_id):\n    return f'session:{session_id}'\n"),
        _write("/r/sessions/cache.py", "KEY_PREFIX = 'sx2:'\n\n\ndef cache_key(session_id):\n    return f'{KEY_PREFIX}{session_id}'\n")),
    "c_lookalike": (
        _write("/r/feeds/atom_meta.py", "FEED_TAG = 'r9'\n\n\ndef feed_meta(title):\n    return {'title': title, 'tag': FEED_TAG}\n"),
        _write("/r/feeds/atom_meta.py", "FEED_TAG = 'a4'\n\n\ndef feed_meta(title):\n    return {'title': title, 'tag': FEED_TAG}\n")),
    "c_retry_flags": (_bash("ls", "./qa"), _bash("cat qa", "./qa --serial")),
}


class Scenarios(unittest.TestCase):
    def test_well_formed(self):
        names = [sc["name"] for sc in c1.CANDIDATES]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(4 <= len(names) <= 6)
        self.assertEqual(sorted(SAMPLES), sorted(names))
        for sc in c1.CANDIDATES:
            for k in ("shape", "files", "later", "trap_regex", "trap_on", "oracle", "key", "needed", "hot"):
                self.assertIn(k, sc, (sc["name"], k))
            self.assertIn(sc["shape"], SHAPES)
            self.assertIn(sc["trap_on"], ("content", "cmd_path"))
            if sc["trap_on"] == "content":
                self.assertTrue(sc["trap_path"] and sc["trap_path"].endswith(r"\.py$"), sc["name"])   # exact file
            self.assertIn(sc["hot"], sc["files"])
            self.assertEqual(sum(h["role"] == "needed" for h in c1.history(sc)), 1)
        self.assertTrue(any(sc["shape"].startswith("gain") for sc in c1.CANDIDATES))
        self.assertTrue(any(sc["shape"].startswith("control") for sc in c1.CANDIDATES))

    def test_convention_not_visible_in_starter_files(self):
        for sc in c1.CANDIDATES:
            for path, content in sc["files"].items():
                self.assertIsNone(re.search(sc["key"], content), (sc["name"], path))
                self.assertIsNone(re.search(sc["key"], path), (sc["name"], path))

    def test_key_text_only_in_the_needed_memory(self):
        """by-text surfacing must not be fooled by a near-duplicate that happens to contain the key."""
        for sc in c1.CANDIDATES:
            hits = [h["role"] for h in c1.history(sc) if re.search(sc["key"], h["text"])]
            self.assertEqual(hits, ["needed"], sc["name"])
            self.assertRegex(sc["oracle"], sc["key"])

    def test_traps_fire_on_violation_only(self):
        for sc in c1.CANDIDATES:
            bad, good = SAMPLES[sc["name"]]
            m = lambda ev: metrics.metrics(ev, sc["trap_regex"], sc["trap_on"], sc.get("trap_path"))["trap_hit"]
            self.assertTrue(m(bad), sc["name"])
            self.assertFalse(m(good), sc["name"])

    def test_content_traps_judge_only_the_exact_file(self):
        for sc in c1.CANDIDATES:
            if sc["trap_on"] != "content":
                continue
            bad, _ = SAMPLES[sc["name"]]
            ev = bad[0]["message"]["content"][0]["input"]
            other = _write("/r/other/elsewhere.py", ev.get("content") or ev.get("new_string"))
            self.assertFalse(metrics.metrics(other, sc["trap_regex"], "content", sc["trap_path"])["trap_hit"], sc["name"])

    def test_retry_trap_variants(self):
        sc = next(s for s in c1.CANDIDATES if s["name"] == "c_retry_flags")
        hit = lambda *cmds: metrics.metrics(_bash(*cmds), sc["trap_regex"], "cmd_path")["trap_hit"]
        self.assertTrue(hit("cd /tmp/r && ./qa -q"))
        self.assertTrue(hit("./qa; ./qa --serial"))           # ran it without the flag first
        self.assertFalse(hit("./qa -v --serial"))
        self.assertFalse(hit("python3 -m pytest -q"))           # not ./qa at all: not this trap's mistake

    def test_offline_flat_and_design_simulation(self):
        """Flat ranking misses every gain scenario and surfaces every control; the simulation of the planned grouping
        (not the real code) gives the design intent: gains hit, the retry-detail control loses its fact."""
        for sc in c1.CANDIDATES:
            o = c1.offline_check(sc, simulate=True)
            arm = "consol_sim" if "consol_sim" in o else "consol"
            if sc["shape"].startswith("gain"):
                self.assertFalse(o["flat"]["surfaced"], sc["name"])
                if arm == "consol_sim":
                    self.assertTrue(o[arm]["surfaced"], sc["name"])
            else:
                self.assertTrue(o["flat"]["surfaced"], sc["name"])
            if arm == "consol_sim" and sc["name"] == "c_retry_flags":
                self.assertFalse(o[arm]["surfaced"])

    def test_signature_matches_announced_grouping(self):
        s = c1.signature
        a = "`pytest tests/test_x.py -q` failed and passed after editing x/a.py. Fix was in x/a.py."
        b = "`pytest tests/test_x.py --lf -k slow` failed and passed after editing x/b.py, x/a.py. Fix was in x/a.py."
        self.assertEqual(s(a), s(b))
        self.assertNotEqual(s(a), s(a.replace("pytest tests/test_x.py", "./qa")))
        r1 = c1._revert("x/a.py", "A = 1", "A = 2")
        self.assertNotEqual(s(r1), s(c1._revert("x/a.py", "B = 1", "B = 2")))     # quoted spans are kept


class Harness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = ce.run_size(100)

    def test_key_texts_unique_in_store(self):
        from memcode import store
        d, meta = ce.build_store(1000)
        try:
            con = store.connect(d)
            rows = con.execute("SELECT id, text FROM memories").fetchall()
            con.close()
            for p in ce.PROMPTS:
                ids = [r["id"] for r in rows if re.search(p["key"], r["text"])]
                self.assertEqual(ids, [meta["tags"][p["needed"]]], p["name"])
        finally:
            ce._rmtree(d)

    def test_store_mix_and_size(self):
        from memcode import store
        for n in (100, 1000):
            d, meta = ce.build_store(n)
            try:
                con = store.connect(d)
                self.assertEqual(con.execute("SELECT COUNT(*) FROM memories").fetchone()[0], n)
                team = con.execute("SELECT COUNT(*) FROM memories WHERE provenance LIKE '%\"source\": \"team\"%'").fetchone()[0]
                self.assertEqual(team, 2)
                con.close()
                self.assertEqual(set(meta["tags"]), {v["tag"] for v in ce.VALUABLE})
            finally:
                ce._rmtree(d)

    def test_flag_off_runs_and_flag_on_is_never_a_copy(self):
        r = self.res
        self.assertTrue(r["flat"]["present"])
        self.assertEqual(len(r["flat"]["prompts"]), len(ce.PROMPTS))
        md = ce.markdown([r], [], {"present": False})
        present = ce.Feature.present()
        if not present["consolidate"]:
            self.assertFalse(r["consol"]["present"])
            self.assertFalse(r["budget"]["present"])
            self.assertIn(f"| 100 | consol | {ce.NA} |", md)
            self.assertFalse(r["budget_check"]["present"])
        else:
            self.assertTrue(r["consol"]["present"])
            if present["budget"]:
                self.assertTrue(r["budget_check"]["invariants_ok"], r["budget_check"])
                self.assertLessEqual(r["budget_check"]["after"], max(r["budget_cap"], len(r["budget"]["store_after"]["rules"])
                                                                     + len(r["budget"]["store_after"]["team"])))
            self.assertEqual(r["consol"]["wrong_merges"], [])

    def test_labels_never_change_injection(self):
        lr = self.res["labels_rank"]
        if ce.Feature.present()["labels"]:
            self.assertTrue(lr["ok"], lr)
        else:
            self.assertFalse(lr["present"])

    def test_arm_env_strips_inherited_flags(self):
        import os
        os.environ["MEMCODE_RANK"] = "salience"
        try:
            with ce.arm_env({"MEMCODE_CONSOLIDATE": "1"}):
                self.assertNotIn("MEMCODE_RANK", os.environ)
                self.assertEqual(os.environ["MEMCODE_RETRIEVAL"], "1")
            self.assertEqual(os.environ["MEMCODE_RANK"], "salience")
        finally:
            os.environ.pop("MEMCODE_RANK", None)


class Labels(unittest.TestCase):
    def test_sample_size_and_vocab(self):
        self.assertEqual(len(ce.LABELLED), 30)
        for *_, gold in ce.LABELLED:
            self.assertTrue(gold <= set(ce.LABEL_VOCAB), gold)

    def test_scoring(self):
        gold = [g for *_, g in ce.LABELLED]
        perfect = ce.score_labels([set(g) for g in gold])
        self.assertEqual((perfect["micro_precision"], perfect["micro_recall"]), (1.0, 1.0))
        empty = ce.score_labels([set() for _ in gold])
        self.assertEqual(empty["micro_recall"], 0.0)
        self.assertEqual(empty["coverage"], 0.0)
        aliased = ce.score_labels([{"testing" if x == "tests" else "git" if x == "vcs" else x for x in g} for g in gold])
        self.assertEqual(aliased["micro_precision"], 1.0)
        noisy = ce.score_labels([set(g) | {"bogus"} for g in gold])
        self.assertLess(noisy["micro_precision"], 1.0)
        self.assertEqual(noisy["unknown_labels"], {"bogus": len(gold)})

    def test_labeller_if_present(self):
        res = ce.labels_eval()
        if ce.Feature.present()["labels"]:
            self.assertTrue(res["present"])
            self.assertGreaterEqual(res["micro_precision"], 0.0)
        else:
            self.assertEqual(res, {"present": False})


if __name__ == "__main__":
    unittest.main()
