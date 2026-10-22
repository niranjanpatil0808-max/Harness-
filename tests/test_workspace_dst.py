import calendar
import tempfile
import unittest
from datetime import datetime

from kintsugi.model import MockModel
from kintsugi.workspace import Workspace
from kintsugi.workspace.scheduler import Scheduler


def run(tzname, cron, start, minutes):
    """Tick a scheduler once a minute from `start` (UTC); return the local times at which the job fired."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Workspace(tmp, model_factory=lambda n: MockModel(["ok"]), encrypt_keychain=False, sync=False)
        try:
            ws.create_agent("alice", persona="p")
            ws.create_room("team", ["alice", "you"])
            ws.set_timezone(tzname, 0)
            ws.add_job("alice", "team", cron, "go")
            scheduler, t, fired = Scheduler(ws), calendar.timegm(start.timetuple()), []
            for i in range(minutes):
                if scheduler.tick(t + 60 * i):
                    fired.append(ws.local_datetime(t + 60 * i).strftime("%m-%d %H:%M"))
            return fired
        finally:
            ws.close()


class TestDaylightSaving(unittest.TestCase):
    def setUp(self):
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo("America/New_York")
        except Exception:
            self.skipTest("no time zone database on this machine")

    def test_a_job_in_the_hour_that_does_not_exist_runs_once_after_the_jump(self):
        self.assertEqual(run("America/New_York", "30 2 * * *", datetime(2026, 3, 8, 6, 0), 120), ["03-08 03:00"])

    def test_a_job_in_the_repeated_hour_runs_once(self):
        self.assertEqual(run("America/New_York", "30 1 * * *", datetime(2026, 11, 1, 4, 30), 240), ["11-01 01:30"])

    def test_ordinary_jobs_are_unchanged_around_the_changes(self):
        self.assertEqual(run("America/New_York", "0 3 * * *", datetime(2026, 3, 8, 6, 0), 120), ["03-08 03:00"])  # exists, fires normally
        self.assertEqual(run("America/New_York", "30 4 * * *", datetime(2026, 11, 1, 4, 30), 360), ["11-01 04:30"])
        self.assertEqual(len(run("America/New_York", "*/30 * * * *", datetime(2026, 3, 8, 5, 0), 180)), 6)  # every half hour for three real hours

    def test_a_long_pause_does_not_replay_old_minutes(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp, model_factory=lambda n: MockModel(["ok"]), encrypt_keychain=False, sync=False)
            try:
                ws.create_agent("alice", persona="p")
                ws.create_room("team", ["alice", "you"])
                ws.set_timezone("America/New_York", 0)
                ws.add_job("alice", "team", "30 2 * * *", "go")
                scheduler = Scheduler(ws)
                before, after = calendar.timegm(datetime(2026, 3, 8, 5, 0).timetuple()), calendar.timegm(datetime(2026, 3, 8, 7, 5).timetuple())
                scheduler.tick(before)
                self.assertEqual(scheduler.tick(after), 0)  # the process was asleep for two hours: not a clock jump, no replay
            finally:
                ws.close()


if __name__ == "__main__":
    unittest.main()
