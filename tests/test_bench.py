import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))
import run  # noqa: E402


class BenchTest(unittest.TestCase):
    def test_none_config(self):
        scns = run.load_scenarios(ROOT / "bench" / "scenarios")
        self.assertGreaterEqual(len(scns), 4)
        rows = [run.run_scenario(s, "none") for s in scns]
        for r in rows:
            self.assertEqual(r["repeated_mistakes"], r["opportunities"])
            self.assertGreater(r["opportunities"], 0)
            self.assertEqual(r["context_tokens"], 0)
            self.assertGreaterEqual(r["exploratory_calls"], 1)
            self.assertTrue(0 <= r["repeated_mistake_rate"] <= 1)
        self.assertEqual(run.aggregate(rows)["repeated_mistake_rate"], 1.0)

    def test_main_writes_results(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "r.json"
            self.assertEqual(run.main(["--configs", "none", "--out", str(out)]), 0)
            data = json.loads(out.read_text())
            self.assertIn("none", data["summary"])


if __name__ == "__main__":
    unittest.main()
