"""
Step 2: Connect to the Melnor timer and read its state.

Run this with:   uv run python main.py

First run scan.py to find the device, then (optionally) paste its
address into DEVICE_ADDRESS below. If you leave it as None, this
script will scan and use the first Melnor device it finds.
"""

import asyncio

from melnor_bluetooth.device import Device

from melnor_scan import scan_for_melnor

# Paste the address you got from scan.py here, e.g. "A1B2C3D4-...".
# Leave as None to auto-pick the first device found.
DEVICE_ADDRESS = None


async def find_device():
    """Scan and return one BLE device (matching DEVICE_ADDRESS if set)."""
    print("Scanning for the timer...")
    found = await scan_for_melnor(timeout_seconds=15)

    if not found:
        return None

    if DEVICE_ADDRESS is not None:
        return found.get(DEVICE_ADDRESS)

    # No specific address requested: just take the first one.
    return next(iter(found.values()))


async def main():
    ble_device = await find_device()
    if ble_device is None:
        print("Could not find the timer. Run scan.py first and check it's awake.")
        return

    print(f"Connecting to {ble_device.address} ...")
    device = Device(ble_device)
    await device.connect(retry_attempts=4)

    if not device.is_connected:
        print("Failed to connect. Make sure the Melnor phone app is closed and retry.")
        return

    # Pull the latest state (battery, valve status, etc.) from the timer.
    await device.fetch_state()

    print("\nConnected! Current state:")
    print(f"  Name:        {device.name}")
    print(f"  Model:       {device.model}")
    print(f"  Battery:     {device.battery_level}%")
    print(f"  Valve count: {device.valve_count}")
    print(f"  Zone 1 watering now? {device.zone1.is_watering}")

    # Turn zone 1 on for 5 minutes:
    #
    # device.zone1.is_watering = True
    # device.zone1.manual_watering_minutes = 5
    # await device.push_state()
    # print("Turned zone 1 ON for 5 minutes.")
    #
    # To turn it off:
    # device.zone1.is_watering = False
    # await device.push_state()

    await device.disconnect()
    print("\nDisconnected. Done.")


if __name__ == "__main__":
    asyncio.run(main())
