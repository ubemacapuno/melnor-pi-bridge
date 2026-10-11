"""
Tests for the Bluetooth plumbing that can run without a timer: the scanner is
always stopped, and the connect phase retries transient errors (but not bugs).
"""

import asyncio

import pytest
from bleak.exc import BleakError

from api import melnor, scan


class FakeScanner:
    """Stands in for BleakScanner and records start/stop calls."""

    instances = []

    def __init__(self, detection_callback):
        self.callback = detection_callback
        self.started = self.stopped = 0
        FakeScanner.instances.append(self)

    async def start(self):
        self.started += 1

    async def stop(self):
        self.stopped += 1


@pytest.fixture
def fake_scanner(monkeypatch):
    FakeScanner.instances = []
    monkeypatch.setattr(scan, "BleakScanner", FakeScanner)
    return FakeScanner


# --- scanner is always stopped ---------------------------------------------

def test_scanner_stopped_after_timeout(fake_scanner):
    assert asyncio.run(scan.scan_for_melnor(timeout_seconds=0.01)) == {}
    s = fake_scanner.instances[0]
    assert (s.started, s.stopped) == (1, 1)


def test_scanner_stopped_when_cancelled(fake_scanner):
    async def run_and_cancel():
        task = asyncio.create_task(scan.scan_for_melnor(timeout_seconds=30))
        await asyncio.sleep(0.01)  # let it start scanning
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run_and_cancel())
    s = fake_scanner.instances[0]
    assert (s.started, s.stopped) == (1, 1)


# --- connect retries --------------------------------------------------------

def _flaky_connect_once(monkeypatch, errors):
    """_connect_once raises each error in turn, then returns 'device'."""
    calls = {"n": 0}

    async def fake():
        calls["n"] += 1
        if errors:
            raise errors.pop(0)
        return "device"

    monkeypatch.setattr(melnor, "_connect_once", fake)
    return calls


@pytest.mark.parametrize(
    "error",
    [
        melnor.TimerNotFound("asleep"),
        BleakError("gatt"),
        asyncio.TimeoutError(),
        EOFError(),
        OSError("link dropped"),
    ],
    ids=lambda e: type(e).__name__,
)
def test_transient_errors_are_retried(monkeypatch, error):
    calls = _flaky_connect_once(monkeypatch, [error])
    assert asyncio.run(melnor._connect()) == "device"
    assert calls["n"] == 2


def test_gives_up_with_timer_not_found(monkeypatch):
    errors = [asyncio.TimeoutError() for _ in range(melnor._CONNECT_ATTEMPTS)]
    calls = _flaky_connect_once(monkeypatch, errors)
    with pytest.raises(melnor.TimerNotFound):
        asyncio.run(melnor._connect())
    assert calls["n"] == melnor._CONNECT_ATTEMPTS


def test_programming_errors_are_not_retried(monkeypatch):
    calls = _flaky_connect_once(monkeypatch, [AttributeError("bug")])
    with pytest.raises(AttributeError):
        asyncio.run(melnor._connect())
    assert calls["n"] == 1
