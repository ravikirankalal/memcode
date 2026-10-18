"""tc2 self-checks: frozen hash, traps catch a no-memory answer and pass a compliant one, starter files hide answers."""
import hashlib
import json
import re
import unittest

from bench.live import metrics
from bench.live.tc2 import FROZEN_SHA256, TC2

SAMPLES = {   # name -> (written text or command, compliant text or command)
    "g_prefix": ("def area(w, h):\n    return w * h\n", "def qx_area(w, h):\n    return w * h\n"),
    "g_result_tuple": ("def parse_age(t):\n    raise ValueError(t)\n", "def parse_age(t):\n    return None, 'bad'\n"),
    "g_owner_line": ('"""Text helpers."""\n', '"""Text helpers.\n\nOwner: platform\n"""\n'),
    "d_qa_runner": ("python3 -m pytest -q", "sh tools/ci/verify.sh"),
    "d_tally_env": ("python3 -m tally report 2026-03", "TALLY_DATA=ledger python3 -m tally report 2026-03"),
    "k_pattern_rule": ("def area(w, h):\n    return w * h\n", "def area(w: float, h: float) -> float:\n    return w * h\n"),
    "k_one_off": ("def temp_area(w, h):\n    return w * h\n", "def area(w, h):\n    return w * h\n"),
}


def events(sc, text):
    if sc["trap_on"] == "cmd_path":
        b = {"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": text}}
    else:
        path = "/r/" + re.search(r"\(\^\|/\)(.+)\$$", sc["trap_path"]).group(1).replace("\\.", ".")
        b = {"type": "tool_use", "id": "t", "name": "Write", "input": {"file_path": path, "content": text}}
    return [{"type": "assistant", "message": {"content": [b]}}]


class TC2Set(unittest.TestCase):
    def test_hash_unchanged(self):
        self.assertEqual(hashlib.sha256(json.dumps(TC2, sort_keys=True).encode()).hexdigest(), FROZEN_SHA256)

    def test_traps(self):
        self.assertEqual(sorted(s["name"] for s in TC2), sorted(SAMPLES))
        for sc in TC2:
            bad, good = SAMPLES[sc["name"]]
            hit = lambda t: metrics.metrics(events(sc, t), sc["trap_regex"], sc["trap_on"], sc.get("trap_path"))["trap_hit"]  # noqa: E731
            self.assertTrue(hit(bad), sc["name"])
            self.assertFalse(hit(good), sc["name"])

    def test_starter_files_do_not_give_the_answer(self):
        for sc in TC2:
            blob = "\n".join(sc["files"].values())
            for token in ("qx_", "Owner: platform", "(value, error)", "temp_"):
                self.assertNotIn(token, blob, sc["name"])


if __name__ == "__main__":
    unittest.main()
