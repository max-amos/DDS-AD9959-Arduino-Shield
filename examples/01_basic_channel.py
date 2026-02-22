#!/usr/bin/env python3
"""
Basic Channel Configuration
============================

Set frequency, amplitude, and phase on individual channels.

Usage:
    python 01_basic_channel.py /dev/ttyUSB0
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ad9959 import AD9959

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"

with AD9959(PORT) as dds:
    # Query device info
    print(f"Model:    {dds.get_model()}")
    print(f"Firmware: {dds.get_version()}")
    print()

    # Set Channel 0: 10 MHz, -10 dBm
    dds.set_channel(0, freq_hz=10_000_000, dbm=-10)
    print("Ch0: 10 MHz @ -10 dBm")

    # Set Channel 1: 1 MHz, -20 dBm, 90 degrees
    dds.set_channel(1, freq_hz=1_000_000, dbm=-20, degrees=90)
    print("Ch1: 1 MHz @ -20 dBm, 90 deg")

    # Change just the frequency on Channel 0
    dds.set_frequency(0, 15_000_000)
    print("Ch0: -> 15 MHz")

    # Change just the amplitude on Channel 1
    dds.set_amplitude(1, -15)
    print("Ch1: -> -15 dBm")

    # Disable and re-enable
    dds.disable()
    print("Outputs disabled")

    import time
    time.sleep(1)

    dds.enable()
    print("Outputs enabled")
