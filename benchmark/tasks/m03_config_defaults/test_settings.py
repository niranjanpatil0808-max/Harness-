import unittest

from settings import get_setting, load


class TestSettings(unittest.TestCase):
    def test_present(self):
        self.assertEqual(get_setting(load("timeout = 30"), "timeout"), "30")

    def test_default(self):
        self.assertEqual(get_setting(load("# empty"), "timeout"), "15")
        self.assertEqual(get_setting({}, "region"), "ap-south-1")

    def test_unknown(self):
        with self.assertRaises(KeyError):
            get_setting({}, "colour")
