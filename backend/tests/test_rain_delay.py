"""
Tests for the rain delay (api/rain_delay.py), its endpoints, and the
scheduler skipping runs while it's active.
"""

import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from api import main, melnor, rain_delay, scheduler, store

NOW = datetime(2026, 11, 1, 22, 0, 0).astimezone()


@pytest.fixture
def delay_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(rain_delay, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(rain_delay, "_RAIN_DELAY_PATH", tmp_path / "rain_delay.json")
    clock = {"now": NOW}
    monkeypatch.setattr(rain_delay, "_now", lambda: clock["now"])
    return clock


@pytest.fixture
def client(delay_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_SCHEDULES_PATH", tmp_path / "schedules.json")
    monkeypatch.setattr(scheduler, "_scheduler", None)
    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "reload_jobs", lambda: None)
    with TestClient(main.app) as c:
        yield c


# --- module ---------------------------------------------------------------

def test_inactive_when_no_file(delay_dir):
    assert rain_delay.status() == {"is_active": False, "until": None}


def test_start_lasts_24_hours(delay_dir):
    result = rain_delay.start()
    assert result["is_active"] is True
    until = datetime.fromisoformat(result["until"])
    assert until == NOW + timedelta(hours=24)
    # carries a UTC offset so any browser parses it correctly
    assert result["until"][-6] in "+-"


def test_expires_on_its_own(delay_dir):
    rain_delay.start()
    delay_dir["now"] = NOW + timedelta(hours=23, minutes=59)
    assert rain_delay.is_active() is True
    delay_dir["now"] = NOW + timedelta(hours=24)
    assert rain_delay.status() == {"is_active": False, "until": None}


def test_start_again_restarts_window(delay_dir):
    rain_delay.start()
    delay_dir["now"] = NOW + timedelta(hours=10)
    result = rain_delay.start()
    assert datetime.fromisoformat(result["until"]) == NOW + timedelta(hours=34)


def test_cancel(delay_dir):
    rain_delay.start()
    assert rain_delay.cancel() == {"is_active": False, "until": None}
    assert rain_delay.cancel() == {"is_active": False, "until": None}  # idempotent


@pytest.mark.parametrize("content", ["{not json", "[]", '{"until": "tomorrow"}', "{}"])
def test_corrupt_file_means_no_delay(delay_dir, content):
    rain_delay._RAIN_DELAY_PATH.write_text(content)
    assert rain_delay.status() == {"is_active": False, "until": None}


# --- endpoints ------------------------------------------------------------

def test_endpoints_roundtrip(client):
    assert client.get("/api/rain-delay").json() == {"is_active": False, "until": None}

    started = client.post("/api/rain-delay")
    assert started.status_code == 200
    assert started.json()["is_active"] is True
    assert client.get("/api/rain-delay").json() == started.json()

    cancelled = client.delete("/api/rain-delay")
    assert cancelled.json() == {"is_active": False, "until": None}


# --- scheduler ------------------------------------------------------------

@pytest.fixture
def water_calls(monkeypatch):
    calls = []

    async def fake_water_zone(zone, minutes):
        calls.append((zone, minutes))

    monkeypatch.setattr(melnor, "water_zone", fake_water_zone)
    return calls


def test_scheduled_run_skipped_during_delay(delay_dir, water_calls):
    rain_delay.start()
    asyncio.run(scheduler._fire("abc", 1, 20))
    assert water_calls == []


def test_scheduled_run_fires_without_delay(delay_dir, water_calls):
    asyncio.run(scheduler._fire("abc", 1, 20))
    assert water_calls == [(1, 20)]


def test_scheduled_run_fires_after_delay_expires(delay_dir, water_calls):
    rain_delay.start()
    delay_dir["now"] = NOW + timedelta(hours=25)
    asyncio.run(scheduler._fire("abc", 2, 15))
    assert water_calls == [(2, 15)]
