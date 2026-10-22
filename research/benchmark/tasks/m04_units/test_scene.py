import unittest

from scene import total_length_cm


class TestScene(unittest.TestCase):
    def test_total(self):
        self.assertEqual(total_length_cm([50, 150, 300]), 50)

    def test_empty(self):
        self.assertEqual(total_length_cm([]), 0)
