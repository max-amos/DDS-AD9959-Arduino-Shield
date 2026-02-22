#!/usr/bin/env python3
"""
Amplitude Modulation Patterns
===============================

Software-driven amplitude sweeps and modulation patterns.
The AD9959 amplitude range via serial is -60 to -7 dBm (integer steps).
This gives ~53 dB of dynamic range with 1 dB resolution.

Usage:
    python 04_amplitude_modulation.py /dev/ttyUSB0
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import time
import math
from ad9959 import AD9959

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"

with AD9959(PORT) as dds:
    CARRIER_FREQ = 10_000_000  # 10 MHz carrier

    # ── Amplitude ramp up/down ─────────────────────────────
    print("=== Amplitude Ramp: -60 dBm -> -7 dBm -> -60 dBm ===")
    dds.set_frequency(0, CARRIER_FREQ)

    # Ramp up
    for dbm, _ in dds.sweep_amplitude(0, -60, -7, 1, 0.05):
        print(f"  {dbm} dBm", end='\r')
    # Ramp down
    for dbm, _ in dds.sweep_amplitude(0, -7, -60, 1, 0.05):
        print(f"  {dbm} dBm", end='\r')
    print("\nRamp complete.")

    print()

    # ── On/Off keying (OOK) ────────────────────────────────
    # Toggle between full power and minimum power
    print("=== OOK Pattern: 10 MHz carrier ===")
    pattern = [1, 0, 1, 1, 0, 1, 0, 0]  # arbitrary bit pattern
    for bit in pattern:
        if bit:
            dds.set_amplitude(0, -10)
        else:
            dds.set_amplitude(0, -60)
        print(f"  bit={bit}", end='\r')
        time.sleep(0.2)
    print(f"\nOOK pattern: {pattern}")

    print()

    # ── Sinusoidal AM envelope (quantized) ─────────────────
    # Map sin(t) to the -60..-7 dBm range
    print("=== Sinusoidal AM Envelope: 2 cycles ===")
    dds.set_frequency(0, CARRIER_FREQ)
    steps = 100
    for cycle in range(2):
        for i in range(steps):
            t = i / steps * 2 * math.pi
            # sin(t) ranges -1..1, map to -60..-7
            level = -60 + (1 + math.sin(t)) / 2 * 53  # 53 dB range
            level = max(-60, min(-7, int(level)))
            dds.set_amplitude(0, level)
        print(f"  Cycle {cycle + 1} complete")
    print("Sinusoidal AM complete.")

    print()

    # ── Multi-channel amplitude balance ────────────────────
    print("=== Channel Balance: equal power on 4 channels ===")
    dds.configure({
        0: {'freq_hz': 10_000_000, 'dbm': -10, 'degrees': 0},
        1: {'freq_hz': 10_000_000, 'dbm': -10, 'degrees': 90},
        2: {'freq_hz': 10_000_000, 'dbm': -10, 'degrees': 180},
        3: {'freq_hz': 10_000_000, 'dbm': -10, 'degrees': 270},
    })
    print("All channels: 10 MHz, -10 dBm, 90 deg spacing")

    # Now attenuate channels one at a time for testing
    print("Attenuating channels individually...")
    for ch in range(4):
        dds.set_amplitude(ch, -30)
        print(f"  Ch{ch} -> -30 dBm (others at -10 dBm)")
        time.sleep(1)
        dds.set_amplitude(ch, -10)  # restore
    print("Balance test complete.")
