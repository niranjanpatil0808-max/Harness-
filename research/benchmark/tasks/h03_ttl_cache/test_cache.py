import unittest

from cache import TTLCache


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class TestTTLCache(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()

    def make(self, capacity=2, ttl=10):
        return TTLCache(capacity, ttl, self.clock)

    def test_put_and_get(self):
        cache = self.make()
        cache.put("a", 1)
        self.assertEqual(cache.get("a"), 1)
        self.assertIsNone(cache.get("missing"))
        self.assertEqual(cache.get("missing", "x"), "x")

    def test_expires_exactly_at_ttl(self):
        cache = self.make()
        cache.put("a", 1)
        self.clock.now = 9.9
        self.assertEqual(cache.get("a"), 1)
        self.clock.now = 10
        self.assertIsNone(cache.get("a"))

    def test_get_does_not_extend_lifetime(self):
        cache = self.make()
        cache.put("a", 1)
        self.clock.now = 6
        self.assertEqual(cache.get("a"), 1)
        self.clock.now = 10
        self.assertIsNone(cache.get("a"))

    def test_least_recently_used_is_evicted(self):
        cache = self.make()
        cache.put("a", 1)
        cache.put("b", 2)
        cache.get("a")  # a is now more recent than b
        cache.put("c", 3)
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("a"), 1)
        self.assertEqual(cache.get("c"), 3)

    def test_put_existing_key_refreshes_value_time_and_recency(self):
        cache = self.make()
        cache.put("a", 1)
        cache.put("b", 2)
        self.clock.now = 5
        cache.put("a", 11)  # new value, new lifetime, most recent
        cache.put("c", 3)   # evicts b, the least recently used
        self.assertIsNone(cache.get("b"))
        self.clock.now = 12
        self.assertEqual(cache.get("a"), 11)

    def test_len_counts_only_live_entries(self):
        cache = self.make(capacity=3)
        cache.put("a", 1)
        self.clock.now = 5
        cache.put("b", 2)
        self.assertEqual(len(cache), 2)
        self.clock.now = 10
        self.assertEqual(len(cache), 1)

    def test_expired_entries_are_dropped_before_evicting_live_ones(self):
        cache = self.make(capacity=2)
        cache.put("a", 1)          # t=0
        self.clock.now = 4
        cache.put("b", 2)          # t=4
        self.clock.now = 5
        cache.get("a")             # a is more recent than b, but older
        self.clock.now = 10        # a expired (age 10), b live (age 6)
        cache.put("c", 3)          # must drop expired a, not evict live b
        self.assertEqual(cache.get("b"), 2)
        self.assertEqual(cache.get("c"), 3)
        self.assertEqual(len(cache), 2)
