"""
Last-known device state cache.

Reading the timer is a slow (~15s) Bluetooth call, so we remember the result of
the most recent successful read (or command) in data/last_state.json. Any
client, phone, laptop, a fresh browser tab, can then fetch it instantly from
GET /api/state/cached, and the UI can keep counting down from `ends_at` without
touching Bluetooth.

The file looks like:
    {
        "read_at": "2026-10-10T22:44:38-05:00",   # when this snapshot was taken
        "state": { ...same shape as GET /api/state... }
    }

Same atomic-write pattern as store.py (temp file + os.replace) so a power cut
mid-write can't leave a torn file behind.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

log = logging.getLogger("melnor.state_cache")

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_LAST_STATE_PATH = _DATA_DIR / "last_state.json"


def load():
    """Return {"read_at": ..., "state": ...} or None if nothing cached yet.

    A missing file is normal (fresh install). An unreadable or corrupt file is
    logged and treated as empty rather than raised, the cache is a convenience
    and must never take the API down.
    """
    if not _LAST_STATE_PATH.exists():
        return None
    try:
        with open(_LAST_STATE_PATH, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        log.exception("Could not read %s, treating as empty", _LAST_STATE_PATH)
        return None
    if not isinstance(data, dict) or not isinstance(data.get("state"), dict):
        log.warning("Ignoring malformed cache file %s", _LAST_STATE_PATH)
        return None
    return data


def save(state):
    """Persist `state` (the GET /api/state dict) with a timestamp.

    `read_at` is timezone-aware ISO 8601 (with a UTC offset), so a browser in
    any timezone parses it correctly. Returns the saved entry.
    """
    entry = {
        "read_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "state": state,
    }
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = _LAST_STATE_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(entry, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, _LAST_STATE_PATH)
    return entry


def clear():
    """Delete the cache file (used by tests and if the file is ever suspect)."""
    try:
        _LAST_STATE_PATH.unlink()
    except FileNotFoundError:
        pass
