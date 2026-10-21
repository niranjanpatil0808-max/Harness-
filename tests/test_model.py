import unittest

from kintsugi.model import MockModel


class TestMockModel(unittest.TestCase):
    def test_replays_in_order_then_repeats_last(self):
        model = MockModel(["a", "b"])
        replies = [model.complete([{"role": "user", "content": "x"}]) for _ in range(3)]
        self.assertEqual(replies, ["a", "b", "b"])
        self.assertEqual(model.usage.calls, 3)

    def test_callable_script(self):
        model = MockModel(lambda messages: messages[-1]["content"].upper())
        self.assertEqual(model.complete([{"role": "user", "content": "hi"}]), "HI")


if __name__ == "__main__":
    unittest.main()
