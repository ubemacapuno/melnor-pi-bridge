"""
Step 1: Find the Melnor timer over Bluetooth.

Run this with:   uv run python scan.py

It listens for ~15 seconds and prints any Melnor devices it hears,
along with the "address" you'll use to connect in main.py.
"""

import asyncio

from melnor_scan import scan_for_melnor


def on_device_found(ble_device):
    """Called every time the scanner hears a new Melnor device."""
    print(f"  Found: name={ble_device.name!r}  address={ble_device.address}")


async def main():
    print("Scanning for Melnor devices for 15 seconds...")
    print("(Make sure the timer is powered on and nearby.)\n")

    found = await scan_for_melnor(timeout_seconds=15, on_found=on_device_found)

    print()
    if not found:
        print("No Melnor devices found. Tips:")
        print("  - Make sure the timer has batteries and is awake.")
        print("  - Make sure the Melnor phone app is CLOSED (it holds the connection).")
        print("  - Check macOS Bluetooth permission for your terminal app.")
    else:
        print(f"Done. Found {len(found)} device(s).")
        print("Copy an address above and paste it into main.py.")


if __name__ == "__main__":
    asyncio.run(main())
