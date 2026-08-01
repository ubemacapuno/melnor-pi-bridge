"""
Unit tests for the schedule store (api/store.py)
"""

import pytest

from api import store


@pytest.fixture
def temp_store(tmp_path, monkeypatch):
    """Redirect the store's file to a fresh temp path for each test."""
    path = tmp_path / "schedules.json"
    monkeypatch.setattr(store, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_SCHEDULES_PATH", path)
    return path


# --- load / save / delete ----------------------------------------------------

def test_load_missing_file_returns_empty(temp_store):
    assert store.load_schedules() == []


def test_corrupt_file_treated_as_empty(temp_store):
    # A bad hand-edit must not crash, load_schedules logs and returns [].
    temp_store.write_text("{ this is not valid json")
    assert store.load_schedules() == []


def test_add_then_load(temp_store):
    created = store.add_schedule(1, ["mon", "wed"], "21:00", 20)
    assert created["id"]  # got a generated id
    saved = store.load_schedules()
    assert len(saved) == 1
    assert saved[0]["zone"] == 1
    assert saved[0]["days"] == ["mon", "wed"]


def test_ids_are_unique(temp_store):
    a = store.add_schedule(1, ["mon"], "06:00", 10)
    b = store.add_schedule(1, ["tue"], "06:00", 10)
    assert a["id"] != b["id"]


def test_delete_existing_and_missing(temp_store):
    created = store.add_schedule(1, ["mon"], "21:00", 20)
    assert store.delete_schedule(created["id"]) is True
    assert store.load_schedules() == []
    assert store.delete_schedule("does-not-exist") is False


# --- overlap rejection --------------------------------------------------------

def test_overlap_same_zone_rejected(temp_store):
    store.add_schedule(1, ["mon"], "21:00", 30)
    with pytest.raises(store.ScheduleConflict):
        store.add_schedule(1, ["mon"], "21:15", 30)


def test_overlap_across_zones_rejected(temp_store):
    # The key new rule: different zones still conflict (water-pressure reason).
    store.add_schedule(1, ["mon"], "21:00", 30)
    with pytest.raises(store.ScheduleConflict):
        store.add_schedule(2, ["mon"], "21:15", 30)


def test_back_to_back_allowed(temp_store):
    # One ends exactly as the next begins -> NOT an overlap.
    store.add_schedule(1, ["mon"], "21:00", 20)
    store.add_schedule(2, ["mon"], "21:20", 20)
    assert len(store.load_schedules()) == 2


def test_different_days_allowed(temp_store):
    store.add_schedule(1, ["mon"], "21:00", 60)
    store.add_schedule(2, ["tue"], "21:00", 60)
    assert len(store.load_schedules()) == 2


def test_midnight_crossing_conflict(temp_store):
    # Mon 23:00 for 240 min runs until Tue 03:00, so it clashes with Tue 01:00.
    store.add_schedule(1, ["mon"], "23:00", 240)
    with pytest.raises(store.ScheduleConflict):
        store.add_schedule(2, ["tue"], "01:00", 30)


def test_sunday_wraps_into_monday_conflict(temp_store):
    # Sun 23:00 for 240 min wraps past the end of the week into Mon 00:00-03:00.
    store.add_schedule(1, ["sun"], "23:00", 240)
    with pytest.raises(store.ScheduleConflict):
        store.add_schedule(2, ["mon"], "02:00", 30)


# --- "paused" schedules are ignored by the overlap check ----------------------

def test_paused_existing_does_not_block(temp_store):
    # A disabled schedule never fires, so a new one may overlap it.
    store.add_schedule(1, ["mon"], "21:00", 30, enabled=False)
    store.add_schedule(2, ["mon"], "21:00", 30)
    assert len(store.load_schedules()) == 2


def test_paused_candidate_never_conflicts(temp_store):
    # Adding a disabled schedule that overlaps an active one is allowed.
    store.add_schedule(1, ["mon"], "21:00", 30)
    store.add_schedule(1, ["mon"], "21:00", 30, enabled=False)
    assert len(store.load_schedules()) == 2


# --- interval math edge case (the wrap split) ---------------------------------

def test_weekly_intervals_wrap_split():
    # Sun 23:00 = 6*1440 + 1380 = 10020; +240 = 10260 > 10080 (end of week),
    # so it must split into (10020, 10080) plus the wrapped (0, 180).
    intervals = store._weekly_intervals({"days": ["sun"], "time": "23:00", "minutes": 240})
    assert (10020, 10080) in intervals
    assert (0, 180) in intervals
