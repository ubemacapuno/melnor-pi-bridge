"""
Logic that talks to the Melnor timer.

!IMPORTANT: the Melnor phone app must be CLOSED. Only one thing can hold the Bluetooth connection at a time.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta

from bleak.exc import BleakError
from melnor_bluetooth.device import Device
from melnor_bluetooth.utils import date as melnor_date

# Logs under "melnor.ble" so they flow up to the "melnor" handler that main.py
# sets up (see the logging block there). This is how the retry warnings below
# show up in the server console.
_log = logging.getLogger("melnor.ble")

# A "relative import": the leading dot means "from THIS package (api)".
# So this grabs scan_for_melnor from api/scan.py.
from .scan import scan_for_melnor
from . import state_cache

# Weekday name -> Python weekday number (0=Mon .. 6=Sun). The web layer uses
# this to validate the incoming day before we touch Bluetooth.
WEEKDAYS = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


ble_lock = asyncio.Lock()


class TimerNotFound(Exception):
    """Raised when we can't find or connect to the timer over Bluetooth.

    The web layer catches this and turns it into a friendly HTTP error
    instead of a 500 crash.
    """


async def _find_device():
    """Scan and return the first Melnor BLE device found (or None).

    The leading underscore is a Python convention meaning "internal helper --
    not part of the public API of this module." Nothing enforces it; it's a
    hint to other developers.
    """
    found = await scan_for_melnor(timeout_seconds=15)
    if not found:
        return None
    return next(iter(found.values()))


_CONNECT_ATTEMPTS = 5

# Errors worth retrying while REACHING the timer (scan, connect, fetch_state).
# Besides our own TimerNotFound and bleak's BleakError, a link that drops
# mid-read surfaces as a timeout (TimeoutError, which is an OSError) or an
# EOFError from the GATT layer. Programming errors (AttributeError, etc.) are
# deliberately NOT here, so a real bug fails fast instead of being retried
# five times and disguised as "timer not found". CancelledError is a
# BaseException, so a cancelled request is never swallowed either.
_RETRYABLE_CONNECT_ERRORS = (TimerNotFound, BleakError, EOFError, OSError)


async def _connect_once():
    """One attempt: scan, connect, refresh state, and return a live Device.

    Raises TimerNotFound (or a BleakError) if the timer can't be reached. The
    retrying wrapper _connect() below is what callers actually use.

    Whoever ends up with the returned device is responsible for calling
    `await device.disconnect()` when done (callers do that in a `finally:`).
    """
    ble_device = await _find_device()
    if ble_device is None:
        raise TimerNotFound(
            "Could not find the timer. Is it awake? Is the phone app closed?"
        )

    device = Device(ble_device)
    await device.connect(retry_attempts=4)

    if not device.is_connected:
        raise TimerNotFound(
            "Found the timer but couldn't connect. Close the phone app and retry."
        )

    # Pull the latest state (battery, valve status, schedule) from the device.
    # If this fails we must NOT leave a half-open connection behind before the
    # retry opens a new one, so disconnect and re-raise.
    try:
        await device.fetch_state()
    except Exception:
        try:
            await device.disconnect()
        except Exception:
            pass
        raise
    return device


async def _connect():
    """Scan + connect, retrying up to _CONNECT_ATTEMPTS times on failure.
    We retry only reaching the timer. Once connected, the caller's own
    read/write runs exactly once. We never blindly re-run a write that may
    have half-finished. After all attempts fail we raise a single TimerNotFound, 
    which the web layer turns into an HTTP 503.
    """
    last_error = None
    for attempt in range(1, _CONNECT_ATTEMPTS + 1):
        try:
            return await _connect_once()
        except _RETRYABLE_CONNECT_ERRORS as error:
            # Remember the failure and try again immediately (no backoff). The
            # 15s scan timeout inside _connect_once() paces the retries for us.
            last_error = error
            _log.warning(
                "Timer connect attempt %d/%d failed: %s",
                attempt,
                _CONNECT_ATTEMPTS,
                error,
            )

    raise TimerNotFound(
        f"Could not reach the timer after {_CONNECT_ATTEMPTS} attempts. "
        "Is it awake? Is the phone app closed?"
    ) from last_error


async def _disconnect_quietly(device):
    """Disconnect, but never raise.

    By the time a caller's `finally:` runs, the real work (a read, or a valve
    write that has already opened or closed the valve) is done. If the link
    has already dropped, disconnect() can raise BleakError; letting that
    escape would report a watering that actually started as a failure, and
    the user might press Start again. Log it and move on.
    """
    try:
        await device.disconnect()
    except Exception:
        _log.warning("Disconnect after a finished command failed", exc_info=True)


def _get_zone(device, zone_number):
    """Return the Valve object for zone 1 or 2 (device.zone1 / device.zone2)."""
    return getattr(device, f"zone{zone_number}")


async def water_zone(zone_number, minutes):
    """Turn a zone ON for `minutes` of manual watering (mirrors CLI `on`).

    Writes the change to the timer with push_state() and returns a small
    dict describing the result so the web layer can echo it back as JSON.
    """
    device = await _connect()
    try:
        zone = _get_zone(device, zone_number)
        zone.is_watering = True
        zone.manual_watering_minutes = minutes
        await device.push_state()  # writes the change to the timer
        await _remember_after_command(device, zone_number, minutes)
        return {
            "zone": zone_number,
            "is_watering": zone.is_watering,
            "minutes": minutes,
        }
    finally:
        await _disconnect_quietly(device)


async def turn_off_zone(zone_number):
    """Turn a zone OFF (mirrors CLI `off`).

    Stops manual watering but LEAVES any schedule enabled, so a scheduled
    cycle can still run later. Use stop_zone() to also disable the schedule.
    """
    device = await _connect()
    try:
        zone = _get_zone(device, zone_number)
        zone.is_watering = False
        await device.push_state()
        await _remember_after_command(device, zone_number)
        return {"zone": zone_number, "is_watering": zone.is_watering}
    finally:
        await _disconnect_quietly(device)


async def stop_zone(zone_number):
    """Fully stop a zone: watering off AND schedule disabled (mirrors CLI `stop`).

    set_frequency_enabled(False) disables the schedule and writes the whole
    state (including is_watering) to the device in one shot.
    """
    device = await _connect()
    try:
        zone = _get_zone(device, zone_number)
        zone.is_watering = False
        await zone.set_frequency_enabled(False)
        await _remember_after_command(device, zone_number)
        return {
            "zone": zone_number,
            "is_watering": zone.is_watering,
            "is_schedule_enabled": zone.schedule_enabled,
        }
    finally:
        await _disconnect_quietly(device)


def _is_watering(zone):
    """True if water is actually flowing, manual OR a scheduled cycle.

    zone.is_watering only tracks MANUAL watering (the `on` command). A zone
    watering because of its schedule shows up in frequency.is_watering instead
    (computed from the schedule + current time), so we have to check both.
    """
    return zone.is_watering or (zone.schedule_enabled and zone.frequency.is_watering)


def _watering_remaining(zone):
    """Describe how much longer a zone will water, and which source.

    Returns {} when the zone isn't watering. Handles both MANUAL watering
    (device reports a unix `watering_end_time`) and a SCHEDULED cycle
    (`frequency.schedule_end`, a datetime).
    """
    if zone.is_watering and zone.watering_end_time:
        end_ts = zone.watering_end_time
        source = "manual"
    elif zone.schedule_enabled and zone.frequency.is_watering:
        # schedule_end is a tz-aware datetime; .timestamp() gives unix seconds.
        end_ts = zone.frequency.schedule_end.timestamp()
        source = "scheduled"
    else:
        return {}

    return _watering_fields(end_ts, source)


def _watering_fields(end_ts, source):
    """The remaining-time fields for a zone that ends at unix time `end_ts`."""
    remaining = max(int(end_ts - time.time()), 0)
    return {
        "watering_source": source,
        # .astimezone() attaches the Pi's UTC offset, so a browser in any
        # timezone (or a Pi whose timezone was never set) parses the same
        # instant instead of guessing the wall clock is its own
        "ends_at": datetime.fromtimestamp(end_ts).astimezone().isoformat(timespec="seconds"),
        "remaining_seconds": remaining,
        "remaining_minutes": round(remaining / 60, 1),
    }


def _zone_schedule(zone):
    """Return one zone's schedule as a plain dict.

    Shared by get_state() and get_schedule() so the schedule shape lives in
    exactly one place (DRY). The web layer turns this dict into JSON.
    """
    if not zone.schedule_enabled:
        return {"is_enabled": False}

    freq = zone.frequency
    next_cycle = zone.next_cycle
    return {
        "is_enabled": True,
        # The library warns the DATE is unreliable; the time-of-day
        # and weekday are what we trust.
        "start_time": str(freq.start_time),
        "interval_hours": freq.interval_hours,
        "duration_minutes": freq.duration_minutes,
        "next_run": next_cycle.strftime("%A %H:%M") if next_cycle else None,
    }


def _next_occurrence(weekday, hour, minute):
    """Return the next datetime on `weekday` (0=Mon..6=Sun) at hour:minute.

    If that moment already passed today, jump to next week.
    """
    now = datetime.now()
    days_ahead = (weekday - now.weekday()) % 7
    target = (now + timedelta(days=days_ahead)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if target <= now:
        target += timedelta(days=7)
    return target


async def set_zone_schedule(zone_number, weekday, hour, minute, minutes):
    """Set a WEEKLY schedule for a zone (mirrors CLI `set-schedule`).

    Waters every `weekday` (0=Mon..6=Sun) at hour:minute for `minutes`. The
    device has no weekday field, so we encode it as a start timestamp on that
    weekday and repeat every 168 hours (once per week).
    """
    device = await _connect()
    try:
        zone = _get_zone(device, zone_number)
        freq = zone.frequency

        target = _next_occurrence(weekday, hour, minute)

        # The public setter only changes the time-of-day, not the weekday, so
        # we write the raw start timestamp directly.
        freq._attr_raw_start_time = melnor_date.from_start_time(target)
        # These setters cap at the device's limits and recompute the next run.
        freq.duration_minutes = minutes
        freq.interval_hours = 168  # 168 hours = once per week

        zone.is_watering = False  # make sure manual watering isn't left on
        # Enabling the schedule writes the whole frequency block to the device.
        await zone.set_frequency_enabled(True)

        return {"zone": zone_number, "schedule": _zone_schedule(zone)}
    finally:
        await _disconnect_quietly(device)


def _zone_state(zone):
    """Build one zone's live-state dict: watering (manual OR scheduled),
    the remaining-time/source fields when watering, and its schedule."""
    return {
        "is_watering": _is_watering(zone),
        # When watering, adds watering_source / ends_at / remaining_*; empty
        # otherwise.
        **_watering_remaining(zone),
        "schedule": _zone_schedule(zone),
    }


def _build_state(device):
    """The full GET /api/state dict for a connected device."""
    return {
        "name": device.name,
        "battery": device.battery_level,
        "zones": {str(n): _zone_state(_get_zone(device, n)) for n in (1, 2)},
    }


async def _remember(state):
    """Save `state` to the last-known-state cache (data/last_state.json).

    Runs the disk write on a thread so the fsync can't stall the event loop,
    and never raises: a failed cache write must not fail the command.
    """
    try:
        await asyncio.to_thread(state_cache.save, state)
    except Exception:
        _log.exception("Could not write the state cache")


async def _remember_after_command(device, zone_number, minutes=None):
    """Cache a snapshot right after a valve command. Never raises.

    For an OFF/STOP (`minutes` is None) the device object already reflects
    the write, so the snapshot is taken as-is. That matters for OFF: it only
    cancels MANUAL watering, so a zone mid-way through its on-device schedule
    correctly stays "watering (scheduled)" instead of being marked idle.

    For an ON, the device doesn't report the new countdown until a later read
    (its end-time register fills in a moment after the write), so we patch the
    zone as manual watering ending at now + minutes. The next real read
    overwrites this with the device's own numbers.

    The valve command has already succeeded by the time this runs, so any
    failure here is logged and swallowed rather than failing the request.
    """
    try:
        state = _build_state(device)
        if minutes:
            zone = state["zones"][str(zone_number)]
            zone["is_watering"] = True
            zone.update(_watering_fields(time.time() + minutes * 60, "manual"))
        await _remember(state)
    except Exception:
        _log.exception("Could not snapshot state after zone %s command", zone_number)


async def get_state():
    """Return battery + each zone's live watering status AND its schedule.

    One connection gets the whole picture (mirrors the CLI `state` command),
    which matters because each call is a full ~15s scan/connect cycle. The
    result is also saved to the state cache for GET /api/state/cached.
    """
    device = await _connect()
    try:
        state = _build_state(device)
        await _remember(state)
        return state
    finally:
        # `finally` runs whether the code above succeeded or raised, so we
        # never leave the Bluetooth connection open (which would block the
        # phone app and the next request).
        await _disconnect_quietly(device)


async def get_schedule():
    """Return just the watering schedule for each zone, as a dict."""
    device = await _connect()
    try:
        zones = {str(n): _zone_schedule(_get_zone(device, n)) for n in (1, 2)}
        return {"zones": zones}
    finally:
        await _disconnect_quietly(device)
