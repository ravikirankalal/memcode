import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memcode import embed, graph, store  # noqa: E402


class Embeddings(unittest.TestCase):
    def setUp(self):
        self.con = store.connect(tempfile.mkdtemp())

    def add(self, text, anchor=""):
        return store.add_memory(self.con, "agent", text, anchor, None, {})

    def test_tokens_split_identifiers_and_paths(self):
        t = embed.tokens("OrderService.cancelOrder lives in billing/orders.py", "billing/orders.py")
        self.assertIn("order", t)
        self.assertIn("service", t)
        self.assertIn("path:billing/orders.py", t)

    def test_search_finds_the_closest_memory(self):
        stripe = self.add("PaymentGateway wraps the Stripe SDK for charges and refunds.", "billing/gateway.py")
        self.add("Tests run with make check, never pytest directly.")
        self.add("OrderState has states NEW, PAID, SHIPPED, CANCELLED.")
        hits = embed.search(self.con, "how do refunds go through Stripe?")
        self.assertEqual(hits[0][0], stripe)
        self.assertEqual(embed.search(self.con, "zebra giraffe"), [])

    def test_vectors_follow_text_changes(self):
        mid = self.add("Use tabs.")
        self.assertEqual(embed.refresh(self.con), [mid])
        self.assertEqual(embed.refresh(self.con), [])
        self.con.execute("UPDATE memories SET text='Use four spaces.' WHERE id=?", (mid,))
        self.assertEqual(embed.refresh(self.con), [mid])


class Graph(unittest.TestCase):
    def setUp(self):
        self.con = store.connect(tempfile.mkdtemp())

    def add(self, text, anchor=""):
        return store.add_memory(self.con, "agent", text, anchor, None, {})

    def test_auto_links_same_file_and_similar(self):
        a = self.add("PaymentGateway wraps the Stripe SDK for charges and refunds.", "billing/gateway.py")
        b = self.add("PaymentGateway retries Stripe refunds three times.", "billing/gateway.py")
        c = self.add("Refunds through the Stripe SDK need an idempotency key.")
        d = self.add("Tests run with make check.")
        self.assertEqual(graph.update(self.con), 4)
        near = {o: k for o, _, k in graph.neighbours(self.con, [a])}
        self.assertEqual(near.get(b), "same_file")
        self.assertEqual(near.get(c), "similar")
        self.assertNotIn(d, near)
        self.assertEqual(graph.update(self.con), 0)                     # nothing changed: nothing rebuilt
        self.assertGreater(graph.degree(self.con)[a], graph.degree(self.con).get(d, 0))

    def test_agent_links_survive_rebuilds_and_deletes_clear_them(self):
        a = self.add("OrderService is the entry point of the order lifecycle.")
        b = self.add("Cancelling goes through OrderState.canCancel.")
        graph.update(self.con)
        graph.link(self.con, b, a, "refines")
        self.con.execute("UPDATE memories SET text='OrderService owns the whole order lifecycle.' WHERE id=?", (a,))
        graph.update(self.con)
        self.assertIn((b, 1.0, "refines"), graph.neighbours(self.con, [a]))
        store.delete_ids(self.con, [b])
        self.assertEqual(graph.neighbours(self.con, [a]), [])

    def test_command_facts_take_no_auto_links(self):
        from memcode import facts
        facts.ensure(self.con)
        facts._upsert(self.con, "cmd:make check", "command", "test", "make check", "observed", ok=1, runs=1)
        n = self.add("Tests run with make check.")
        graph.update(self.con)
        self.assertEqual(graph.neighbours(self.con, [n]), [])
        self.assertTrue(embed.search(self.con, "make check"))          # still found by search



class Delivery(unittest.TestCase):
    """Recall and first touch bring a memory's neighbours in the graph along."""
    def setUp(self):
        from pathlib import Path
        from memcode import tree
        self.d = tempfile.mkdtemp()
        Path(self.d, "billing").mkdir()
        Path(self.d, "billing", "gateway.py").write_text("class PaymentGateway: pass\n")
        self.con = store.connect(self.d)
        tree.scan_repo(self.con, self.d)
        self.gateway = store.add_memory(self.con, "agent", "PaymentGateway wraps the Stripe SDK for charges.",
                                        "billing/gateway.py", None, {})
        self.retry = store.add_memory(self.con, "agent", "Webhooks are verified with the signing secret before use.",
                                      "", None, {})
        from memcode import scope
        for mid in (self.gateway,):
            sp, sk = scope.assign(self.con, "agent", "", "billing/gateway.py")
            self.con.execute("UPDATE memories SET scope_path=?, scope_kind=? WHERE id=?", (sp, sk, mid))
        graph.update(self.con)
        graph.link(self.con, self.gateway, self.retry, "related")
        self.con.commit()

    def test_recall_adds_a_neighbour(self):
        from memcode import retrieval
        self.con.execute("UPDATE memories SET scope_path='', scope_kind='repo'")     # folder-scoped ones come by touch
        text, ids = retrieval.render(retrieval.score(self.con, self.d, "s", "how are Stripe charges made?"),
                                     self.con, "s")
        self.assertEqual(ids, [self.gateway, self.retry])
        self.assertIn("## Memory relevant to this request", text)
        self.assertRegex(text, r"- \(note, \d{4}-\d\d-\d\d\) Webhooks are verified")

    def test_first_touch_adds_a_neighbour(self):
        from memcode import scope
        os.environ["MEMCODE_HIER"] = "1"
        try:
            text, ids = scope.rules_for_path(self.con, "s", "billing/gateway.py", self.d)
        finally:
            os.environ.pop("MEMCODE_HIER")
        self.assertEqual(ids, [self.gateway, self.retry])
        self.assertIn("## Memory for billing/gateway.py", text)


if __name__ == "__main__":
    unittest.main()
