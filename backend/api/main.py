"""
FastAPI app that exposes the timer over HTTP.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path as FilePath

from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Relative imports: bring in our logic layer (melnor.py), the schedule store
# (store.py), and the Pi-side scheduler (scheduler.py).
from . import melnor, store, scheduler, state_cache

# Make OUR logs visible in the console. Everything in this app logs under the
# "melnor" name (e.g. "melnor.scheduler"). uvicorn only sets up its own
# loggers, so without this our messages, including "Schedule firing..." --
# would be silently swallowed. We attach one handler to the parent "melnor"
# logger; the child loggers send their messages up to it automatically.
_app_log = logging.getLogger("melnor")
if not _app_log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    _app_log.addHandler(_handler)
    _app_log.setLevel(logging.INFO)


# A "lifespan" runs setup code before the server takes any requests, and
# teardown code as it stops. Everything before `yield` is startup; everything
# after is shutdown. We use it to start the scheduler (which arms all saved
# schedules) on boot and stop it cleanly on exit.
@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()      # build the alarms from schedules.json
    yield                  # <-- the server runs here for its whole life
    scheduler.shutdown()   # stop the alarms cleanly on exit


# This one object IS the web application. FastAPI collects every route we
# attach to it below. uvicorn looks for this variable (api.main:app).
app = FastAPI(title="Melnor Timer API", lifespan=lifespan)

# The single Bluetooth gatekeeper now lives in melnor.py as `melnor.ble_lock`
# (see the comment there). Both the web endpoints below AND the scheduler take
# that same lock, so a scheduled watering can't collide with a live request.


# @app.get("/api/state") is a DECORATOR. It tells FastAPI: "when someone makes
# an HTTP GET request to /api/state, run the function right below me." The
# function's return value (a dict) is automatically turned into JSON.
@app.get("/api/state")
async def read_state():
    async with melnor.ble_lock:  # wait for our turn on the Bluetooth connection
        try:
            return await melnor.get_state()
        except melnor.TimerNotFound as error:
            # Turn our custom error into a clean HTTP 503 (Service Unavailable)
            # with a readable message, instead of a 500 "Internal Server Error".
            raise HTTPException(status_code=503, detail=str(error))


@app.get("/api/state/cached")
async def read_cached_state():
    """The last state we saw, WITHOUT touching Bluetooth (instant).

    Served from data/last_state.json, which melnor.py rewrites after every
    successful read or valve command (web or scheduler). Any client can load
    it on page open and count down from each zone's `ends_at`. Returns
    {"read_at": null, "state": null} until the timer has been read once.
    """
    cached = await asyncio.to_thread(state_cache.load)
    return cached or {"read_at": None, "state": None}


@app.get("/api/schedule")
async def read_schedule():
    async with melnor.ble_lock:
        try:
            return await melnor.get_schedule()
        except melnor.TimerNotFound as error:
            raise HTTPException(status_code=503, detail=str(error))


@app.get("/api/health")
async def health():
    """Liveness check: is the API process up and the scheduler running?

    Deliberately does NOT touch Bluetooth, it stays instant and won't report
    "unhealthy" just because the timer is asleep. (Use /api/state to check the
    timer itself.) `scheduler.jobs` is how many alarms are armed; compare it to
    the number of enabled schedules from /api/schedules to confirm they armed.
    """
    return {"status": "ok", "scheduler": scheduler.status()}


# --- Write endpoints (valve control) ------------------------------------
#
# These OPEN THE VALVE and run water. Path(...) restricts {zone} to 1 or 2
# and Query(...) restricts minutes to the device's 1-360 range; FastAPI turns
# out-of-range values into a clean 422 before we ever touch Bluetooth.
# The device tops out at 360 manual minutes.


@app.post("/api/zones/{zone}/on")
async def turn_zone_on(
    zone: int = Path(ge=1, le=2),
    minutes: int = Query(default=5, ge=1, le=360),
):
    """Turn a zone ON for `minutes` of manual watering."""
    async with melnor.ble_lock:
        try:
            return await melnor.water_zone(zone, minutes)
        except melnor.TimerNotFound as error:
            raise HTTPException(status_code=503, detail=str(error))


@app.post("/api/zones/{zone}/off")
async def turn_zone_off(zone: int = Path(ge=1, le=2)):
    """Turn a zone OFF (stops manual watering; leaves the schedule enabled)."""
    async with melnor.ble_lock:
        try:
            return await melnor.turn_off_zone(zone)
        except melnor.TimerNotFound as error:
            raise HTTPException(status_code=503, detail=str(error))


@app.post("/api/zones/{zone}/stop")
async def stop_zone(zone: int = Path(ge=1, le=2)):
    """Stop a zone: watering off AND schedule disabled."""
    async with melnor.ble_lock:
        try:
            return await melnor.stop_zone(zone)
        except melnor.TimerNotFound as error:
            raise HTTPException(status_code=503, detail=str(error))


@app.post("/api/zones/{zone}/schedule")
async def set_zone_schedule(
    zone: int = Path(ge=1, le=2),
    weekday: str = Query(description="Day of week: mon, tue, wed, thu, fri, sat, sun"),
    time: str = Query(description="24-hour start time, e.g. 21:00"),
    minutes: int = Query(ge=1, le=360),
):
    """Set a WEEKLY schedule: water `zone` every `weekday` at `time` for `minutes`."""
    # Validate HERE so bad input is a clean 422 before we ever open the (slow)
    # Bluetooth connection. Same validators as the Pi-side schedules below.
    day = _validate_weekday(weekday)
    hour, minute = _validate_time(time)

    async with melnor.ble_lock:
        try:
            return await melnor.set_zone_schedule(
                zone, melnor.WEEKDAYS[day], hour, minute, minutes
            )
        except melnor.TimerNotFound as error:
            raise HTTPException(status_code=503, detail=str(error))


# --- Pi-side schedule management -----------------------------------------
#
# These endpoints manage the schedules.json store and re-arm the in-process
# scheduler. They do NOT touch Bluetooth, they only edit the file and rebuild
# the alarms, so they don't take the BLE lock. They're `async def` so they run
# directly on the event loop, which is the safe way to poke the scheduler.


# Pi-side schedules cap watering at 360 minutes (6 h). That's also the device's
# own limit for one manual run, which is what a schedule sends when it fires
# (melnor.water_zone), so it can't go higher.
# If changing this, also update MAX_MINUTES in AddScheduleForm.tsx
_MAX_SCHEDULE_MINUTES = 360


class ScheduleCreate(BaseModel):
    """Shape of the JSON body for creating a schedule. FastAPI validates
    incoming JSON against this automatically and returns 422 if it's wrong."""

    zone: int = Field(ge=1, le=2)
    days: list[str]
    time: str = Field(description="24-hour HH:MM, e.g. 21:00")
    minutes: int = Field(ge=1, le=_MAX_SCHEDULE_MINUTES)
    is_enabled: bool = True


# Full names map to the 3-letter keys; anything else (e.g. "monkey", which
# used to slip through as "mon" via a [:3] slice) is rejected.
_FULL_DAY_NAMES = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu",
    "friday": "fri", "saturday": "sat", "sunday": "sun",
}


def _validate_weekday(value):
    """Normalize one weekday ("mon" or "monday", any case) to its 3-letter key,
    or raise HTTP 422."""
    day = value.strip().lower()
    day = _FULL_DAY_NAMES.get(day, day)
    if day not in melnor.WEEKDAYS:
        raise HTTPException(
            status_code=422,
            detail=f"'{value}' is not a weekday (use mon..sun).",
        )
    return day


def _validate_days(days):
    """Normalize + check a list of weekday names; raise HTTP 422 if any is bad.
    Returns the cleaned list (lowercased, 3-letter, e.g. ["mon", "wed"])."""
    if not days:
        raise HTTPException(status_code=422, detail="days must list at least one weekday.")
    return [_validate_weekday(d) for d in days]


def _validate_time(value):
    """Check a 24-hour HH:MM string; raise HTTP 422 if it's not valid.
    Returns (hour, minute)."""
    try:
        hour, minute = (int(p) for p in value.split(":"))
    except ValueError:
        raise HTTPException(
            status_code=422, detail="time must be HH:MM 24-hour, e.g. 21:00."
        )
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise HTTPException(
            status_code=422, detail="time must be a valid 24-hour HH:MM, e.g. 21:00."
        )
    return hour, minute


@app.get("/api/schedules")
async def list_schedules():
    """Return every saved schedule. No Bluetooth, just reads the file."""
    return store.load_schedules()


@app.post("/api/schedules")
async def create_schedule(body: ScheduleCreate):
    """Add a schedule, then re-arm the alarms so it takes effect immediately."""
    days = _validate_days(body.days)
    _validate_time(body.time)

    # Writing the file calls os.fsync (a disk flush that can briefly BLOCK).
    # asyncio.to_thread runs it on a background thread so it can't freeze the
    # event loop, and the scheduler, while it waits on the (SD-card) disk.
    # store.add_schedule rejects overlaps by raising ScheduleConflict -> 409.
    try:
        created = await asyncio.to_thread(
            store.add_schedule, body.zone, days, body.time, body.minutes, body.is_enabled
        )
    except store.ScheduleConflict as error:
        raise HTTPException(status_code=409, detail=str(error))
    scheduler.reload_jobs()  # rebuild alarms from the updated file
    return created


@app.delete("/api/schedules/{schedule_id}")
async def remove_schedule(schedule_id: str):
    """Delete a schedule by id, then re-arm the remaining alarms."""
    # Same reason as create_schedule: offload the blocking file write so the
    # disk flush can't stall the event loop.
    if not await asyncio.to_thread(store.delete_schedule, schedule_id):
        raise HTTPException(
            status_code=404, detail=f"No schedule with id '{schedule_id}'."
        )
    scheduler.reload_jobs()
    return {"deleted": schedule_id}


# --- Serve the built React frontend -------------------------------------
#
# The frontend is built (on the Pi) with `npm run build`, which writes static
# files to frontend/dist at the repo root. We mount that folder at "/" so the
# whole app is served by THIS same FastAPI server, one process, one URL, and
# the frontend's relative "/api/..." calls hit these routes automatically.
#
# This mount MUST come AFTER every /api route above: FastAPI matches the
# explicit routes first, then falls back to this catch-all for everything else
# (the HTML, JS, CSS). html=True makes it serve index.html at "/".
#
# We only mount if the build exists, so the API still starts (and the tests
# still run) before you've ever built the frontend.
_FRONTEND_DIST = FilePath(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
else:
    logging.getLogger("melnor").info(
        "Frontend build not found at %s, serving API only. "
        "Run `npm run build` in frontend/ to enable the web UI.",
        _FRONTEND_DIST,
    )
