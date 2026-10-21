import unittest

from semver import compare_versions

ORDERED = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta",
           "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"]


class TestCompareVersions(unittest.TestCase):
    def test_numeric_core(self):
        self.assertEqual(compare_versions("1.2.3", "1.2.4"), -1)
        self.assertEqual(compare_versions("1.10.0", "1.9.0"), 1)
        self.assertEqual(compare_versions("2.0.0", "2.0.0"), 0)

    def test_prerelease_is_lower_than_release(self):
        self.assertEqual(compare_versions("1.0.0-alpha", "1.0.0"), -1)
        self.assertEqual(compare_versions("1.0.0", "1.0.0-rc.1"), 1)

    def test_numeric_identifiers_compare_as_numbers(self):
        self.assertEqual(compare_versions("1.0.0-alpha.2", "1.0.0-alpha.10"), -1)

    def test_more_identifiers_win_when_prefix_equal(self):
        self.assertEqual(compare_versions("1.0.0-alpha", "1.0.0-alpha.1"), -1)

    def test_numeric_lower_than_alphanumeric(self):
        self.assertEqual(compare_versions("1.0.0-alpha.1", "1.0.0-alpha.beta"), -1)

    def test_full_precedence_chain(self):
        for i, low in enumerate(ORDERED):
            for high in ORDERED[i + 1:]:
                self.assertEqual(compare_versions(low, high), -1, (low, high))
                self.assertEqual(compare_versions(high, low), 1, (high, low))

    def test_build_metadata_is_ignored(self):
        self.assertEqual(compare_versions("1.0.0+a", "1.0.0+b"), 0)
        self.assertEqual(compare_versions("1.0.0-rc.1+x", "1.0.0-rc.1"), 0)
        self.assertEqual(compare_versions("1.0.1+zzz", "1.0.0+aaa"), 1)
