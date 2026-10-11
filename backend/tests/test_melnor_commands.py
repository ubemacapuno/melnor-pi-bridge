"""
Tests for the Bluetooth command layer (api/melnor.py) that don't need a real
timer: the state-cache snapshot after valve commands, timezone-aware end
times, and that a finished command is never reported as a failure.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from bleak.exc import BleakError

from api import melnor, state_cache


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(state_cache, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(state_cache, "_LAST_STATE_PATH", tmp_path / "last_state.json")
    return tmp_path


def _zone(*, is_watering=False, schedule_watering=False):
    """A stand-in for a melnor_bluetooth Valve.

    `schedule_watering=True` models a zone mid-way through its ON-DEVICE
    schedule: manual watering is off, but the schedule says water is flowing.
    """
    end = datetime.now(timezone.utc) + timedelta(minutes=30)
    return SimpleNamespace(
        is_watering=is_watering,
        watering_end_time=None,
        schedule_enabled=schedule_watering,
        frequency=SimpleNamespace(
            is_watering=schedule_watering,
            schedule_end=end,
            start_time="19:00:00",
            interval_hours=168,
            duration_minutes=60,
        ),
        next_cycle=None,
    )


class FakeDevice:
    """Records push_state calls; disconnect can be told to fail."""

    def __init__(self, zone1=None, zone2=None, disconnect_error=None):
        self.name = "Melnor"
        self.battery_level = 77
        self.zone1 = zone1 or _zone()
        self.zone2 = zone2 or _zone()
        self.pushes = 0
        self.disconnects = 0
        self._disconnect_error = disconnect_error

    async def push_state(self):
        self.pushes += 1

    async def disconnect(self):
        self.disconnects += 1
        if self._disconnect_error:
            raise self._disconnect_error


def _use(monkeypatch, device):
    async def fake_connect():
        return device
    monkeypatch.setattr(melnor, "_connect", fake_connect)


# --- ends_at carries a UTC offset ------------------------------------------

def test_ends_at_is_timezone_aware():
    end_ts = datetime(2026, 10, 10, 22, 0, tzinfo=timezone.utc).timestamp()
    ends_at = melnor._watering_fields(end_ts, "manual")["ends_at"]
    parsed = datetime.fromisoformat(ends_at)
    assert parsed.tzinfo is not None, ends_at
    # same instant regardless of the Pi's local timezone
    assert parsed.timestamp() == end_ts


# --- snapshot after ON / OFF ------------------------------------------------

def test_on_snapshot_patches_zone_with_countdown(monkeypatch):
    _use(monkeypatch, FakeDevice())
    asyncio.run(melnor.water_zone(1, 10))
    zones = state_cache.load()["state"]["zones"]
    z1, z2 = zones["1"], zones["2"]
    assert z1["is_watering"] is True
    assert z1["watering_source"] == "manual"
    assert 590 <= z1["remaining_seconds"] <= 600
    assert datetime.fromisoformat(z1["ends_at"]).tzinfo is not None
    assert z2["is_watering"] is False and "ends_at" not in z2


def test_off_snapshot_marks_manual_zone_idle(monkeypatch):
    _use(monkeypatch, FakeDevice(zone1=_zone(is_watering=True)))
    asyncio.run(melnor.turn_off_zone(1))
    z1 = state_cache.load()["state"]["zones"]["1"]
    assert z1["is_watering"] is False
    assert "ends_at" not in z1


def test_off_snapshot_keeps_on_device_schedule_watering(monkeypatch):
    """OFF only cancels manual watering. A zone running its on-device schedule
    keeps flowing, so the cache must not claim it's idle."""
    _use(monkeypatch, FakeDevice(zone1=_zone(schedule_watering=True)))
    asyncio.run(melnor.turn_off_zone(1))
    z1 = state_cache.load()["state"]["zones"]["1"]
    assert z1["is_watering"] is True
    assert z1["watering_source"] == "scheduled"
    assert z1["ends_at"]


# --- a finished command is never reported as a failure --------------------

def test_on_succeeds_even_if_disconnect_fails(monkeypatch):
    device = FakeDevice(disconnect_error=BleakError("link already dropped"))
    _use(monkeypatch, device)
    result = asyncio.run(melnor.water_zone(1, 5))
    assert result == {"zone": 1, "is_watering": True, "minutes": 5}
    assert device.pushes == 1 and device.disconnects == 1


def test_on_succeeds_even_if_snapshot_fails(monkeypatch):
    device = FakeDevice()
    _use(monkeypatch, device)

    def broken_build_state(_device):
        raise RuntimeError("unexpected device value")
    monkeypatch.setattr(melnor, "_build_state", broken_build_state)

    result = asyncio.run(melnor.water_zone(2, 15))
    assert result["is_watering"] is True
    assert device.pushes == 1
    assert state_cache.load() is None  # nothing cached, but no error raised


def test_on_succeeds_even_if_cache_write_fails(monkeypatch):
    _use(monkeypatch, FakeDevice())

    def broken_save(_state):
        raise OSError("disk full")
    monkeypatch.setattr(state_cache, "save", broken_save)

    assert asyncio.run(melnor.water_zone(1, 5))["is_watering"] is True


def test_push_failure_still_raises(monkeypatch):
    """Guarding the AFTER-command steps must not hide a real write failure."""
    device = FakeDevice()

    async def failing_push():
        raise BleakError("write failed")
    device.push_state = failing_push
    _use(monkeypatch, device)

    with pytest.raises(BleakError):
        asyncio.run(melnor.water_zone(1, 5))
    assert device.disconnects == 1  # still cleaned up
