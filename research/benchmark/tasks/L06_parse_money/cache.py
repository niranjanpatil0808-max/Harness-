"""A tiny cache."""


class SimpleCache:
    def __init__(self, capacity=128):
        self.capacity = capacity
        self._data = {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def put(self, key, value):
        if key not in self._data and len(self._data) >= self.capacity:
            self._data.pop(next(iter(self._data)))
        self._data[key] = value

    def clear(self):
        self._data.clear()

    def __len__(self):
        return len(self._data)
