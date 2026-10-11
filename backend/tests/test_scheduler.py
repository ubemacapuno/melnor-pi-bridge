"""
Scheduler wiring tests (api/scheduler.py)
"""

import json

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from api import scheduler, store


@pytest.fixture
def schedules_file(tmp_path, monkeypatch):
    """Point the store at a temp file and reset the scheduler global."""
    path = tmp_path / "schedules.json"
    monkeypatch.setattr(store, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_SCHEDULES_PATH", path)
    monkeypatch.setattr(scheduler, "_scheduler", None)
    return path


def _reload_and_inspect():
    """Start a scheduler, reload jobs from the store, and return one (id, args)
    tuple per armed job. Runs inside a fresh event loop and shuts down cleanly."""
    import asyncio

    async def run():
        scheduler._scheduler = AsyncIOScheduler()
        scheduler._scheduler.start()
        scheduler.reload_jobs()
        armed = [(j.id, tuple(j.args)) for j in scheduler._scheduler.get_jobs()]
        scheduler._scheduler.shutdown(wait=False)
        return armed

    return asyncio.run(run())


def test_arms_enabled_schedule(schedules_file):
    created = store.add_schedule(1, ["mon", "wed"], "21:00", 20)
    armed = _reload_and_inspect()
    assert len(armed) == 1
    job_id, args = armed[0]
    assert job_id == created["id"]
    # _fire is called as _fire(schedule_id, zone, minutes).
    assert args == (created["id"], 1, 20)


def test_skips_disabled_schedule(schedules_file):
    store.add_schedule(1, ["mon"], "21:00", 20, is_enabled=False)
    assert _reload_and_inspect() == []


def test_skips_malformed_record_but_arms_good_one(schedules_file):
    # Write the file directly so we can plant a BAD record (add_schedule would
    # reject it). "9am" is not HH:MM, so arming this one raises, but the good
    # one must still be armed and the server must not crash.
    good = {"id": "good", "zone": 1, "days": ["mon"], "time": "21:00", "minutes": 20, "is_enabled": True}
    bad = {"id": "bad", "zone": 2, "days": ["tue"], "time": "9am", "minutes": 10, "is_enabled": True}
    schedules_file.write_text(json.dumps([good, bad]))

    armed = _reload_and_inspect()
    assert [job_id for job_id, _ in armed] == ["good"]


def test_reload_is_idempotent(schedules_file):
    # Re-arming the same store twice shouldn't duplicate jobs (ids are reused).
    store.add_schedule(1, ["mon"], "21:00", 20)
    import asyncio

    async def run():
        scheduler._scheduler = AsyncIOScheduler()
        scheduler._scheduler.start()
        scheduler.reload_jobs()
        scheduler.reload_jobs()  # second time
        count = len(scheduler._scheduler.get_jobs())
        scheduler._scheduler.shutdown(wait=False)
        return count

    assert asyncio.run(run()) == 1
