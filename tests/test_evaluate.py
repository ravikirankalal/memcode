"""The memory agent's eval runner (agent/evaluate.py), offline: a fake model that answers each case perfectly passes
every check, one that keeps nothing passes only the `avoid` checks."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memcode.agent import evaluate  # noqa: E402


def item(text, evidence, **kw):
    base = {"op": "add", "target": 0, "from_user": False, "topic": "workflow", "subject": "", "importance": 4,
            "text": text, "evidence": evidence, "path": "", "links": [], "unusual": False, "conflicts": False}
    return dict(base, **kw)


PERFECT = {
    "profile from code": [
        item("PaymentGateway wraps the Stripe SDK for charges and refunds.", "Wraps the Stripe SDK", topic="integration"),
        item("OrderService is the entry point of the order lifecycle.", "Entry point of the order lifecycle", topic="component"),
        item("OrderState goes NEW, PAID, SHIPPED, DELIVERED, CANCELLED.", "enum OrderState { NEW, PAID", topic="domain"),
        item("Run the module tests with ./mvnw -q -pl orders test.", "./mvnw -q -pl orders test")],
    "deploy, infra, branching": [
        item("Branch off develop, never main; main only gets release merges.", "we never branch off main", from_user=True,
             topic="branching"),
        item("Tests live in checks/: run pytest -q checks/.", "pytest -q checks/", unusual=True),
        item("Tags v* trigger deploy.yml: staging, then prod after approval.", "tags: ['v*']", topic="deployment"),
        item("Production runs on EKS with Helm, images in ECR, Postgres on RDS.", "rds-prod.eu-west-1", topic="infra"),
        item("Checkout latency dashboard: https://grafana.acme.dev/d/checkout-p95", "grafana.acme.dev/d/checkout-p95",
             topic="reference"),
        item("Incident steps are in docs/RUNBOOK.md.", "On-call steps for checkout incidents", topic="location")],
    "a correction": [item("Tests go in checks/, never tests/.", "tests go in checks/, never tests/", from_user=True,
                          topic="convention")],
    "a decision, not the agent's progress": [item("G16 is parked until the end of the milestone.", "Park G16 until the end",
                                                 topic="decision", subject="G16")],
    "a request for now is not a rule": [],
    "a stale memory to revive": [item("orders.total(items, tax_rate) sums item prices including tax.",
                                      "def total(items, tax_rate):", op="update", target=1, topic="component")],
    "flag parked work the agent starts on its own": [item("the agent is starting the parked export unasked",
                                                          "also start the invoice export's CSV writer", op="recall",
                                                          target=1)],
    "nothing worth keeping": [],
}


class Runner(unittest.TestCase):
    def fake(self, answers):
        def extract(text, ctx):
            case = next(c for c in evaluate.load_cases() if "\n".join(c["log"]) == text)
            return {"items": answers(case), "model": "fake", "cost_usd": 0.001}
        return extract

    def test_a_perfect_answer_passes_every_check(self):
        report = evaluate.run(extract_fn=self.fake(lambda c: PERFECT[c["name"]]))
        failed = [(r["name"], label) for r in report["results"] for label, ok in r["checks"] if not ok]
        self.assertEqual(failed, [])
        self.assertEqual(report["score"], 1.0)
        self.assertEqual(len(report["results"]), len(evaluate.load_cases()))
        self.assertIn("score ", evaluate.render(report))

    def test_keeping_nothing_passes_only_the_avoid_checks(self):
        report = evaluate.run(extract_fn=self.fake(lambda c: []))
        for r in report["results"]:                       # ("left as it is" holds when nothing is done, too)
            self.assertTrue(all(ok == (label.startswith("avoids:") or "left as it is" in label)
                                for label, ok in r["checks"]), r["name"])

    def test_keeping_the_agents_progress_is_caught(self):
        bad = [item("#42 is implemented and pushed to feat/review.", "#42 is implemented and its tests pass", topic="decision")]
        report = evaluate.run(only="not the agent", extract_fn=self.fake(lambda c: bad))
        self.assertLess(report["score"], 1.0)


if __name__ == "__main__":
    unittest.main()
