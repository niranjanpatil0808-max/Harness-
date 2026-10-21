from datetime import timedelta

from schedule_config import INTERVALS


def interval_for(job):
    return INTERVALS[job["frequency"]]


def next_run(job, now):
    return now + timedelta(minutes=interval_for(job))
