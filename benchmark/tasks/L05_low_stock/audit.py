"""A minimal audit trail."""

from dates import quarter_of


class AuditLog:
    def __init__(self):
        self._entries = []

    def record(self, day, actor, action):
        self._entries.append({"day": day, "actor": actor, "action": action})

    def by_actor(self, actor):
        return [entry for entry in self._entries if entry["actor"] == actor]

    def per_quarter(self):
        counts = {}
        for entry in self._entries:
            key = (entry["day"].year, quarter_of(entry["day"]))
            counts[key] = counts.get(key, 0) + 1
        return counts
