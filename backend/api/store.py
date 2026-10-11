"""
Schedule store: reads and writes the list of watering schedules.

One schedule looks like:
    {
        "id": "a1b2c3d4",               # unique id we generate; used to delete
        "zone": 1,                      # 1 or 2
        "days": ["mon", "wed", "sat"],  # any subset of mon..sun
        "time": "21:00",                # 24-hour HH:MM, local time
        "minutes": 20,                  # how long to water
        "is_enabled": true              # false = keep it, but don't arm it
    }
"""

import json
import logging
import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

log = logging.getLogger("melnor.store")

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_SCHEDULES_PATH = _DATA_DIR / "schedules.json"

# Serializes every read-modify-write of schedules.json. main.py runs
# add_schedule / delete_schedule on worker threads (asyncio.to_thread), so two
# requests close together (two tabs, a double-click) could otherwise both load
# the file, both pass the overlap check, and the second save would silently
# drop the first schedule. A threading lock (not asyncio) because the callers
# are threads. Reentrant so a locked function can call another locked one.
_lock = threading.RLock()


class _Unreadable(Exception):
    """schedules.json exists but isn't a readable JSON list."""


def _read_file():
    """Return the parsed list from schedules.json, [] if the file is missing.

    Raises _Unreadable for a corrupt file (bad JSON, I/O error, or valid JSON
    that isn't a list, e.g. `{}`).
    """
    if not _SCHEDULES_PATH.exists():
        return []
    try:
        with open(_SCHEDULES_PATH, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as error:
        raise _Unreadable(str(error)) from error
    if not isinstance(data, list):
        raise _Unreadable(f"expected a JSON list, got {type(data).__name__}")
    return data


def load_schedules():
    """Return the list of schedules (a list of dicts). Empty list if none yet.

    If the file is missing we return []. If it exists but is unreadable or not
    valid JSON (e.g. a bad hand-edit, or a truncated file), we LOG the problem
    and also return [] rather than raising, otherwise a single corrupt file
    would crash the whole server on startup (the scheduler reads this on boot)
    and break every schedule endpoint. Returning [] keeps the server alive; the
    error in the log tells you to go fix the file.
    """
    try:
        schedules = _read_file()
    except _Unreadable:
        log.exception("Could not read %s, treating as empty", _SCHEDULES_PATH)
        return []
    return [_migrate(s) for s in schedules]


def _migrate(sched):
    """Upgrade a schedule record written by an older version in place.

    The flag used to be called `enabled`; it's `is_enabled` now. A file saved
    before the rename still loads, and the next save writes the new name.
    """
    if isinstance(sched, dict) and "enabled" in sched and "is_enabled" not in sched:
        sched["is_enabled"] = sched.pop("enabled")
    return sched


def _backup_if_unreadable():
    """If schedules.json exists but can't be parsed, copy it to
    schedules.json.corrupt-YYYYMMDD-HHMMSS before it gets overwritten.
    Returns the backup path, or None if no backup was needed."""
    try:
        _read_file()
        return None
    except _Unreadable:
        pass
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = _SCHEDULES_PATH.with_name(f"{_SCHEDULES_PATH.name}.corrupt-{stamp}")
    shutil.copy2(_SCHEDULES_PATH, backup)
    log.error(
        "%s was unreadable; saved a copy to %s before overwriting it",
        _SCHEDULES_PATH, backup,
    )
    return backup


def save_schedules(schedules):
    """Write the whole list back to disk SAFELY (an "atomic write").

    Why the temp-file dance: if power died halfway through writing the real
    file, we'd be left with a half-written, corrupt schedules.json. Instead we
    write a temporary file first, then os.replace() renames it over the real
    one. That rename is ATOMIC on every OS, it either fully happens or not at
    all, so the real file is always a complete version (old or new, never a
    torn half).
    """
    # backend/data/ is gitignored and may not exist yet on a fresh checkout.
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    # A corrupt file loads as [] (see load_schedules), so the first save after
    # that would replace it with just the new record and the originals would
    # be gone for good. Copy it aside first so it can be repaired by hand.
    _backup_if_unreadable()

    # Write the temp file in the SAME folder, so os.replace stays on one disk
    # (a rename across disks isn't atomic).
    tmp_path = _SCHEDULES_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(schedules, f, indent=2)
        f.flush()                # push Python's buffer to the OS...
        os.fsync(f.fileno())     # ...and force the OS to write it to the disk.
    os.replace(tmp_path, _SCHEDULES_PATH)  # atomic swap into place


# --- Overlap validation ------------------------------------------------------
#
# Two schedules "overlap" if, on any weekday they share, their watering windows
# touch, REGARDLESS of zone. Running two zones at once drops the water
# pressure, so we forbid any time overlap across the whole system, not just per
# zone. We model each run as an interval on a weekly timeline measured in
# minutes from Monday 00:00 (0) up to Sunday 24:00 (10080); a run that spills
# past the end of the week wraps back to the start, so a late Sunday run
# correctly conflicts with an early Monday one.

_MINUTES_PER_DAY = 24 * 60
_MINUTES_PER_WEEK = 7 * _MINUTES_PER_DAY
_DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class ScheduleConflict(Exception):
    """Raised when a schedule would overlap an existing one (in time, any zone).

    The web layer catches this and returns an HTTP 409 (Conflict).
    """


def _weekly_intervals(sched):
    """Return a schedule's watering windows as (start, end) minute ranges on the
    weekly timeline. A window that runs past the end of the week is split into
    two plain ranges (the tail wraps to Monday 00:00) so callers can use simple
    overlap math instead of circular arithmetic."""
    hour, minute = sched["time"].split(":")
    start_of_day = int(hour) * 60 + int(minute)

    intervals = []
    for day in (_DAY_ORDER.index(d) for d in sched["days"]):
        start = day * _MINUTES_PER_DAY + start_of_day
        end = start + sched["minutes"]
        if end <= _MINUTES_PER_WEEK:
            intervals.append((start, end))
        else:
            # Wrapped past Sunday midnight -> "rest of week" + "start of week".
            intervals.append((start, _MINUTES_PER_WEEK))
            intervals.append((0, end - _MINUTES_PER_WEEK))
    return intervals


def _ranges_overlap(a, b):
    """True if two (start, end) minute ranges intersect. Touching end-to-start
    (e.g. 21:00-21:20 then 21:20-21:40) is NOT an overlap."""
    return a[0] < b[1] and b[0] < a[1]


def find_conflict(candidate):
    """Return an existing schedule that `candidate` would overlap in time, or
    None. Overlap is checked across ALL zones (two zones running at once drops
    the water pressure). Only ENABLED schedules count, a paused schedule never
    fires, so it can't clash and a paused candidate conflicts with nothing."""
    if not candidate.get("is_enabled", True):
        return None  # a schedule that won't fire can't clash with anything

    candidate_windows = _weekly_intervals(candidate)
    for other in load_schedules():
        if not isinstance(other, dict) or not other.get("is_enabled", True):
            continue
        try:
            other_windows = _weekly_intervals(other)
        except (KeyError, ValueError, TypeError, AttributeError):
            # A hand-edited record like "time": "9am" or days: ["monday"].
            # The scheduler skips it too (it never fires), so it can't clash;
            # skipping keeps one bad record from 500-ing every create.
            log.warning("Skipping unusable schedule record in overlap check: %r", other)
            continue
        for cw in candidate_windows:
            if any(_ranges_overlap(cw, ow) for ow in other_windows):
                return other
    return None


def _conflict_message(conflict):
    """Human-readable 'this clashes with ...' text for the 409 response."""
    return (
        f"Overlaps schedule {conflict['id']} "
        f"(zone {conflict['zone']}, {conflict['days']} @ {conflict['time']} "
        f"for {conflict['minutes']} min)."
    )


def add_schedule(zone, days, time, minutes, is_enabled=True):
    """Create one schedule, save it, and return the new schedule dict.

    Raises ScheduleConflict if it would overlap an existing enabled schedule (in
    time, any zone)."""
    new_schedule = {
        "id": uuid.uuid4().hex[:8],  # short random unique id, e.g. "a1b2c3d4"
        "zone": zone,
        "days": days,
        "time": time,
        "minutes": minutes,
        "is_enabled": is_enabled,
    }
    # Check-then-write must be atomic, or two concurrent adds can both pass
    # the overlap check (see _lock).
    with _lock:
        conflict = find_conflict(new_schedule)
        if conflict is not None:
            raise ScheduleConflict(_conflict_message(conflict))

        schedules = load_schedules()
        schedules.append(new_schedule)
        save_schedules(schedules)
    return new_schedule


def delete_schedule(schedule_id):
    """Remove the schedule with this id. Return True if one was actually removed."""
    with _lock:
        schedules = load_schedules()
        # Keep every schedule EXCEPT the one whose id matches (a list comprehension).
        # isinstance guard: a junk entry (e.g. a bare string) is kept as-is
        # rather than crashing the delete with a TypeError.
        remaining = [
            s for s in schedules
            if not (isinstance(s, dict) and s.get("id") == schedule_id)
        ]
        if len(remaining) == len(schedules):
            return False  # nothing matched that id
        save_schedules(remaining)
    return True
