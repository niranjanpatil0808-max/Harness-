from collections import OrderedDict


class TTLCache:
    def __init__(self, capacity, ttl, clock):
        self.capacity = capacity
        self.ttl = ttl
        self.clock = clock
        self._data = OrderedDict()  # key -> (value, stored_at), least recently used first

    def _is_live(self, stored_at):
        return self.clock() - stored_at < self.ttl

    def _purge(self):
        for key in [k for k, (_, stored_at) in self._data.items() if not self._is_live(stored_at)]:
            del self._data[key]

    def get(self, key, default=None):
        item = self._data.get(key)
        if item is None:
            return default
        value, stored_at = item
        if not self._is_live(stored_at):
            del self._data[key]
            return default
        self._data.move_to_end(key)
        return value

    def put(self, key, value):
        if key in self._data:
            del self._data[key]
        else:
            self._purge()
            if len(self._data) >= self.capacity:
                self._data.popitem(last=False)
        self._data[key] = (value, self.clock())

    def __len__(self):
        self._purge()
        return len(self._data)
