"""
Tests for the last-known-state cache (api/state_cache.py) and its endpoint.
"""

import json

import pytest
from fastapi.testclient import TestClient

from api import main, scheduler, state_cache, store

STATE = {
    "name": "Melnor",
    "battery": 88,
    "zones": {
        "1": {
            "is_watering": True,
            "watering_source": "manual",
            "ends_at": "2026-10-10T23:00:00",
            "remaining_seconds": 600,
            "remaining_minutes": 10.0,
            "schedule": {"is_enabled": False},
        },
        "2": {"is_watering": False, "schedule": {"is_enabled": False}},
    },
}


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(state_cache, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(state_cache, "_LAST_STATE_PATH", tmp_path / "last_state.json")
    return tmp_path


@pytest.fixture
def client(cache_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_SCHEDULES_PATH", tmp_path / "schedules.json")
    monkeypatch.setattr(scheduler, "_scheduler", None)
    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "reload_jobs", lambda: None)
    with TestClient(main.app) as c:
        yield c


# --- module ---------------------------------------------------------------

def test_load_empty_when_no_file(cache_dir):
    assert state_cache.load() is None


def test_save_then_load_roundtrip(cache_dir):
    saved = state_cache.save(STATE)
    loaded = state_cache.load()
    assert loaded == saved
    assert loaded["state"] == STATE
    # read_at carries a UTC offset so any browser parses it correctly
    assert loaded["read_at"][-6] in "+-"
    assert not (cache_dir / "last_state.json.tmp").exists()


def test_corrupt_file_treated_as_empty(cache_dir):
    (cache_dir / "last_state.json").write_text("{ not json")
    assert state_cache.load() is None


def test_malformed_shape_treated_as_empty(cache_dir):
    (cache_dir / "last_state.json").write_text(json.dumps({"state": "nope"}))
    assert state_cache.load() is None


def test_clear(cache_dir):
    state_cache.save(STATE)
    state_cache.clear()
    assert state_cache.load() is None
    state_cache.clear()  # idempotent


# --- endpoint -------------------------------------------------------------

def test_cached_endpoint_empty(client):
    r = client.get("/api/state/cached")
    assert r.status_code == 200
    assert r.json() == {"read_at": None, "state": None}


def test_cached_endpoint_returns_saved(client):
    state_cache.save(STATE)
    r = client.get("/api/state/cached")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == STATE
    assert body["read_at"]

