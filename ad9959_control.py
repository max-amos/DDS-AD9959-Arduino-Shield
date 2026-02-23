#!/usr/bin/env python3
"""
AD9959 DDS Arduino Shield - Serial Control Library & CLI

Controls the GRA & AFCH AD9959 4-channel DDS signal generator (HW v1.x/v2.x)
over serial port. Firmware >= v1.21 required.

Library usage:
    from ad9959_control import AD9959Controller
    ctrl = AD9959Controller('/dev/ttyUSB0')
    ctrl.connect()
    ctrl.set_frequency(0, 10_000_000)
    ctrl.set_amplitude(0, -10)
    ctrl.close()

CLI usage:
    python ad9959_control.py --port /dev/ttyUSB0 --channel 0 --freq 10000000
    python ad9959_control.py --port /dev/ttyUSB0 --channel 0 --freq 10000000 --amp -10 --phase 90
    python ad9959_control.py --port /dev/ttyUSB0 --enable
    python ad9959_control.py --port /dev/ttyUSB0 --info
    python ad9959_control.py --port /dev/ttyUSB0 --channel 0 --sweep-start 1000000 --sweep-stop 50000000 --sweep-step 100000 --sweep-dwell 10
    python ad9959_control.py --test  # mock serial, no hardware needed

Requires: pyserial (pip install pyserial)
"""

import argparse
import io
import re
import sys
import time


# ── Number parsing (scientific notation) ───────────────────────────


def parse_number(s):
    """
    Parse a numeric string, supporting scientific notation (e.g. 10e6, 1.5e7).

    Returns an integer. Accepts:
        - Plain integers: '10000000'
        - Scientific notation: '10e6', '1.5e7', '1e+6', '2.25e8'
        - Negative values: '-10', '-1.5e1'

    Raises:
        argparse.ArgumentTypeError: If the string cannot be parsed.
    """
    s = s.strip()
    try:
        value = float(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid number: '{s}'")
    result = int(value)
    if abs(value - result) > 0.5:
        raise argparse.ArgumentTypeError(
            f"'{s}' = {value}, which does not round to a clean integer"
        )
    return result


# ── Mock serial for hardware-free testing ──────────────────────────


class MockSerial:
    """
    Emulates the AD9959 firmware serial responses.

    Faithfully reproduces every response string from ReadSerialCommands.ino
    so round-trip communication logic can be validated without hardware.
    """

    FREQ_MIN = 100_000
    FREQ_MAX = 225_000_000  # ui32HIGH_FREQ_LIMIT = DDS_Core_Clock * 0.45

    def __init__(self, **kwargs):
        self._is_open = True
        self._read_buf = io.BytesIO()
        self._channel = -1
        self._channels = {
            ch: {'freq_hz': 100_000_000, 'dbm': -3, 'degrees': 0}
            for ch in range(4)
        }
        self._outputs_enabled = True

    # -- pyserial interface stubs --

    @property
    def is_open(self):
        return self._is_open

    @property
    def in_waiting(self):
        pos = self._read_buf.tell()
        self._read_buf.seek(0, 2)
        end = self._read_buf.tell()
        self._read_buf.seek(pos)
        return end - pos

    @property
    def dtr(self):
        return False

    @dtr.setter
    def dtr(self, value):
        pass

    def reset_input_buffer(self):
        self._read_buf = io.BytesIO()
        # Simulate boot banner arriving after port open (firmware prints on reset)
        self._queue_response(
            "DDS AD9959 by GRA & AFCH\r\n"
            "HW v2.x\r\n"
            "SW v2.04\r\n"
            "CoreClock\r\n"
        )

    def write(self, data):
        text = data.decode('ascii').strip()
        self._process_message(text)

    def flush(self):
        pass

    def readline(self):
        line = self._read_buf.readline()
        return line if line else b''

    def close(self):
        self._is_open = False

    # -- firmware emulation --

    def _queue_response(self, text):
        old_pos = self._read_buf.tell()
        self._read_buf.seek(0, 2)
        # Firmware sends raw bytes over serial; em-dashes in PROGMEM
        # arrive as multi-byte sequences. For mock purposes, replace
        # unicode em-dashes with plain ASCII dashes.
        safe = text.replace('\u2014', '-')
        self._read_buf.write(safe.encode('ascii'))
        self._read_buf.seek(old_pos)

    def _process_message(self, text):
        """Parse semicolon-separated commands exactly like GParser + sscanf in firmware."""
        parts = text.split(';')
        for part in parts:
            part = part.strip()
            if not part:
                continue
            cmd = part[0]
            val_str = part[1:]
            try:
                value = int(val_str) if val_str else 0
            except ValueError:
                value = 0
            self._dispatch(cmd, value)

    def _dispatch(self, cmd, value):
        if cmd == 'C':
            if 0 <= value <= 3:
                self._channel = value
                self._queue_response(
                    f"The Channel number is set to: {value}\r\n"
                )
            else:
                self._queue_response(
                    "The Channel number is OUT OF RANGE (0 \u2014 3)\r\n"
                )

        elif cmd == 'F':
            if self._channel == -1:
                self._queue_response(
                    'The output Channel is not selected! '
                    'Use "C" command to select the Channel.\r\n'
                )
                return
            if self.FREQ_MIN <= value <= self.FREQ_MAX:
                self._channels[self._channel]['freq_hz'] = value
                self._queue_response(
                    f"The Frequency of Channel {self._channel} is set to: {value}\r\n"
                )
            else:
                self._queue_response(
                    f"Frequency is OUT OF RANGE ({self.FREQ_MIN} - {self.FREQ_MAX})\r\n"
                )

        elif cmd == 'A':
            if self._channel == -1:
                self._queue_response(
                    'The output Channel is not selected! '
                    'Use "C" command to select the Channel.\r\n'
                )
                return
            if -60 <= value <= -7:
                self._channels[self._channel]['dbm'] = value
                self._queue_response(
                    f"The Power (Amplitude) of Channel {self._channel} is set to: {value}\r\n"
                )
            else:
                self._queue_response(
                    "Power is OUT OF RANGE (-60 \u2014 -7)\r\n"
                )

        elif cmd == 'P':
            if self._channel == -1:
                self._queue_response(
                    'The output Channel is not selected! '
                    'Use "C" command to select the Channel.\r\n'
                )
                return
            if 0 <= value <= 360:
                self._channels[self._channel]['degrees'] = value
                self._queue_response(
                    f"The Phase of Channel {self._channel} is set to: {value}\r\n"
                )
            else:
                self._queue_response(
                    "Phase is OUT OF RANGE (0 \u2014 360)\r\n"
                )

        elif cmd == 'E':
            self._outputs_enabled = True
            self._queue_response("Outputs Enabled\r\n")

        elif cmd == 'D':
            self._outputs_enabled = False
            self._queue_response("Outputs Disabled\r\n")

        elif cmd == 'V':
            self._queue_response("2.04\r\n")

        elif cmd == 'M':
            self._queue_response("DDS9959 v1.1\r\n")

        elif cmd == 'h':
            self._queue_response(
                "C \u2014 Set the current output Channel: (0 \u2014 3)\n"
                "F \u2014 Sets Frequency in Hz (100000 \u2014 225000000)\n"
                "A \u2014 Sets the power (Amplitude) level of the selected channel in dBm (-60 \u2014 -7)\n"
                "P \u2014 Sets the Phase of the selected channel in dBm (0 \u2014 360)\n"
                "M \u2014 Gets Model\n"
                "E - Enable Outputs (ALL)\n"
                "D - Disable Outputs (ALL)\n"
                "V \u2014 Gets Firmware Version\n"
                "h \u2014 This Help\n"
                "; \u2014 Commands Separator\n"
                "Example:\n"
                "C0;F100000;A-10\n"
                "Sets the Frequency to 100 kHz, and Output Power (Amplitude) to -10 dBm on Channel 0 (RF OUT0).\n"
                "Any number of commands in any order is allowed, but the very first command must be \"C\".\n"
                "Note: by default, the maximum length of one message is 64 bytes\r\n"
            )
        else:
            self._queue_response(f"Unknown command:{cmd}\r\n")


# ── Controller ─────────────────────────────────────────────────────


class AD9959Error(Exception):
    """Base exception for AD9959 errors."""


class AD9959Controller:
    """
    Controller for the GRA & AFCH AD9959 DDS Arduino Shield.

    Protocol (from ReadSerialCommands.ino analysis):
      - 115200 baud, 8N1, DTR OFF, 10ms firmware timeout
      - Commands: single ASCII letter + integer value
      - Semicolon-separated, newline-terminated
      - Max 64 bytes per message (Arduino serial buffer)
      - Channel (C) must be selected before F/A/P
      - All changes applied atomically after full message parsed
    """

    FREQ_MIN = 100_000
    FREQ_MAX = 225_000_000
    AMP_MIN = -60
    AMP_MAX = -7
    PHASE_MIN = 0
    PHASE_MAX = 360
    CHANNELS = (0, 1, 2, 3)
    MAX_MSG = 64

    def __init__(self, port=None, baudrate=115200, timeout=1.0, test_mode=False):
        """
        Create controller. Call connect() to open the serial link.

        Args:
            port: Serial port path (e.g. '/dev/ttyUSB0', 'COM3').
                  Ignored when test_mode=True.
            baudrate: Baud rate (default 115200, must match firmware).
            timeout: Serial read timeout in seconds.
            test_mode: If True, use MockSerial instead of real hardware.
        """
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._test_mode = test_mode
        self._ser = None
        self._connected = False
        # Shadow state: track what we've sent to the device
        self._state = {
            ch: {'freq_hz': None, 'dbm': None, 'degrees': None}
            for ch in range(4)
        }
        self._outputs_enabled = None
        self._model = None
        self._version = None

    # ── Connection ─────────────────────────────────────────

    def connect(self):
        """
        Open the serial connection and drain the boot banner.

        Returns:
            List of boot banner lines from the device.

        Raises:
            AD9959Error: If port is not set (and not in test mode).
        """
        if self._connected:
            return []

        if self._test_mode:
            self._ser = MockSerial()
        else:
            if not self._port:
                raise AD9959Error("No port specified. Pass port= or use --port on CLI.")
            import serial
            # CRITICAL: Set DTR=False BEFORE opening the port.
            # Opening with port= in constructor pulses DTR HIGH,
            # which resets the Arduino MEGA via the auto-reset circuit.
            self._ser = serial.Serial()
            self._ser.port = self._port
            self._ser.baudrate = self._baudrate
            self._ser.bytesize = serial.EIGHTBITS
            self._ser.parity = serial.PARITY_NONE
            self._ser.stopbits = serial.STOPBITS_ONE
            self._ser.timeout = self._timeout
            self._ser.dsrdtr = False
            self._ser.rtscts = False
            self._ser.dtr = False
            self._ser.open()
            time.sleep(0.1)

        self._ser.reset_input_buffer()
        self._connected = True

        # Wait for boot banner. If DTR pulsed (some USB-serial chips do this
        # regardless of settings), the Arduino resets and takes ~3.5s to boot.
        # We detect this by waiting and checking for the banner.
        time.sleep(0.5)
        banner = self._read_response()
        if not banner:
            # No banner yet — likely mid-boot. Wait for the full 3s delay.
            print("[waiting for board boot...]", flush=True)
            time.sleep(3.5)
            banner = self._read_response()
        return banner

    def close(self):
        """Close the serial connection without resetting the Arduino."""
        if self._ser and self._ser.is_open:
            # Hold DTR low before closing to prevent reset pulse
            self._ser.dtr = False
            self._ser.close()
        self._connected = False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    @property
    def connected(self):
        return self._connected

    # ── Low-level I/O ──────────────────────────────────────

    def _send(self, cmd_str):
        """
        Send a command string, return response lines.

        Appends newline. Raises if message exceeds 64-byte limit.
        """
        if not self._connected:
            raise AD9959Error("Not connected. Call connect() first.")

        msg = cmd_str.strip() + '\n'
        if len(msg) > self.MAX_MSG:
            raise AD9959Error(
                f"Message too long ({len(msg)} bytes, max {self.MAX_MSG}). "
                "Split into multiple sends."
            )
        self._ser.write(msg.encode('ascii'))
        self._ser.flush()
        # Firmware needs time to process command, update DDS via SPI,
        # and refresh the OLED display (~16ms I2C write + SPI writes).
        time.sleep(0.08)
        return self._read_response()

    def _read_response(self):
        """Read all available lines from the device."""
        lines = []
        while self._ser.in_waiting:
            raw = self._ser.readline()
            if raw:
                line = raw.decode('ascii', errors='replace').strip()
                if line:
                    lines.append(line)
        return lines

    def _check_errors(self, lines):
        """Raise AD9959Error if any response line indicates a firmware error."""
        for line in lines:
            if 'OUT OF RANGE' in line:
                raise AD9959Error(line)
            if 'not selected' in line:
                raise AD9959Error(line)
            if 'Unknown command' in line:
                raise AD9959Error(line)

    # ── Core commands ──────────────────────────────────────

    def set_frequency(self, channel, freq_hz):
        """
        Set output frequency on a channel.

        Args:
            channel: 0-3
            freq_hz: Frequency in Hz (100000 - 225000000)

        Returns:
            Response lines from the device.
        """
        self._validate_channel(channel)
        freq_hz = int(freq_hz)
        self._validate_range(freq_hz, self.FREQ_MIN, self.FREQ_MAX, 'Frequency', 'Hz')

        lines = self._send(f"C{channel};F{freq_hz}")
        self._check_errors(lines)
        self._state[channel]['freq_hz'] = freq_hz
        return lines

    def set_amplitude(self, channel, dbm):
        """
        Set output amplitude on a channel.

        Args:
            channel: 0-3
            dbm: Power in dBm (-60 to -7)

        Returns:
            Response lines from the device.
        """
        self._validate_channel(channel)
        dbm = int(dbm)
        self._validate_range(dbm, self.AMP_MIN, self.AMP_MAX, 'Amplitude', 'dBm')

        lines = self._send(f"C{channel};A{dbm}")
        self._check_errors(lines)
        self._state[channel]['dbm'] = dbm
        return lines

    def set_phase(self, channel, degrees):
        """
        Set output phase on a channel.

        Args:
            channel: 0-3
            degrees: Phase in integer degrees (0 - 360).
                     Note: serial protocol only supports integer degrees;
                     the fractional part (available via encoder) is not settable.

        Returns:
            Response lines from the device.
        """
        self._validate_channel(channel)
        degrees = int(degrees)
        self._validate_range(degrees, self.PHASE_MIN, self.PHASE_MAX, 'Phase', 'deg')

        lines = self._send(f"C{channel};P{degrees}")
        self._check_errors(lines)
        self._state[channel]['degrees'] = degrees
        return lines

    def configure_channel(self, channel, freq_hz=None, dbm=None, degrees=None):
        """
        Set frequency, amplitude, and/or phase on a channel in one atomic command.

        All parameters are applied simultaneously by the firmware after the
        full message is parsed, then ApplyChangesToDDS() reprograms the chip.

        Args:
            channel: 0-3
            freq_hz: Frequency in Hz (optional)
            dbm: Power in dBm (optional)
            degrees: Phase in degrees (optional)

        Returns:
            Response lines from the device.
        """
        self._validate_channel(channel)
        parts = [f"C{channel}"]

        if freq_hz is not None:
            freq_hz = int(freq_hz)
            self._validate_range(freq_hz, self.FREQ_MIN, self.FREQ_MAX, 'Frequency', 'Hz')
            parts.append(f"F{freq_hz}")

        if dbm is not None:
            dbm = int(dbm)
            self._validate_range(dbm, self.AMP_MIN, self.AMP_MAX, 'Amplitude', 'dBm')
            parts.append(f"A{dbm}")

        if degrees is not None:
            degrees = int(degrees)
            self._validate_range(degrees, self.PHASE_MIN, self.PHASE_MAX, 'Phase', 'deg')
            parts.append(f"P{degrees}")

        lines = self._send(';'.join(parts))
        self._check_errors(lines)

        if freq_hz is not None:
            self._state[channel]['freq_hz'] = freq_hz
        if dbm is not None:
            self._state[channel]['dbm'] = dbm
        if degrees is not None:
            self._state[channel]['degrees'] = degrees

        return lines

    def enable(self):
        """Enable all RF outputs."""
        lines = self._send('E')
        self._outputs_enabled = True
        return lines

    def disable(self):
        """Disable (power down) all RF outputs."""
        lines = self._send('D')
        self._outputs_enabled = False
        return lines

    def get_version(self):
        """Query firmware version. Returns version string."""
        lines = self._send('V')
        self._version = lines[0] if lines else None
        return self._version

    def get_model(self):
        """Query device model. Returns model string."""
        lines = self._send('M')
        self._model = lines[0] if lines else None
        return self._model

    def get_help(self):
        """Retrieve the help text from the device."""
        return '\n'.join(self._send('h'))

    def get_status(self):
        """
        Return a status dict with everything we know about the device state.

        Queries model/version from the device on first call, then uses cached
        values. Channel state reflects what this controller has sent (shadow state).
        """
        if self._model is None:
            self.get_model()
        if self._version is None:
            self.get_version()

        return {
            'model': self._model,
            'version': self._version,
            'outputs_enabled': self._outputs_enabled,
            'channels': {
                ch: dict(self._state[ch]) for ch in range(4)
            },
        }

    # ── Sweep ──────────────────────────────────────────────

    def sweep_frequency(self, channel, start_hz, stop_hz, step_hz, dwell_ms):
        """
        Software-driven frequency sweep.

        Sends rapid serial commands - not a hardware sweep. Actual step rate
        is limited by serial latency (~50ms per step minimum).

        Args:
            channel: 0-3
            start_hz: Start frequency in Hz
            stop_hz: Stop frequency in Hz
            step_hz: Step size in Hz (always positive; direction auto-detected)
            dwell_ms: Dwell time per step in milliseconds

        Yields:
            (freq_hz, response_lines) at each step.
        """
        self._validate_channel(channel)
        step = abs(int(step_hz))
        if step == 0:
            raise AD9959Error("Step size must be > 0")

        start = int(start_hz)
        stop = int(stop_hz)
        dwell_s = dwell_ms / 1000.0

        if start <= stop:
            freq = start
            while freq <= stop:
                lines = self.set_frequency(channel, freq)
                yield freq, lines
                if dwell_s > 0:
                    time.sleep(dwell_s)
                freq += step
        else:
            freq = start
            while freq >= stop:
                lines = self.set_frequency(channel, freq)
                yield freq, lines
                if dwell_s > 0:
                    time.sleep(dwell_s)
                freq -= step

    # ── Validation helpers ─────────────────────────────────

    def _validate_channel(self, channel):
        if channel not in self.CHANNELS:
            raise AD9959Error(f"Channel must be 0-3, got {channel}")

    @staticmethod
    def _validate_range(value, lo, hi, name, unit):
        if not (lo <= value <= hi):
            raise AD9959Error(f"{name} {value} {unit} out of range ({lo} - {hi})")


# ── CLI ────────────────────────────────────────────────────────────


def build_parser():
    p = argparse.ArgumentParser(
        prog='ad9959_control',
        description='AD9959 DDS Arduino Shield - serial control',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'examples:\n'
            '  %(prog)s --port /dev/ttyUSB0 --channel 0 --freq 10000000\n'
            '  %(prog)s --port /dev/ttyUSB0 --channel 0 --freq 10000000 --amp -10 --phase 90\n'
            '  %(prog)s --port /dev/ttyUSB0 --enable\n'
            '  %(prog)s --port /dev/ttyUSB0 --info\n'
            '  %(prog)s --port /dev/ttyUSB0 --channel 0 --sweep-start 1000000 --sweep-stop 50000000 --sweep-step 100000 --sweep-dwell 10\n'
            '  %(prog)s --test\n'
        ),
    )

    p.add_argument('--port', '-p', help='Serial port (e.g. /dev/ttyUSB0, COM3)')
    p.add_argument('--test', action='store_true',
                   help='Use mock serial (no hardware needed)')

    chan = p.add_argument_group('channel configuration')
    chan.add_argument('--channel', '-c', type=int, choices=[0, 1, 2, 3],
                      help='Target channel (0-3)')
    chan.add_argument('--freq', '-f', type=parse_number, metavar='HZ',
                      help='Frequency in Hz (100000 - 225000000). Supports scientific notation (e.g. 10e6)')
    chan.add_argument('--amp', '-a', type=parse_number, metavar='DBM',
                      help='Amplitude in dBm (-60 to -7)')
    chan.add_argument('--phase', type=parse_number, metavar='DEG',
                      help='Phase in degrees (0 - 360)')

    out = p.add_argument_group('output control')
    out.add_argument('--enable', action='store_true', help='Enable all outputs')
    out.add_argument('--disable', action='store_true', help='Disable all outputs')

    info = p.add_argument_group('info')
    info.add_argument('--info', action='store_true',
                      help='Query and print model, version, status')
    info.add_argument('--device-help', action='store_true',
                      help='Print the device help text')

    sw = p.add_argument_group('frequency sweep')
    sw.add_argument('--sweep-start', type=parse_number, metavar='HZ',
                    help='Sweep start frequency. Supports scientific notation (e.g. 1e6)')
    sw.add_argument('--sweep-stop', type=parse_number, metavar='HZ',
                    help='Sweep stop frequency. Supports scientific notation (e.g. 50e6)')
    sw.add_argument('--sweep-step', type=parse_number, metavar='HZ', default=100_000,
                    help='Sweep step size (default: 100000). Supports scientific notation (e.g. 100e3)')
    sw.add_argument('--sweep-dwell', type=parse_number, metavar='MS', default=10,
                    help='Dwell time per step in ms (default: 10)')

    return p


def run_cli(args=None):
    parser = build_parser()
    opts = parser.parse_args(args)

    # Validate: need either --port or --test
    if not opts.port and not opts.test:
        parser.error('--port is required (or use --test for mock mode)')

    # Validate: channel required for freq/amp/phase/sweep
    needs_channel = any([
        opts.freq is not None,
        opts.amp is not None,
        opts.phase is not None,
        opts.sweep_start is not None,
    ])
    if needs_channel and opts.channel is None:
        parser.error('--channel is required when setting freq/amp/phase or sweeping')

    # Validate: sweep needs start and stop
    sweep_opts = [opts.sweep_start, opts.sweep_stop]
    if any(v is not None for v in sweep_opts) and not all(v is not None for v in sweep_opts):
        parser.error('--sweep-start and --sweep-stop must both be specified')

    ctrl = AD9959Controller(
        port=opts.port,
        test_mode=opts.test,
    )

    try:
        banner = ctrl.connect()
        if opts.test and banner:
            print('[mock] Boot banner:')
            for line in banner:
                print(f'  {line}')
            print()

        # Info / help
        if opts.info:
            status = ctrl.get_status()
            print(f"Model:    {status['model']}")
            print(f"Firmware: {status['version']}")
            print(f"Outputs:  {'enabled' if status['outputs_enabled'] else 'disabled' if status['outputs_enabled'] is not None else 'unknown'}")
            for ch in range(4):
                s = status['channels'][ch]
                freq = f"{s['freq_hz']} Hz" if s['freq_hz'] else '?'
                amp = f"{s['dbm']} dBm" if s['dbm'] else '?'
                phase = f"{s['degrees']} deg" if s['degrees'] is not None else '?'
                print(f"  Ch{ch}: {freq}, {amp}, {phase}")
            return

        if opts.device_help:
            print(ctrl.get_help())
            return

        # Enable/disable
        if opts.enable:
            for line in ctrl.enable():
                print(line)

        if opts.disable:
            for line in ctrl.disable():
                print(line)

        # Channel configuration
        if opts.freq is not None or opts.amp is not None or opts.phase is not None:
            lines = ctrl.configure_channel(
                opts.channel,
                freq_hz=opts.freq,
                dbm=opts.amp,
                degrees=opts.phase,
            )
            for line in lines:
                print(line)

        # Sweep
        if opts.sweep_start is not None:
            count = 0
            t0 = time.time()
            for freq, lines in ctrl.sweep_frequency(
                opts.channel,
                opts.sweep_start,
                opts.sweep_stop,
                opts.sweep_step,
                opts.sweep_dwell,
            ):
                count += 1
                print(f"  {freq:>12,} Hz", end='\r', flush=True)
            elapsed = time.time() - t0
            print(f"\n{count} steps in {elapsed:.1f}s", end='')
            if elapsed > 0:
                print(f" ({count / elapsed:.0f} steps/sec)", end='')
            print()

    except AD9959Error as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        ctrl.close()


# ── Self-test ──────────────────────────────────────────────────────


def run_tests():
    """
    Validate round-trip communication using MockSerial.

    Tests every command path, error handling, and edge cases.
    Returns True if all tests pass.
    """
    passed = 0
    failed = 0
    errors = []

    def check(name, condition, detail=''):
        nonlocal passed, failed
        if condition:
            passed += 1
        else:
            failed += 1
            errors.append(f"  FAIL: {name}" + (f" - {detail}" if detail else ''))

    print("AD9959Controller self-test (mock serial)")
    print("=" * 50)

    # -- connect --
    ctrl = AD9959Controller(test_mode=True)
    banner = ctrl.connect()
    check("connect returns banner", len(banner) > 0, f"got {len(banner)} lines")
    check("connected flag", ctrl.connected)

    # -- model / version --
    model = ctrl.get_model()
    check("get_model", model == "DDS9959 v1.1", f"got '{model}'")

    version = ctrl.get_version()
    check("get_version", version == "2.04", f"got '{version}'")

    # -- set_frequency --
    lines = ctrl.set_frequency(0, 10_000_000)
    check("set_frequency response",
          any("Frequency" in l and "10000000" in l for l in lines),
          str(lines))

    # -- set_amplitude --
    lines = ctrl.set_amplitude(0, -10)
    check("set_amplitude response",
          any("Amplitude" in l and "-10" in l for l in lines),
          str(lines))

    # -- set_phase --
    lines = ctrl.set_phase(0, 90)
    check("set_phase response",
          any("Phase" in l and "90" in l for l in lines),
          str(lines))

    # -- configure_channel (multi-param) --
    lines = ctrl.configure_channel(1, freq_hz=5_000_000, dbm=-20, degrees=180)
    check("configure_channel has channel set",
          any("Channel number" in l for l in lines), str(lines))
    check("configure_channel has freq",
          any("Frequency" in l and "5000000" in l for l in lines), str(lines))
    check("configure_channel has amp",
          any("Amplitude" in l and "-20" in l for l in lines), str(lines))
    check("configure_channel has phase",
          any("Phase" in l and "180" in l for l in lines), str(lines))

    # -- enable / disable --
    lines = ctrl.enable()
    check("enable", any("Enabled" in l for l in lines), str(lines))

    lines = ctrl.disable()
    check("disable", any("Disabled" in l for l in lines), str(lines))

    # -- get_status --
    status = ctrl.get_status()
    check("status has model", status['model'] == "DDS9959 v1.1")
    check("status has version", status['version'] == "2.04")
    check("status ch0 freq",
          status['channels'][0]['freq_hz'] == 10_000_000,
          f"got {status['channels'][0]['freq_hz']}")
    check("status ch0 amp",
          status['channels'][0]['dbm'] == -10,
          f"got {status['channels'][0]['dbm']}")
    check("status ch0 phase",
          status['channels'][0]['degrees'] == 90,
          f"got {status['channels'][0]['degrees']}")
    check("status ch1 freq",
          status['channels'][1]['freq_hz'] == 5_000_000)
    check("status outputs disabled", status['outputs_enabled'] is False)

    # -- get_help --
    help_text = ctrl.get_help()
    check("get_help non-empty", len(help_text) > 100, f"len={len(help_text)}")
    check("get_help has commands", "Commands Separator" in help_text)

    # -- edge: frequency boundaries --
    lines = ctrl.set_frequency(2, 100_000)
    check("freq at min boundary (100kHz)",
          any("100000" in l for l in lines), str(lines))

    lines = ctrl.set_frequency(2, 225_000_000)
    check("freq at max boundary (225MHz)",
          any("225000000" in l for l in lines), str(lines))

    # -- error: freq out of range --
    try:
        ctrl.set_frequency(0, 50_000)  # below 100kHz
        check("freq below min raises", False, "no exception raised")
    except AD9959Error as e:
        check("freq below min raises", "out of range" in str(e).lower(), str(e))

    try:
        ctrl.set_frequency(0, 300_000_000)  # above 225MHz
        check("freq above max raises", False, "no exception raised")
    except AD9959Error as e:
        check("freq above max raises", "out of range" in str(e).lower(), str(e))

    # -- error: amp out of range --
    try:
        ctrl.set_amplitude(0, -3)
        check("amp above -7 raises", False)
    except AD9959Error as e:
        check("amp above -7 raises", True)

    try:
        ctrl.set_amplitude(0, -65)
        check("amp below -60 raises", False)
    except AD9959Error as e:
        check("amp below -60 raises", True)

    # -- error: bad channel --
    try:
        ctrl.set_frequency(5, 1_000_000)
        check("bad channel raises", False)
    except AD9959Error as e:
        check("bad channel raises", "0-3" in str(e))

    # -- error: phase out of range --
    try:
        ctrl.set_phase(0, 400)
        check("phase above 360 raises", False)
    except AD9959Error as e:
        check("phase above 360 raises", True)

    # -- sweep (short) --
    sweep_freqs = []
    for freq, lines in ctrl.sweep_frequency(0, 1_000_000, 3_000_000, 1_000_000, 0):
        sweep_freqs.append(freq)
    check("sweep steps",
          sweep_freqs == [1_000_000, 2_000_000, 3_000_000],
          str(sweep_freqs))

    # -- sweep reverse --
    sweep_freqs = []
    for freq, lines in ctrl.sweep_frequency(0, 3_000_000, 1_000_000, 1_000_000, 0):
        sweep_freqs.append(freq)
    check("sweep reverse",
          sweep_freqs == [3_000_000, 2_000_000, 1_000_000],
          str(sweep_freqs))

    # -- message length limit --
    try:
        ctrl._send("C0;F" + "9" * 100)
        check("msg length limit raises", False)
    except AD9959Error as e:
        check("msg length limit raises", "too long" in str(e).lower())

    # -- close --
    ctrl.close()
    check("close", not ctrl.connected)

    # -- context manager --
    with AD9959Controller(test_mode=True) as ctx:
        ctx.set_frequency(0, 1_000_000)
        check("context manager works", ctx.connected)
    check("context manager closes", not ctx.connected)

    # -- parse_number: scientific notation --
    check("parse 10e6", parse_number('10e6') == 10_000_000,
          f"got {parse_number('10e6')}")
    check("parse 1.5e7", parse_number('1.5e7') == 15_000_000,
          f"got {parse_number('1.5e7')}")
    check("parse 225e6", parse_number('225e6') == 225_000_000,
          f"got {parse_number('225e6')}")
    check("parse 100e3", parse_number('100e3') == 100_000,
          f"got {parse_number('100e3')}")
    check("parse 1e+6", parse_number('1e+6') == 1_000_000,
          f"got {parse_number('1e+6')}")
    check("parse plain int", parse_number('10000000') == 10_000_000,
          f"got {parse_number('10000000')}")
    check("parse negative", parse_number('-10') == -10,
          f"got {parse_number('-10')}")
    check("parse -1.5e1", parse_number('-1.5e1') == -15,
          f"got {parse_number('-1.5e1')}")
    check("parse 2.25e8", parse_number('2.25e8') == 225_000_000,
          f"got {parse_number('2.25e8')}")

    try:
        parse_number('abc')
        check("parse garbage raises", False, "no exception raised")
    except argparse.ArgumentTypeError:
        check("parse garbage raises", True)

    # -- CLI with scientific notation (end-to-end via mock) --
    ctrl2 = AD9959Controller(test_mode=True)
    ctrl2.connect()
    lines = ctrl2.set_frequency(0, parse_number('10e6'))
    check("set_frequency via parse_number('10e6')",
          any("10000000" in l for l in lines), str(lines))
    lines = ctrl2.set_frequency(0, parse_number('225e6'))
    check("set_frequency via parse_number('225e6')",
          any("225000000" in l for l in lines), str(lines))
    ctrl2.close()

    # -- report --
    print()
    total = passed + failed
    if errors:
        for e in errors:
            print(e)
        print()
    print(f"{passed}/{total} tests passed", end='')
    if failed:
        print(f", {failed} FAILED")
    else:
        print(" - ALL OK")

    return failed == 0


# ── Entry point ────────────────────────────────────────────────────


if __name__ == '__main__':
    # If --test is the only arg (or combined with no port), run self-test
    if '--test' in sys.argv and '--freq' not in sys.argv and '--sweep-start' not in sys.argv \
            and '--enable' not in sys.argv and '--disable' not in sys.argv \
            and '--info' not in sys.argv and '--device-help' not in sys.argv \
            and '--channel' not in sys.argv:
        ok = run_tests()
        sys.exit(0 if ok else 1)
    else:
        run_cli()
