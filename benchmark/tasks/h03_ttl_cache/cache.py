class TTLCache:
    def __init__(self, capacity, ttl, clock):
        self.capacity = capacity
        self.ttl = ttl
        self.clock = clock
        self._data = {}

    def get(self, key, default=None):
        item = self._data.get(key)
        if item is None:
            return default
        value, stored_at = item
        if self.clock() - stored_at >= self.ttl:
            del self._data[key]
            return default
        return value

    def put(self, key, value):
        if key not in self._data and len(self._data) >= self.capacity:
            oldest = next(iter(self._data))
            del self._data[oldest]
        self._data[key] = (value, self.clock())

    def __len__(self):
        return len(self._data)
