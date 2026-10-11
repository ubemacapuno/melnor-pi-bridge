"""
Scheduler logic: fires each watering schedule at the right time.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from . import melnor
from . import store

log = logging.getLogger("melnor.scheduler")

_scheduler = None


async def _fire(schedule_id, zone, minutes):
    """Run ONE watering job, this is what an alarm calls when it goes off.

    It's `async` because Bluetooth is async, and because it must take the SAME
    BLE lock the web endpoints use: only one thing may hold the Bluetooth
    connection at a time. Everything is wrapped in try/except so a failed
    watering (timer asleep, out of range) LOGS an error instead of crashing the
    scheduler and silently killing every future job. We log the schedule_id so
    that when several schedules share a zone you can tell which one fired.
    """
    log.info("Schedule %s firing: zone %s for %s min", schedule_id, zone, minutes)
    try:
        async with melnor.ble_lock:  # wait our turn on the Bluetooth connection
            await melnor.water_zone(zone, minutes)
        log.info("Schedule %s: zone %s watering started OK", schedule_id, zone)
    except Exception:
        # .exception() records the full traceback but lets the scheduler keep
        # running, so tonight's failure doesn't cancel tomorrow's watering.
        log.exception("Schedule %s (zone %s) FAILED", schedule_id, zone)


def reload_jobs():
    """Wipe all alarms and rebuild them from schedules.json.

    Called on startup and after every add/delete, so the live alarms always
    match the file. Rebuilding from scratch is simpler (and plenty fast at this
    scale) than diffing old vs new.
    """
    # remove_all_jobs() already clears the store, so every id below is fresh --
    # no need for replace_existing on add_job.
    _scheduler.remove_all_jobs()

    for sched in store.load_schedules():
        # Arm each record inside its own try/except so ONE bad entry (e.g. a
        # hand-edited "time": "9am", or a missing field) is skipped and logged,
        # instead of aborting the loop and leaving every LATER schedule unarmed.
        try:
            if not sched.get("is_enabled", True):
                continue  # keep it in the file, but don't arm it

            hour, minute = sched["time"].split(":")
            trigger = CronTrigger(
                day_of_week=",".join(sched["days"]),  # e.g. "mon,wed,sat"
                hour=int(hour),
                minute=int(minute),
            )
            _scheduler.add_job(
                _fire,
                trigger,
                # These three are passed into _fire(schedule_id, zone, minutes).
                args=[sched["id"], sched["zone"], sched["minutes"]],
                id=sched["id"],           # reuse the schedule id as the job id
                misfire_grace_time=300,   # if we're up to 5 min late, still fire
                coalesce=True,            # if several were missed, run once not N times
            )
            log.info(
                "Armed %s: zone %s %s @ %s for %s min",
                sched["id"], sched["zone"], sched["days"], sched["time"], sched["minutes"],
            )
        except Exception:
            log.exception("Skipping unusable schedule record: %r", sched)


def start():
    """Create and start the scheduler, then arm all saved schedules.

    Called once when FastAPI boots (see main.py's lifespan handler).
    """
    global _scheduler
    # No timezone argument = APScheduler uses the machine's LOCAL time. On the
    # Pi you MUST set the system timezone (timedatectl) so 21:00 means 21:00
    # where you live. We log the resolved zone below so it's easy to verify.
    _scheduler = AsyncIOScheduler()
    _scheduler.start()
    log.info("Scheduler started (timezone: %s)", _scheduler.timezone)
    reload_jobs()


def shutdown():
    """Stop the scheduler cleanly when FastAPI shuts down."""
    if _scheduler is not None:
        _scheduler.shutdown()


def status():
    """A snapshot for health checks.

    `running` is whether the scheduler is alive; `jobs` is how many alarms are
    ARMED right now (enabled + valid schedules only), compare it against the
    count from GET /api/schedules to confirm everything armed after a reboot.
    Both come from in-memory state, so this is instant and never touches BLE.
    """
    if _scheduler is None:
        return {"is_running": False, "jobs": 0}
    return {"is_running": _scheduler.running, "jobs": len(_scheduler.get_jobs())}
