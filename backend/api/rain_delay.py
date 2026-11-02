"""
Rain delay: pause every Pi-side schedule for a while (24 hours by default).

While a delay is active, scheduler._fire() skips its watering. 
Manual watering from the web UI still works, a rain delay
only stops the AUTOMATIC runs. The delay ends on its own at `until`; nothing
has to wake up and clear it, because every check compares against the clock.

This is enforced on the Pi, not on the timer, the melnor-bluetooth library has
no rain-delay command.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("melnor.rain_delay")

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_RAIN_DELAY_PATH = _DATA_DIR / "rain_delay.json"

DEFAULT_HOURS = 24


def _now():
    """Timezone-aware local time. Its own function so tests can move the clock."""
    return datetime.now().astimezone()


def _load_until():
    """Return the saved end time as an aware datetime, or None.

    A missing file means no delay. A corrupt file is logged and treated as no
    delay: failing open (schedules run) is safer for the garden than a bad file
    silently skipping watering forever.
    """
    if not _RAIN_DELAY_PATH.exists():
        return None
    try:
        with open(_RAIN_DELAY_PATH, "r") as f:
            until = datetime.fromisoformat(json.load(f)["until"])
    except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError):
        log.exception("Could not read %s, treating as no delay", _RAIN_DELAY_PATH)
        return None
    if until.tzinfo is None:
        until = until.astimezone()  # treat a hand-written naive time as local
    return until


def status():
    """{"is_active": bool, "until": ISO string or None}.

    An expired delay reports as inactive with until=None, so clients never
    have to compare timestamps themselves.
    """
    until = _load_until()
    if until is None or until <= _now():
        return {"is_active": False, "until": None}
    return {"is_active": True, "until": until.isoformat(timespec="seconds")}


def is_active():
    return status()["is_active"]


def start(hours=DEFAULT_HOURS):
    """Start (or restart) a delay ending `hours` from now. Returns status().

    Pressing it again while active restarts the full window from now rather
    than stacking, which is what "it rained again" usually means.
    """
    until = _now() + timedelta(hours=hours)
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = _RAIN_DELAY_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump({"until": until.isoformat(timespec="seconds")}, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, _RAIN_DELAY_PATH)
    log.info("Rain delay started, schedules paused until %s", until)
    return status()


def cancel():
    """End any delay now. Returns status()."""
    try:
        _RAIN_DELAY_PATH.unlink()
        log.info("Rain delay cancelled")
    except FileNotFoundError:
        pass
    return status()
