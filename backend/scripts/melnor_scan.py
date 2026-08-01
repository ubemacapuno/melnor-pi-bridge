"""
Bluetooth scanner to detect the Melnor device.
"""

import asyncio

from bleak import BleakScanner

# Melnor timers advertise using Bluetooth "manufacturer ID" 13.
# We use this to tell Melnor devices apart from every other BLE gadget
MELNOR_MANUFACTURER_ID = 13


async def scan_for_melnor(timeout_seconds=15, on_found=None, stop_on_first=True):
    """
    Listen for Melnor devices for up to `timeout_seconds`.

    Returns a dict of {address: BLEDevice} for everything found.
    If `on_found` is given, it's called with each new BLE device.

    By default (`stop_on_first=True`) the scan returns as soon as the first
    Melnor device is seen, instead of always waiting the full timeout. Set
    it to False to keep listening the whole window (e.g. to find several).
    """
    found = {}
    # An Event lets the callback signal "found it" so we can stop early
    # instead of always sleeping for the full timeout.
    first_found = asyncio.Event()

    def detection_callback(ble_device, advertisement_data):
        # Only keep devices that advertise as Melnor.
        if MELNOR_MANUFACTURER_ID not in advertisement_data.manufacturer_data:
            return
        if ble_device.address in found:
            return
        found[ble_device.address] = ble_device
        if on_found is not None:
            on_found(ble_device)
        if stop_on_first:
            first_found.set()

    scanner = BleakScanner(detection_callback=detection_callback)
    await scanner.start()
    try:
        # Wait until we find one, or give up after timeout_seconds.
        await asyncio.wait_for(first_found.wait(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        # Nothing showed up in time, found stays whatever we collected.
        pass
    await scanner.stop()

    return found
