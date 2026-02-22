#!/usr/bin/env python3
"""
Frequency Sweep
================

Software-driven frequency sweep on one channel.
This uses rapid serial updates - not the AD9959 hardware sweep engine
(which isn't exposed through the GRA & AFCH firmware serial protocol).

Sweep rate is limited by serial latency (~50ms per step).
For faster sweeps, use coarser steps.

Usage:
    python 03_frequency_sweep.py /dev/ttyUSB0
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import time
from ad9959 import AD9959

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"

with AD9959(PORT) as dds:
    # Set initial amplitude
    dds.set_channel(0, freq_hz=1_000_000, dbm=-10)

    # ── Linear sweep: 1 MHz to 50 MHz in 100 kHz steps ────
    print("=== Linear Sweep: 1 MHz -> 50 MHz ===")
    t0 = time.time()
    count = 0
    for freq, _ in dds.sweep_frequency(
        channel=0,
        start_hz=1_000_000,
        stop_hz=50_000_000,
        step_hz=100_000,
        dwell_s=0,  # as fast as serial allows
    ):
        count += 1
        print(f"  {freq/1e6:.1f} MHz", end='\r')
    elapsed = time.time() - t0
    print(f"\n{count} steps in {elapsed:.1f}s ({count/elapsed:.0f} steps/sec)")

    print()

    # ── Bidirectional sweep (ping-pong) ────────────────────
    print("=== Ping-Pong Sweep: 5 MHz <-> 25 MHz ===")
    for cycle in range(3):
        # Sweep up
        for freq, _ in dds.sweep_frequency(0, 5_000_000, 25_000_000, 500_000, 0):
            print(f"  Cycle {cycle+1} UP: {freq/1e6:.1f} MHz", end='\r')
        # Sweep down
        for freq, _ in dds.sweep_frequency(0, 25_000_000, 5_000_000, 500_000, 0):
            print(f"  Cycle {cycle+1} DN: {freq/1e6:.1f} MHz", end='\r')
    print("\nPing-pong complete.")

    print()

    # ── Logarithmic-ish sweep (decade steps) ───────────────
    print("=== Decade Sweep: 100 kHz -> 100 MHz ===")
    freq = 100_000
    while freq <= 100_000_000:
        dds.set_frequency(0, freq)
        print(f"  {freq/1e6:.3f} MHz")
        time.sleep(0.5)
        freq *= 10
    print("Decade sweep complete.")
