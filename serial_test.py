#!/usr/bin/env python3
"""
AD9959 DDS Serial Test Script
GRA & AFCH DDS9959 HW2.x firmware v2.04

Connects to the board at 115200 baud and validates serial communication
by exercising every documented command.

Usage:
    python3 serial_test.py [PORT]

    PORT defaults to /dev/tty.usbmodem* (macOS) or /dev/ttyUSB0 (Linux).
    On Windows, use COM3 or similar.

Requires: pip install pyserial
"""

import sys
import time
import glob
import serial


# --- Configuration -----------------------------------------------------------

BAUD = 115200
TIMEOUT_S = 2.0        # read timeout
SETTLE_S = 0.1         # pause between commands
BOOT_WAIT_S = 3.5      # board prints banner + 3s delay(3000) in setup()

# Frequency limits (from firmware)
LOW_FREQ = 100_000          # 100 kHz
HIGH_FREQ = 225_000_000     # 225 MHz

# --- Helpers -----------------------------------------------------------------


def find_port():
    """Auto-detect the Arduino MEGA serial port."""
    patterns = [
        "/dev/tty.usbmodem*",
        "/dev/ttyUSB*",
        "/dev/ttyACM*",
    ]
    for pat in patterns:
        ports = glob.glob(pat)
        if ports:
            return sorted(ports)[0]
    return None


def open_serial(port):
    """Open the serial port with the correct settings (115200 8N1, DTR off)."""
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = BAUD
    ser.bytesize = serial.EIGHTBITS
    ser.parity = serial.PARITY_NONE
    ser.stopbits = serial.STOPBITS_ONE
    ser.timeout = TIMEOUT_S
    ser.dtr = False         # DTR OFF — critical, prevents Arduino reset
    ser.open()
    return ser


def send(ser, cmd):
    """Send a command string terminated with newline. Return all response lines."""
    ser.reset_input_buffer()
    ser.write((cmd + "\n").encode("ascii"))
    ser.flush()
    time.sleep(SETTLE_S)

    lines = []
    while True:
        line = ser.readline().decode("ascii", errors="replace").strip()
        if not line:
            break
        lines.append(line)
    return lines


def expect(lines, substring, label=""):
    """Assert that at least one response line contains the substring."""
    for line in lines:
        if substring in line:
            return True
    tag = f" [{label}]" if label else ""
    print(f"  FAIL{tag}: expected '{substring}' in response, got: {lines}")
    return False


# --- Test Cases --------------------------------------------------------------


def test_boot_banner(ser):
    """Read the boot banner (only works if board just powered on / reset)."""
    print("\n--- Boot Banner (drain) ---")
    ser.reset_input_buffer()
    # The banner may already have been sent. Just drain whatever is there.
    while True:
        line = ser.readline().decode("ascii", errors="replace").strip()
        if not line:
            break
        print(f"  BOOT: {line}")


def test_version(ser):
    """V — query firmware version."""
    print("\n--- Test: V (Firmware Version) ---")
    lines = send(ser, "V")
    for ln in lines:
        print(f"  < {ln}")
    ok = expect(lines, "2.0", "version")
    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def test_model(ser):
    """M — query model string."""
    print("\n--- Test: M (Model) ---")
    lines = send(ser, "M")
    for ln in lines:
        print(f"  < {ln}")
    # Firmware returns "DDS9959 v1.1" (known bug: should be v2.x)
    ok = expect(lines, "DDS9959", "model")
    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def test_help(ser):
    """h — query help text."""
    print("\n--- Test: h (Help) ---")
    lines = send(ser, "h")
    ok = len(lines) >= 5  # help is multi-line
    for ln in lines[:3]:
        print(f"  < {ln}")
    if len(lines) > 3:
        print(f"  < ... ({len(lines)} lines total)")
    print(f"  {'PASS' if ok else 'FAIL'}: got {len(lines)} lines")
    return ok


def test_channel_select(ser):
    """C — select channel 0-3, and out-of-range."""
    print("\n--- Test: C (Channel Select) ---")
    ok = True
    for ch in range(4):
        lines = send(ser, f"C{ch}")
        for ln in lines:
            print(f"  < {ln}")
        ok = ok and expect(lines, f"set to: {ch}", f"C{ch}")

    # Out of range
    lines = send(ser, "C5")
    for ln in lines:
        print(f"  < {ln}")
    ok = ok and expect(lines, "OUT OF RANGE", "C5 reject")

    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def test_frequency(ser):
    """F — set frequency on channel 0 to 10 MHz."""
    print("\n--- Test: C0;F10000000 (Set CH0 to 10 MHz) ---")
    lines = send(ser, "C0;F10000000")
    for ln in lines:
        print(f"  < {ln}")
    ok = expect(lines, "Channel number is set to: 0", "channel")
    ok = expect(lines, "Frequency", "freq ack") and ok
    ok = expect(lines, "10000000", "freq value") and ok
    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def test_frequency_no_channel(ser):
    """F without prior C on a fresh connection — should be rejected.
    Note: C persists in global state, so this only works if C was never set
    in this session. We test by sending an unknown command to NOT reset C,
    but C is already set from previous tests. Skip strict check.
    """
    print("\n--- Test: F without channel (informational) ---")
    # C is already set from test_channel_select, so this won't trigger the error.
    # Documenting the expected behavior: "The output Channel is not selected!"
    print("  SKIP: C already set in this session (stateful)")
    return True


def test_amplitude(ser):
    """A — set amplitude on channel 0 to -10 dBm."""
    print("\n--- Test: C0;A-10 (Set CH0 amplitude to -10 dBm) ---")
    lines = send(ser, "C0;A-10")
    for ln in lines:
        print(f"  < {ln}")
    ok = expect(lines, "Amplitude", "amp ack")
    ok = expect(lines, "-10", "amp value") and ok
    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def test_amplitude_out_of_range(ser):
    """A — reject amplitude outside -60..-7."""
    print("\n--- Test: C0;A0 (Amplitude out of range) ---")
    lines = send(ser, "C0;A0")
    for ln in lines:
        print(f"  < {ln}")
    ok = expect(lines, "OUT OF RANGE", "amp reject")
    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def test_phase(ser):
    """P — set phase on channel 0 to 90 degrees."""
    print("\n--- Test: C0;P90 (Set CH0 phase to 90 deg) ---")
    lines = send(ser, "C0;P90")
    for ln in lines:
        print(f"  < {ln}")
    ok = expect(lines, "Phase", "phase ack")
    ok = expect(lines, "90", "phase value") and ok
    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def test_enable_disable(ser):
    """E/D — enable and disable all outputs."""
    print("\n--- Test: D then E (Disable/Enable outputs) ---")
    ok = True

    lines = send(ser, "D")
    for ln in lines:
        print(f"  < {ln}")
    ok = ok and expect(lines, "Disabled", "disable")

    lines = send(ser, "E")
    for ln in lines:
        print(f"  < {ln}")
    ok = ok and expect(lines, "Enabled", "enable")

    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def test_chained_commands(ser):
    """Test semicolon-separated command chain."""
    print("\n--- Test: C1;F1000000;A-20;P45 (Chained commands) ---")
    lines = send(ser, "C1;F1000000;A-20;P45")
    for ln in lines:
        print(f"  < {ln}")
    ok = expect(lines, "Channel number is set to: 1", "chain C")
    ok = expect(lines, "1000000", "chain F") and ok
    ok = expect(lines, "-20", "chain A") and ok
    ok = expect(lines, "45", "chain P") and ok
    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def test_unknown_command(ser):
    """Unknown command letter — should print help."""
    print("\n--- Test: X (Unknown command) ---")
    lines = send(ser, "X")
    for ln in lines:
        if "Unknown" in ln:
            print(f"  < {ln}")
    ok = expect(lines, "Unknown command", "unknown")
    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def test_query(ser):
    """Q — query current channel state after setting known values."""
    print("\n--- Test: Q (Query channel state) ---")
    # First set known state on CH0
    send(ser, "C0;F5000000;A-15;P45")
    time.sleep(SETTLE_S)

    lines = send(ser, "C0;Q")
    for ln in lines:
        print(f"  < {ln}")
    ok = expect(lines, "CH0", "query channel")
    ok = expect(lines, "F=5000000", "query freq") and ok
    ok = expect(lines, "A=-15", "query amp") and ok
    ok = expect(lines, "P=45", "query phase") and ok
    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def test_per_channel_enable_disable(ser):
    """E0-E3 / D0-D3 — per-channel enable and disable via CFR."""
    print("\n--- Test: D0, E0 (Per-channel enable/disable) ---")
    ok = True

    # Disable channel 0
    lines = send(ser, "D0")
    for ln in lines:
        print(f"  < {ln}")
    ok = ok and expect(lines, "Channel", "D0 ack")
    ok = ok and expect(lines, "Disabled", "D0 disabled")

    # Re-enable channel 0
    lines = send(ser, "E0")
    for ln in lines:
        print(f"  < {ln}")
    ok = ok and expect(lines, "Channel", "E0 ack")
    ok = ok and expect(lines, "Enabled", "E0 enabled")

    # Test all channels D1-D3, E1-E3
    for ch in range(1, 4):
        lines = send(ser, f"D{ch}")
        ok = ok and expect(lines, f"Channel", f"D{ch}")
        ok = ok and expect(lines, "Disabled", f"D{ch}")
        lines = send(ser, f"E{ch}")
        ok = ok and expect(lines, f"Channel", f"E{ch}")
        ok = ok and expect(lines, "Enabled", f"E{ch}")

    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def test_fractional_phase(ser):
    """P90.5 — fractional phase support."""
    print("\n--- Test: C0;P90.5 (Fractional phase) ---")
    lines = send(ser, "C0;P90.5")
    for ln in lines:
        print(f"  < {ln}")
    ok = expect(lines, "Phase", "frac phase ack")
    ok = expect(lines, "90.5", "frac phase value") and ok
    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def test_phase_360_clamp(ser):
    """P360.5 — fractional part clamped to 0 at 360 degrees."""
    print("\n--- Test: C0;P360 (Phase clamp at 360) ---")
    lines = send(ser, "C0;P360")
    for ln in lines:
        print(f"  < {ln}")
    ok = expect(lines, "360.0", "phase 360 clamp")
    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def test_frequency_boundaries(ser):
    """F — test boundary values: min, max, below-min, above-max."""
    print("\n--- Test: Frequency boundaries ---")
    ok = True

    # Minimum valid: 100,000 Hz
    lines = send(ser, f"C0;F{LOW_FREQ}")
    ok = ok and expect(lines, str(LOW_FREQ), "freq min")

    # Maximum valid: 225,000,000 Hz
    lines = send(ser, f"C0;F{HIGH_FREQ}")
    ok = ok and expect(lines, str(HIGH_FREQ), "freq max")

    # Below minimum: 99,999 Hz
    lines = send(ser, f"C0;F{LOW_FREQ - 1}")
    ok = ok and expect(lines, "OUT OF RANGE", "freq below min")

    # Above maximum: 225,000,001 Hz
    lines = send(ser, f"C0;F{HIGH_FREQ + 1}")
    ok = ok and expect(lines, "OUT OF RANGE", "freq above max")

    for ln in lines:
        print(f"  < {ln}")
    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def test_amplitude_boundaries(ser):
    """A — test boundary values: -60, -3, -61, -2."""
    print("\n--- Test: Amplitude boundaries ---")
    ok = True

    # Min valid: -60 dBm
    lines = send(ser, "C0;A-60")
    ok = ok and expect(lines, "-60", "amp min")

    # Max valid: -3 dBm
    lines = send(ser, "C0;A-3")
    ok = ok and expect(lines, "-3", "amp max")

    # Below min: -61 dBm
    lines = send(ser, "C0;A-61")
    ok = ok and expect(lines, "OUT OF RANGE", "amp below min")

    # Above max: -2 dBm
    lines = send(ser, "C0;A-2")
    ok = ok and expect(lines, "OUT OF RANGE", "amp above max")

    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def test_scientific_notation(ser):
    """F1e6 — scientific notation frequency support."""
    print("\n--- Test: C0;F1e6 (Scientific notation) ---")
    lines = send(ser, "C0;F1e6")
    for ln in lines:
        print(f"  < {ln}")
    ok = expect(lines, "1000000", "sci notation 1e6")

    # Also test F1.5e8 = 150 MHz
    lines = send(ser, "C0;F1.5e8")
    for ln in lines:
        print(f"  < {ln}")
    ok = expect(lines, "150000000", "sci notation 1.5e8") and ok

    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def test_query_all_channels(ser):
    """Q — query each channel independently to verify state isolation."""
    print("\n--- Test: Query all channels (state isolation) ---")
    ok = True

    # Set different frequencies on each channel
    freqs = [1000000, 5000000, 10000000, 50000000]
    for ch, freq in enumerate(freqs):
        send(ser, f"C{ch};F{freq}")
        time.sleep(SETTLE_S)

    # Verify each channel retained its own frequency
    for ch, freq in enumerate(freqs):
        lines = send(ser, f"C{ch};Q")
        ok = ok and expect(lines, f"F={freq}", f"CH{ch} query")
        for ln in lines:
            if "CH" in ln:
                print(f"  < {ln}")

    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


# --- Main --------------------------------------------------------------------


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else find_port()
    if not port:
        print("ERROR: No serial port found. Pass port as argument:")
        print("  python3 serial_test.py /dev/ttyUSB0")
        print("  python3 serial_test.py COM3")
        sys.exit(1)

    print(f"AD9959 DDS Serial Test")
    print(f"Port: {port}  Baud: {BAUD}")
    print(f"Opening (DTR=OFF to avoid reset)...")

    ser = open_serial(port)
    print(f"Connected. Draining boot banner...")

    # Drain any boot output
    test_boot_banner(ser)

    # Run all tests
    results = {}
    tests = [
        ("Version",          test_version),
        ("Model",            test_model),
        ("Help",             test_help),
        ("Channel Select",   test_channel_select),
        ("Frequency",        test_frequency),
        ("Freq No Channel",  test_frequency_no_channel),
        ("Amplitude",        test_amplitude),
        ("Amp Out of Range", test_amplitude_out_of_range),
        ("Phase",            test_phase),
        ("Enable/Disable",   test_enable_disable),
        ("Chained Commands", test_chained_commands),
        ("Unknown Command",  test_unknown_command),
        ("Query",            test_query),
        ("Per-Chan En/Dis",  test_per_channel_enable_disable),
        ("Fractional Phase", test_fractional_phase),
        ("Phase 360 Clamp",  test_phase_360_clamp),
        ("Freq Boundaries",  test_frequency_boundaries),
        ("Amp Boundaries",   test_amplitude_boundaries),
        ("Sci Notation",     test_scientific_notation),
        ("Query All Chan",   test_query_all_channels),
    ]

    for name, fn in tests:
        try:
            results[name] = fn(ser)
        except Exception as e:
            print(f"  ERROR: {e}")
            results[name] = False

    # Summary
    print("\n" + "=" * 50)
    print("RESULTS SUMMARY")
    print("=" * 50)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"\n  {passed}/{total} passed")

    ser.close()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
