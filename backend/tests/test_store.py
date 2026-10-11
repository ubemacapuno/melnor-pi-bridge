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
    store.add_schedule(1, ["mon"], "21:00", 30, is_enabled=False)
    store.add_schedule(2, ["mon"], "21:00", 30)
    assert len(store.load_schedules()) == 2


def test_paused_candidate_never_conflicts(temp_store):
    # Adding a disabled schedule that overlaps an active one is allowed.
    store.add_schedule(1, ["mon"], "21:00", 30)
    store.add_schedule(1, ["mon"], "21:00", 30, is_enabled=False)
    assert len(store.load_schedules()) == 2


# --- interval math edge case (the wrap split) ---------------------------------

def test_weekly_intervals_wrap_split():
    # Sun 23:00 = 6*1440 + 1380 = 10020; +240 = 10260 > 10080 (end of week),
    # so it must split into (10020, 10080) plus the wrapped (0, 180).
    intervals = store._weekly_intervals({"days": ["sun"], "time": "23:00", "minutes": 240})
    assert (10020, 10080) in intervals
    assert (0, 180) in intervals


def test_load_migrates_legacy_enabled_key(tmp_path, monkeypatch):
    """A schedules.json written before the rename (`enabled`) still loads,
    with the flag exposed as `is_enabled`."""
    import json
    monkeypatch.setattr(store, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_SCHEDULES_PATH", tmp_path / "schedules.json")
    legacy = [{"id": "old1", "zone": 1, "days": ["mon"], "time": "21:00", "minutes": 20, "enabled": False}]
    (tmp_path / "schedules.json").write_text(json.dumps(legacy))
    loaded = store.load_schedules()
    assert loaded[0]["is_enabled"] is False
    assert "enabled" not in loaded[0]


# --- concurrency (store lock) ----------------------------------------------

import threading


def _run_in_threads(n, target):
    """Start n threads together (behind a barrier) and collect results/errors."""
    barrier = threading.Barrier(n)
    results, errors = [], []

    def worker(i):
        barrier.wait()
        try:
            results.append(target(i))
        except Exception as error:  # noqa: BLE001 - collected for the assert
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, errors


def test_concurrent_adds_are_all_saved(temp_store):
    # 12 non-overlapping slots, 2 hours apart on Monday
    results, errors = _run_in_threads(
        12, lambda i: store.add_schedule(1, ["mon"], f"{i * 2:02d}:00", 10)
    )
    assert errors == []
    saved_ids = {s["id"] for s in store.load_schedules()}
    assert saved_ids == {r["id"] for r in results}
    assert len(saved_ids) == 12


def test_concurrent_overlapping_adds_only_one_wins(temp_store):
    results, errors = _run_in_threads(
        10, lambda i: store.add_schedule(1 + i % 2, ["tue"], "21:00", 30)
    )
    assert len(results) == 1
    assert len(errors) == 9
    assert all(isinstance(e, store.ScheduleConflict) for e in errors)
    assert len(store.load_schedules()) == 1


def test_concurrent_add_and_delete_keep_each_other(temp_store):
    existing = [store.add_schedule(2, ["wed"], f"{i * 2:02d}:00", 10) for i in range(6)]

    def work(i):
        if i < 6:
            return store.delete_schedule(existing[i]["id"])
        return store.add_schedule(1, ["thu"], f"{(i - 6) * 2:02d}:00", 10)

    _, errors = _run_in_threads(12, work)
    assert errors == []
    remaining = store.load_schedules()
    assert {s["days"][0] for s in remaining} == {"thu"}
    assert len(remaining) == 6


# --- corrupt file is backed up, not destroyed ------------------------------

def _backups(temp_store):
    return sorted(temp_store.parent.glob("schedules.json.corrupt-*"))


def test_add_over_corrupt_file_backs_it_up(temp_store):
    original = '[{"id": "keep1", "zone": 1, "days": ["mon"], "time": "21:00", "minut'
    temp_store.write_text(original)

    store.add_schedule(1, ["fri"], "06:00", 15)

    backups = _backups(temp_store)
    assert len(backups) == 1
    assert backups[0].read_text() == original  # byte-for-byte copy
    assert len(store.load_schedules()) == 1     # new file is valid


def test_delete_over_corrupt_file_does_not_touch_it(temp_store):
    temp_store.write_text("{ broken")
    assert store.delete_schedule("anything") is False  # nothing to delete, no save
    assert temp_store.read_text() == "{ broken"
    assert _backups(temp_store) == []


def test_non_list_json_is_treated_as_corrupt(temp_store):
    temp_store.write_text('{"id": "not-a-list"}')
    assert store.load_schedules() == []
    store.add_schedule(1, ["sat"], "07:00", 10)
    assert len(_backups(temp_store)) == 1


def test_valid_file_is_not_backed_up(temp_store):
    store.add_schedule(1, ["mon"], "21:00", 20)
    store.add_schedule(1, ["tue"], "21:00", 20)
    assert _backups(temp_store) == []


# --- malformed records don't break create / delete -------------------------

import json


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "b1", "zone": 1, "days": ["mon"], "time": "9am", "minutes": 20},
        {"id": "b2", "zone": 1, "days": ["monday"], "time": "21:00", "minutes": 20},
        {"id": "b3", "zone": 1, "days": ["mon"], "time": "21:00"},  # no minutes
        "just a string",
    ],
    ids=["bad-time", "bad-day", "missing-minutes", "not-a-dict"],
)
def test_bad_record_does_not_block_add_or_delete(temp_store, bad):
    good = {"id": "g1", "zone": 2, "days": ["sun"], "time": "06:00", "minutes": 10, "is_enabled": True}
    temp_store.write_text(json.dumps([bad, good]))

    created = store.add_schedule(1, ["mon"], "21:00", 20)  # no 500
    assert store.delete_schedule("g1") is True              # no TypeError

    saved = store.load_schedules()
    assert bad in saved                                     # kept for hand repair
    assert [s["id"] for s in saved if isinstance(s, dict)][-1] == created["id"]


def test_good_records_still_conflict_next_to_bad_ones(temp_store):
    bad = {"id": "b1", "zone": 1, "days": ["mon"], "time": "9am", "minutes": 20}
    good = {"id": "g1", "zone": 2, "days": ["mon"], "time": "21:00", "minutes": 30, "is_enabled": True}
    temp_store.write_text(json.dumps([bad, good]))
    with pytest.raises(store.ScheduleConflict):
        store.add_schedule(1, ["mon"], "21:15", 10)
