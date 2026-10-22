"""Cron-style recurring jobs: a small 5-field parser and a thread that fires due jobs.

A job posts its prompt, addressed to its agent, into its room, exactly like a person would.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .core import Workspace

FIELDS = [("minute", 0, 59), ("hour", 0, 23), ("day of month", 1, 31), ("month", 1, 12), ("day of week", 0, 7)]


def _expand(field: str, name: str, low: int, high: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, _, step_text = part.partition("/")
            if not step_text.isdigit() or int(step_text) < 1:
                raise ValueError(f"bad step in {name}: '{field}'")
            step = int(step_text)
        if part == "*":
            start, end = low, high
        elif "-" in part:
            a, _, b = part.partition("-")
            if not (a.isdigit() and b.isdigit()):
                raise ValueError(f"bad range in {name}: '{field}'")
            start, end = int(a), int(b)
        elif part.isdigit():
            start = end = int(part)
            if step != 1:
                end = high  # "5/10" means from 5 in steps of 10
        else:
            raise ValueError(f"bad value in {name}: '{field}'")
        if start < low or end > high or start > end:
            raise ValueError(f"{name} must be between {low} and {high}: '{field}'")
        values.update(range(start, end + 1, step))
    return values


def parse_cron(expression: str) -> list[set[int]]:
    """Parse 'minute hour day-of-month month day-of-week' into five sets of allowed numbers."""
    parts = expression.split()
    if len(parts) != 5:
        raise ValueError("a cron expression has 5 fields: minute hour day-of-month month day-of-week")
    sets = [_expand(text, name, low, high) for text, (name, low, high) in zip(parts, FIELDS)]
    sets[4] = {0 if d == 7 else d for d in sets[4]}  # Sunday may be 0 or 7
    return sets


def cron_matches(expression: str, when: datetime) -> bool:
    minute, hour, dom, month, dow = parse_cron(expression)
    fields = expression.split()
    cron_dow = (when.weekday() + 1) % 7  # Python: Monday=0; cron: Sunday=0
    day_ok = when.day in dom
    weekday_ok = cron_dow in dow
    # Standard cron: if both day fields are restricted, either one matching is enough.
    if fields[2] != "*" and fields[4] != "*":
        days = day_ok or weekday_ok
    else:
        days = day_ok and weekday_ok
    return when.minute in minute and when.hour in hour and when.month in month and days


def cron_next(expression: str, after: datetime, max_days: int = 8) -> datetime | None:
    """The next time (after `after`) a cron expression fires, or None within `max_days`. Minute resolution."""
    from datetime import timedelta

    minute, hour, dom, month, dow = parse_cron(expression)
    fields = expression.split()
    restricted_both = fields[2] != "*" and fields[4] != "*"
    moment = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(max_days * 24 * 60):
        cron_dow = (moment.weekday() + 1) % 7
        day_ok, weekday_ok = moment.day in dom, cron_dow in dow
        days = (day_ok or weekday_ok) if restricted_both else (day_ok and weekday_ok)
        if moment.minute in minute and moment.hour in hour and moment.month in month and days:
            return moment
        moment += timedelta(minutes=1)
    return None


class Scheduler:
    def __init__(self, ws: "Workspace", clock: Callable[[], float] = time.time) -> None:
        self.ws = ws
        self.clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self, now: float | None = None) -> int:
        """Fire every enabled job due in the current minute (once per minute). Returns how many fired."""
        now = self.clock() if now is None else now
        minute_number = int(now // 60)
        when = self.ws.local_datetime(now)
        fired = 0
        try:
            self.ws.improver.maybe_start(now)  # a scheduled self-improvement study, if one is due and switched on
        except Exception as err:  # never let that stop the jobs
            self.ws.audit(None, "improve-error", f"{type(err).__name__}: {str(err)[:200]}")
        try:
            self.ws.backups.maybe_run(now)  # an encrypted backup, if configured and something changed
        except Exception as err:
            self.ws.audit(None, "backup-error", f"{type(err).__name__}: {str(err)[:200]}")
        for job in self.ws.list_jobs():
            if not job["enabled"] or job["last_run_minute"] == minute_number:
                continue
            try:
                due = cron_matches(job["cron"], when)
            except ValueError:
                continue
            if not due:
                continue
            self.ws.mark_job_run(job["id"], minute_number, now)
            self.ws.audit(job["agent"], "cron-fired", f"job {job['id']}")
            self.ws.post(job["room"], f"cron-{job['id']}", f"@{job['agent']} {job['prompt']}")
            fired += 1
        return fired

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="kintsugi-scheduler", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(timeout=1.0):
            try:
                self.tick()
            except Exception as err:  # keep the scheduler alive whatever one job does
                self.ws.audit(None, "scheduler-error", repr(err))

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
