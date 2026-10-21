import unittest

from toposort import topo_order


class TestTopoOrder(unittest.TestCase):
    def test_chain(self):
        self.assertEqual(topo_order({"a": [], "b": ["a"], "c": ["b"]}), ["a", "b", "c"])

    def test_alphabetical_tie_break(self):
        graph = {"d": [], "c": [], "b": ["c"], "a": ["d"]}
        self.assertEqual(topo_order(graph), ["c", "b", "d", "a"])

    def test_nodes_that_only_appear_as_dependencies(self):
        self.assertEqual(topo_order({"app": ["lib", "util"]}), ["lib", "util", "app"])

    def test_diamond(self):
        graph = {"d": ["b", "c"], "b": ["a"], "c": ["a"], "a": []}
        self.assertEqual(topo_order(graph), ["a", "b", "c", "d"])

    def test_repeated_dependency(self):
        self.assertEqual(topo_order({"b": ["a", "a"]}), ["a", "b"])

    def test_empty(self):
        self.assertEqual(topo_order({}), [])

    def test_cycle(self):
        with self.assertRaises(ValueError):
            topo_order({"a": ["b"], "b": ["a"]})

    def test_self_dependency(self):
        with self.assertRaises(ValueError):
            topo_order({"a": ["a"]})

    def test_cycle_next_to_valid_nodes(self):
        with self.assertRaises(ValueError):
            topo_order({"x": [], "a": ["b", "x"], "b": ["c"], "c": ["a"]})
