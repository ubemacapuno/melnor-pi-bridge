"""
Control Melnor timer's valves from the command line.

Run this on the remote device while it's within Bluetooth range of the timer
!IMPORTANT: the Melnor phone app must be CLOSED. Only one thing can hold the Bluetooth connection at a time.

Usage (run from the backend/ folder):

    uv run python scripts/control.py state            # show battery + valve status
    uv run python scripts/control.py schedule         # show any watering schedule set per zone
    uv run python scripts/control.py on 1 5           # turn zone 1 ON for 5 minutes
    uv run python scripts/control.py on 2 10          # turn zone 2 ON for 10 minutes
    uv run python scripts/control.py off 1            # turn zone 1 OFF
    uv run python scripts/control.py off 2            # turn zone 2 OFF
    uv run python scripts/control.py stop 1           # off + DISABLE the schedule
    uv run python scripts/control.py set-schedule 1 thu 19:00 240   # weekly: Thu 7PM, 240 min

Zones are 1 or 2 on the 2-valve timer.
"""

import asyncio
import sys
from datetime import datetime, timedelta

from melnor_bluetooth.device import Device
from melnor_bluetooth.utils import date as melnor_date

from melnor_scan import scan_for_melnor

# Map weekday names to weekday numbers starting from 0
WEEKDAYS = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


def next_occurrence(weekday, hour, minute):
    """
    Return the next datetime that falls on `weekday` (0=Mon..6=Sun) at
    hour:minute. If that moment already passed today, jump to next week.
    """
    now = datetime.now()
    days_ahead = (weekday - now.weekday()) % 7
    target = (now + timedelta(days=days_ahead)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if target <= now:
        target += timedelta(days=7)
    return target


async def find_device():
    """Scan and return the first Melnor BLE device found (or None)."""
    print("Scanning for the timer...")
    found = await scan_for_melnor(timeout_seconds=15)
    if not found:
        return None
    return next(iter(found.values()))


def get_zone(device, zone_number):
    """Return the Valve object for zone 1 or 2 (device.zone1 / device.zone2)."""
    return getattr(device, f"zone{zone_number}")


def watering_status(zone):
    """Return (is_watering, detail) for a zone, covering BOTH manual and
    scheduled watering.

    zone.is_watering only tracks MANUAL watering (the `on` command). A zone
    watering because of its schedule shows up in frequency.is_watering instead,
    so we check both. `detail` is a string like
    'scheduled, ~120.0 min left (ends 23:00:00)', or None when not watering.
    """
    if zone.is_watering and zone.watering_end_time:
        end_ts = zone.watering_end_time
        source = "manual"
    elif zone.schedule_enabled and zone.frequency.is_watering:
        # schedule_end is a datetime for when the scheduled cycle stops.
        end_ts = zone.frequency.schedule_end.timestamp()
        source = "scheduled"
    else:
        return False, None

    remaining = max(int(end_ts - datetime.now().timestamp()), 0)
    ends = datetime.fromtimestamp(end_ts).strftime("%H:%M:%S")
    return True, f"{source}, ~{round(remaining / 60, 1)} min left (ends {ends})"


async def run(command, zone_number=None, minutes=None, schedule=None):
    ble_device = await find_device()
    if ble_device is None:
        print("Could not find the timer. Is it awake? Is the phone app closed?")
        return

    print(f"Connecting to {ble_device.address} ...")
    device = Device(ble_device)
    await device.connect(retry_attempts=4)

    if not device.is_connected:
        print("Failed to connect. Close the Melnor phone app and try again.")
        return

    # Always pull the current state first so we print/act on fresh data.
    await device.fetch_state()

    if command == "state":
        print("\nCurrent state:")
        print(f"  Name:    {device.name}")
        print(f"  Battery: {device.battery_level}%")
        for zone_number in (1, 2):
            zone = get_zone(device, zone_number)
            watering, detail = watering_status(zone)
            line = f"  Zone {zone_number} watering now? {watering}"
            if detail:
                line += f"  ({detail})"
            print(line)

        print("\nSchedules:")
        for zone_number in (1, 2):
            zone = get_zone(device, zone_number)
            print(f"\n  Zone {zone_number}:")
            if not zone.schedule_enabled:
                print("    No schedule enabled.")
                continue
            freq = zone.frequency
            # Note: the library warns the DATE on next_cycle is unreliable;
            # only the hour/minute (the time of day) is trustworthy.
            print(f"    Schedule enabled: yes")
            print(f"    Start time:  {freq.start_time}")
            print(f"    Every:       {freq.interval_hours} hour(s)")
            print(f"    Duration:    {freq.duration_minutes} minute(s)")
            next_cycle = zone.next_cycle
            if next_cycle is not None:
                # Show the full weekday + time so we can sanity-check against
                # the phone app. (The library warns the calendar date can be
                # off; weekday + time are what we care about here.)
                print(f"    Next run: {next_cycle.strftime('%A %H:%M')}")

    elif command == "schedule":
        print("\nSchedules:")
        for zone_number in (1, 2):
            zone = get_zone(device, zone_number)
            print(f"\n  Zone {zone_number}:")
            if not zone.schedule_enabled:
                print("    No schedule enabled.")
                continue
            freq = zone.frequency
            # Note: the library warns the DATE on next_cycle is unreliable;
            # only the hour/minute (the time of day) is trustworthy.
            print(f"    Schedule enabled: yes")
            print(f"    Start time:  {freq.start_time}")
            print(f"    Every:       {freq.interval_hours} hour(s)")
            print(f"    Duration:    {freq.duration_minutes} minute(s)")
            next_cycle = zone.next_cycle
            if next_cycle is not None:
                # Show the full weekday + time so we can sanity-check against
                # the phone app. (The library warns the calendar date can be
                # off; weekday + time are what we care about here.)
                print(f"    Next run: {next_cycle.strftime('%A %H:%M')}")

    elif command == "on":
        zone = get_zone(device, zone_number)
        zone.is_watering = True
        zone.manual_watering_minutes = minutes
        await device.push_state()   # writes the change to the timer
        print(f"Zone {zone_number} turned ON for {minutes} minute(s).")

    elif command == "off":
        zone = get_zone(device, zone_number)
        zone.is_watering = False
        await device.push_state()
        print(f"Zone {zone_number} turned OFF.")

    elif command == "stop":
        # Fully stop a zone: turn off manual watering AND disable the
        # frequency schedule. `off` alone leaves the schedule enabled, so a
        # scheduled cycle keeps running (and gets re-enabled by push_state).
        zone = get_zone(device, zone_number)
        zone.is_watering = False
        # set_frequency_enabled(False) disables the schedule and writes the
        # whole state to the device in one shot (including is_watering above).
        await zone.set_frequency_enabled(False)
        print(f"Zone {zone_number} STOPPED (watering off + schedule disabled).")

    elif command == "set-schedule":
        # Set a WEEKLY schedule: water every `weekday` at `hour:minute`
        # for `minutes`. The device has no "weekday" field, so we encode it
        # as a start timestamp on that weekday, repeating every 168 hours.
        zone = get_zone(device, zone_number)
        freq = zone.frequency

        target = next_occurrence(schedule["weekday"], schedule["hour"], schedule["minute"])

        # Write the start timestamp directly (the public setter only lets you
        # change the time-of-day, not the weekday, so we set the raw value).
        freq._attr_raw_start_time = melnor_date.from_start_time(target)
        # These setters cap at the device's limits (360 min / 168 hours) and
        # recompute the next run time for us.
        freq.duration_minutes = schedule["minutes"]
        freq.interval_hours = 168   # 168 hours = once per week

        zone.is_watering = False    # make sure manual watering isn't left on
        # Enabling the schedule writes the whole frequency block to the device.
        await zone.set_frequency_enabled(True)

        print(
            f"Zone {zone_number} schedule set: "
            f"{target.strftime('%A %H:%M')}, {schedule['minutes']} min, weekly."
        )
        print("Now re-read it below to confirm the device accepted it:")
        print(f"    Schedule enabled: {zone.schedule_enabled}")
        if zone.next_cycle is not None:
            print(f"    Next run: {zone.next_cycle.strftime('%A %H:%M')}")

    await device.disconnect()
    print("Disconnected. Done.")


def parse_args_and_run():
    """Read the command-line arguments and call run() with them."""
    args = sys.argv[1:]  # everything after the script name

    if not args:
        print(__doc__)
        return

    command = args[0]

    if command == "state":
        asyncio.run(run("state"))

    elif command == "schedule":
        asyncio.run(run("schedule"))

    elif command == "on":
        # Expect: on <zone> <minutes>
        if len(args) != 3:
            print("Usage: control.py on <zone 1-2> <minutes>")
            return
        zone_number = int(args[1])
        minutes = int(args[2])
        asyncio.run(run("on", zone_number, minutes))

    elif command == "off":
        # Expect: off <zone>
        if len(args) != 2:
            print("Usage: control.py off <zone 1-2>")
            return
        zone_number = int(args[1])
        asyncio.run(run("off", zone_number))

    elif command == "stop":
        # Expect: stop <zone>, fully stop (watering off + schedule disabled)
        if len(args) != 2:
            print("Usage: control.py stop <zone 1-2>")
            return
        zone_number = int(args[1])
        asyncio.run(run("stop", zone_number))

    elif command == "set-schedule":
        # Expect: set-schedule <zone> <weekday> <HH:MM> <minutes>
        # e.g.    set-schedule 1 thu 19:00 240
        if len(args) != 5:
            print("Usage: control.py set-schedule <zone 1-2> <mon-sun> <HH:MM> <minutes>")
            print("Example: control.py set-schedule 1 thu 19:00 240")
            return
        zone_number = int(args[1])

        weekday_name = args[2].lower()[:3]
        if weekday_name not in WEEKDAYS:
            print(f"Unknown weekday '{args[2]}'. Use mon, tue, wed, thu, fri, sat, or sun.")
            return

        # Parse the HH:MM time (24-hour, e.g. 19:00 for 7 PM).
        try:
            hour_str, minute_str = args[3].split(":")
            hour, minute = int(hour_str), int(minute_str)
        except ValueError:
            print("Time must be HH:MM in 24-hour format, e.g. 19:00 for 7 PM.")
            return

        schedule = {
            "weekday": WEEKDAYS[weekday_name],
            "hour": hour,
            "minute": minute,
            "minutes": int(args[4]),
        }
        asyncio.run(run("set-schedule", zone_number, schedule=schedule))

    else:
        print(f"Unknown command: {command}")
        print(__doc__)


if __name__ == "__main__":
    parse_args_and_run()
