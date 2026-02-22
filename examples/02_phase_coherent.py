#!/usr/bin/env python3
"""
Multi-Channel Phase-Coherent Output
=====================================

Set all 4 channels to the same frequency with controlled phase offsets.
The AD9959 applies changes atomically when commands arrive in a single
serial message, making phase relationships deterministic.

Use case: Quadrature I/Q generation, phased-array beamforming,
          multi-phase power conversion testing.

Usage:
    python 02_phase_coherent.py /dev/ttyUSB0
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ad9959 import AD9959

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"

with AD9959(PORT) as dds:
    # ── Quadrature (I/Q) on channels 0 and 1 ──────────────
    # Same frequency, 90-degree phase offset
    print("=== Quadrature I/Q: 10 MHz ===")
    dds.configure({
        0: {'freq_hz': 10_000_000, 'dbm': -10, 'degrees': 0},
        1: {'freq_hz': 10_000_000, 'dbm': -10, 'degrees': 90},
    })
    print("Ch0: 10 MHz, 0 deg (I)")
    print("Ch1: 10 MHz, 90 deg (Q)")
    input("Press Enter to continue...")

    # ── 4-phase system (0, 90, 180, 270) ──────────────────
    # Common in motor drive testing and 4-phase power systems
    print("\n=== 4-Phase System: 1 MHz ===")
    dds.configure({
        0: {'freq_hz': 1_000_000, 'dbm': -10, 'degrees': 0},
        1: {'freq_hz': 1_000_000, 'dbm': -10, 'degrees': 90},
        2: {'freq_hz': 1_000_000, 'dbm': -10, 'degrees': 180},
        3: {'freq_hz': 1_000_000, 'dbm': -10, 'degrees': 270},
    })
    print("Ch0:   0 deg")
    print("Ch1:  90 deg")
    print("Ch2: 180 deg")
    print("Ch3: 270 deg")
    input("Press Enter to continue...")

    # ── 3-phase power (0, 120, 240) on channels 0-2 ──────
    print("\n=== 3-Phase Power: 50 Hz equivalent @ 500 kHz ===")
    dds.configure({
        0: {'freq_hz': 500_000, 'dbm': -10, 'degrees': 0},
        1: {'freq_hz': 500_000, 'dbm': -10, 'degrees': 120},
        2: {'freq_hz': 500_000, 'dbm': -10, 'degrees': 240},
    })
    print("Ch0:   0 deg")
    print("Ch1: 120 deg")
    print("Ch2: 240 deg")

    # ── Sweep phase offset while keeping frequency locked ─
    print("\n=== Phase sweep: Ch1 relative to Ch0 ===")
    for phase in range(0, 361, 10):
        dds.set_phase(1, phase)
        print(f"  Ch1 phase: {phase} deg", end='\r')
    print("\nPhase sweep complete.")
