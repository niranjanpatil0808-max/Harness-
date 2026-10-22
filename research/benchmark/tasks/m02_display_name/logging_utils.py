"""Small logging helpers used across the app."""

import time

LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]


def format_line(level, message, when=None):
    when = time.time() if when is None else when
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(when))
    return f"[{stamp}] {level:<7} {message}"


class Logger:
    def __init__(self, name, level="INFO"):
        self.name = name
        self.level = level
        self.lines = []

    def enabled(self, level):
        return LEVELS.index(level) >= LEVELS.index(self.level)

    def log(self, level, message):
        if self.enabled(level):
            self.lines.append(format_line(level, f"{self.name}: {message}"))

    def info(self, message):
        self.log("INFO", message)

    def warning(self, message):
        self.log("WARNING", message)

    def error(self, message):
        self.log("ERROR", message)

    def tail(self, count=10):
        return self.lines[-count:]
