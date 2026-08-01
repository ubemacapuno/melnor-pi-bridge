"""
Tests for the HTTP layer for scheduling (api/main.py)
"""

import pytest
from fastapi.testclient import TestClient

from api import main, scheduler, store

# A valid body we can tweak per-test.
VALID = {"zone": 1, "days": ["mon", "wed"], "time": "21:00", "minutes": 20}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_SCHEDULES_PATH", tmp_path / "schedules.json")
    # Keep the real scheduler out of the web tests.
    monkeypatch.setattr(scheduler, "_scheduler", None)
    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "reload_jobs", lambda: None)
    with TestClient(main.app) as c:
        yield c


# --- happy path ---------------------------------------------------------------

def test_create_returns_200_and_echoes(client):
    r = client.post("/api/schedules", json=VALID)
    assert r.status_code == 200
    body = r.json()
    assert body["id"]                      # a generated id came back
    assert body["days"] == ["mon", "wed"]
    assert body["enabled"] is True         # defaulted


def test_list_returns_added(client):
    client.post("/api/schedules", json=VALID)
    r = client.get("/api/schedules")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_delete_then_404(client):
    created = client.post("/api/schedules", json=VALID).json()
    assert client.delete(f"/api/schedules/{created['id']}").status_code == 200
    assert client.get("/api/schedules").json() == []
    assert client.delete("/api/schedules/does-not-exist").status_code == 404


# --- overlap ------------------------------------------------------------------

def test_overlap_returns_409(client):
    client.post("/api/schedules", json=VALID)                      # mon 21:00-21:20
    clash = {**VALID, "days": ["mon"], "time": "21:10"}            # overlaps
    r = client.post("/api/schedules", json=clash)
    assert r.status_code == 409
    assert "Overlaps" in r.json()["detail"]


def test_cross_zone_overlap_returns_409(client):
    client.post("/api/schedules", json=VALID)                      # zone 1
    clash = {**VALID, "zone": 2, "days": ["mon"], "time": "21:10"} # zone 2, still clashes
    assert client.post("/api/schedules", json=clash).status_code == 409


# --- validation (422) ---------------------------------------------------------

def test_bad_weekday_422(client):
    assert client.post("/api/schedules", json={**VALID, "days": ["funday"]}).status_code == 422


def test_bad_time_422(client):
    assert client.post("/api/schedules", json={**VALID, "time": "9am"}).status_code == 422


def test_empty_days_422(client):
    assert client.post("/api/schedules", json={**VALID, "days": []}).status_code == 422


def test_minutes_over_cap_422(client):
    assert client.post("/api/schedules", json={**VALID, "minutes": 241}).status_code == 422


def test_minutes_at_cap_ok(client):
    assert client.post("/api/schedules", json={**VALID, "minutes": 240}).status_code == 200


def test_bad_zone_422(client):
    assert client.post("/api/schedules", json={**VALID, "zone": 3}).status_code == 422


# --- health -------------------------------------------------------------------

def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "scheduler" in body
