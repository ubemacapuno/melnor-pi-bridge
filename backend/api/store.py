"""
Schedule store: reads and writes the list of watering schedules.

One schedule looks like:
    {
        "id": "a1b2c3d4",               # unique id we generate; used to delete
        "zone": 1,                      # 1 or 2
        "days": ["mon", "wed", "sat"],  # any subset of mon..sun
        "time": "21:00",                # 24-hour HH:MM, local time
        "minutes": 20,                  # how long to water
        "enabled": true                 # false = keep it, but don't arm it
    }
"""

import json
import logging
import os
import uuid
from pathlib import Path

log = logging.getLogger("melnor.store")

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_SCHEDULES_PATH = _DATA_DIR / "schedules.json"


def load_schedules():
    """Return the list of schedules (a list of dicts). Empty list if none yet.

    If the file is missing we return []. If it exists but is unreadable or not
    valid JSON (e.g. a bad hand-edit, or a truncated file), we LOG the problem
    and also return [] rather than raising, otherwise a single corrupt file
    would crash the whole server on startup (the scheduler reads this on boot)
    and break every schedule endpoint. Returning [] keeps the server alive; the
    error in the log tells you to go fix the file.
    """
    if not _SCHEDULES_PATH.exists():
        return []
    # Read the file and turn its JSON text back into Python lists/dicts.
    try:
        with open(_SCHEDULES_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        log.exception("Could not read %s, treating as empty", _SCHEDULES_PATH)
        return []


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
    if not candidate.get("enabled", True):
        return None  # a schedule that won't fire can't clash with anything

    candidate_windows = _weekly_intervals(candidate)
    for other in load_schedules():
        if not other.get("enabled", True):
            continue
        for cw in candidate_windows:
            if any(_ranges_overlap(cw, ow) for ow in _weekly_intervals(other)):
                return other
    return None


def _conflict_message(conflict):
    """Human-readable 'this clashes with ...' text for the 409 response."""
    return (
        f"Overlaps schedule {conflict['id']} "
        f"(zone {conflict['zone']}, {conflict['days']} @ {conflict['time']} "
        f"for {conflict['minutes']} min)."
    )


def add_schedule(zone, days, time, minutes, enabled=True):
    """Create one schedule, save it, and return the new schedule dict.

    Raises ScheduleConflict if it would overlap an existing enabled schedule (in
    time, any zone)."""
    new_schedule = {
        "id": uuid.uuid4().hex[:8],  # short random unique id, e.g. "a1b2c3d4"
        "zone": zone,
        "days": days,
        "time": time,
        "minutes": minutes,
        "enabled": enabled,
    }
    conflict = find_conflict(new_schedule)
    if conflict is not None:
        raise ScheduleConflict(_conflict_message(conflict))

    schedules = load_schedules()
    schedules.append(new_schedule)
    save_schedules(schedules)
    return new_schedule


def delete_schedule(schedule_id):
    """Remove the schedule with this id. Return True if one was actually removed."""
    schedules = load_schedules()
    # Keep every schedule EXCEPT the one whose id matches (a list comprehension).
    remaining = [s for s in schedules if s["id"] != schedule_id]
    if len(remaining) == len(schedules):
        return False  # nothing matched that id
    save_schedules(remaining)
    return True
