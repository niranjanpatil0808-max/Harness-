import unittest
from pathlib import Path

from kintsugi.graph import ContextGraph
from kintsugi.loop import load_task, solve
from kintsugi.model import MockModel

SHOP = Path(__file__).parent / "fixtures" / "shop"


class TestGraph(unittest.TestCase):
    def setUp(self):
        self.task = load_task(SHOP)
        self.graph = ContextGraph.build(self.task.sources)

    def test_definitions_found(self):
        self.assertIn("pricing.py::order_total", self.graph.nodes)
        self.assertEqual(self.graph.nodes["tax.py::TAX_RATE"].kind, "constant")

    def test_call_reference_and_import_edges(self):
        edges = self.graph.edges
        self.assertEqual(edges["pricing.py::order_total"]["pricing.py::subtotal"], "calls")
        self.assertEqual(edges["pricing.py::order_total"]["tax.py::TAX_RATE"], "references")
        self.assertEqual(edges["pricing.py::<module>"]["tax.py::apply_tax"], "imports")
        self.assertEqual(edges["reports.py::<module>"]["pricing.py::<module>"], "imports")

    def test_seeds_come_from_tests(self):
        self.assertIn("pricing.py::order_total", self.graph.seeds_for(self.task))

    def test_ranking_prefers_connected_code(self):
        scores = self.graph.rank(self.graph.seeds_for(self.task))
        self.assertGreater(scores["tax.py::TAX_RATE"], scores["reports.py::format_header"])

    def test_context_shows_relevant_file_and_skips_unrelated(self):
        text, editable = self.graph.context_for(self.task)
        self.assertIn("pricing.py", editable)
        self.assertNotIn("reports.py", editable)
        self.assertIn("TAX_RATE = 0.08", text)  # related constant shown from tax.py
        self.assertNotIn('center(40, "=")', text)  # unrelated body left out

    def test_everyday_container_methods_do_not_link_to_user_methods(self):
        graph = ContextGraph.build({
            "store.py": "def lookup(d, key):\n    return d.get(key)\n",
            "cache.py": "class Cache:\n    def get(self, key):\n        return key\n",
        })
        self.assertNotIn("cache.py::Cache.get", graph.edges.get("store.py::lookup", {}))

    def test_plain_function_calls_still_link(self):
        graph = ContextGraph.build({
            "a.py": "from b import get\n\ndef run(x):\n    return get(x)\n",
            "b.py": "def get(x):\n    return x\n",
        })
        self.assertEqual(graph.edges["a.py::run"]["b.py::get"], "calls")

    def test_unparsable_file_is_skipped(self):
        graph = ContextGraph.build({"ok.py": "def f():\n    return 1\n", "bad.py": "def (:\n"})
        self.assertIn("ok.py::f", graph.nodes)

    def test_loop_with_graph_fixes_multi_file_task(self):
        fix = ("```python\n# file: pricing.py\nfrom tax import apply_tax\n\n\n"
               "def subtotal(items):\n    return sum(p * q for p, q in items)\n\n\n"
               "def order_total(items):\n    return round(apply_tax(subtotal(items)), 2)\n```")
        model = MockModel([fix])
        result = solve(self.task, model, max_retries=0, use_graph=True)
        self.assertTrue(result.passed, result.attempts[-1].output)
        self.assertNotIn("monthly_report", model.prompts[0][-1]["content"].split("Other files")[0])


if __name__ == "__main__":
    unittest.main()
