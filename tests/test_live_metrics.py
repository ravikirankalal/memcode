import json
import unittest

from bench.live import metrics


def ev(*cmds):
    return [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": c}} for c in cmds]}},
        {"type": "result", "session_id": "s", "total_cost_usd": 0.01}]


class T(unittest.TestCase):
    def test_metrics(self):
        m = metrics.metrics(ev("ls", "python -m unittest", "pytest -q"), r"unittest")
        self.assertTrue(m["trap_hit"])
        self.assertEqual((m["explore_calls"], m["bash_calls"], m["session_id"]), (1, 3, "s"))

    def test_clean_and_parse(self):
        text = "\n".join(json.dumps(e) for e in ev("pytest -q")) + "\nnoise"
        m = metrics.metrics(metrics.parse_stream(text), r"unittest")
        self.assertFalse(m["trap_hit"])
        self.assertEqual(metrics.summarize([m])["trap_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
