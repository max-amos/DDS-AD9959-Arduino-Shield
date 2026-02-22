"""
AD9959 DDS Arduino Shield - Serial Control Library

Controls the GRA & AFCH AD9959 4-channel DDS signal generator
over serial port. Compatible with HW v1.x and v2.x firmware >= 1.21.

Requires: pyserial (pip install pyserial)
"""

import time
import serial


class AD9959Error(Exception):
    """Base exception for AD9959 errors."""


class ChannelNotSelectedError(AD9959Error):
    """Raised when trying to set F/A/P without selecting a channel first."""


class OutOfRangeError(AD9959Error):
    """Raised when a parameter is out of the allowed range."""


class AD9959:
    """
    Controller for the AD9959 DDS Arduino Shield via serial port.

    Serial protocol: 115200 baud, 8N1, DTR OFF.
    Commands are single-letter + value, semicolon-separated, newline-terminated.
    Max message length: 64 bytes (Arduino serial buffer default).

    The firmware applies all changes atomically after processing the full message,
    so batching commands in one send() call ensures phase-coherent updates.
    """

    FREQ_MIN = 100_000          # 100 kHz
    FREQ_MAX = 225_000_000      # 225 MHz (hard limit)
    AMP_MIN = -60               # dBm
    AMP_MAX = -7                # dBm (HW1.x) or -3 (HW2.x via encoder)
    PHASE_MIN = 0               # degrees
    PHASE_MAX = 360             # degrees
    CHANNELS = (0, 1, 2, 3)
    MAX_MSG_LEN = 64            # Arduino default serial buffer

    def __init__(self, port, baudrate=115200, timeout=1.0):
        """
        Open serial connection to the AD9959 shield.

        Args:
            port: Serial port (e.g. '/dev/ttyUSB0', '/dev/cu.usbmodem*', 'COM3')
            baudrate: Baud rate (default 115200)
            timeout: Read timeout in seconds
        """
        self._ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            dsrdtr=False,
            rtscts=False,
        )
        # Don't toggle DTR on open (prevents Arduino reset on some boards)
        self._ser.dtr = False
        time.sleep(0.1)
        self._ser.reset_input_buffer()
        self._channel = None

    def close(self):
        """Close the serial connection."""
        if self._ser and self._ser.is_open:
            self._ser.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ── Low-level ──────────────────────────────────────────────

    def _send(self, cmd_str):
        """
        Send a raw command string and return the response lines.

        The firmware reads until '\\n', so we append it here.
        """
        msg = cmd_str.strip() + '\n'
        if len(msg) > self.MAX_MSG_LEN:
            raise AD9959Error(
                f"Message too long ({len(msg)} bytes, max {self.MAX_MSG_LEN}). "
                "Split into multiple sends."
            )
        self._ser.write(msg.encode('ascii'))
        self._ser.flush()
        time.sleep(0.05)  # give firmware time to process and respond
        return self._read_response()

    def _read_response(self):
        """Read all available response lines."""
        lines = []
        while self._ser.in_waiting:
            line = self._ser.readline().decode('ascii', errors='replace').strip()
            if line:
                lines.append(line)
        return lines

    def send_raw(self, cmd_str):
        """
        Send a raw command string. For advanced use / direct protocol access.

        Args:
            cmd_str: Raw command string, e.g. "C0;F1000000;A-10"

        Returns:
            List of response lines from the device.
        """
        return self._send(cmd_str)

    # ── Channel selection ──────────────────────────────────────

    def _select_channel(self, channel):
        """Build a channel selection command fragment."""
        if channel not in self.CHANNELS:
            raise OutOfRangeError(f"Channel must be 0-3, got {channel}")
        return f"C{channel}"

    # ── Single-channel commands ────────────────────────────────

    def set_frequency(self, channel, freq_hz):
        """
        Set the output frequency of a channel.

        Args:
            channel: Channel number (0-3)
            freq_hz: Frequency in Hz (100000 - 225000000)

        Returns:
            Response lines from the device.
        """
        freq_hz = int(freq_hz)
        if not (self.FREQ_MIN <= freq_hz <= self.FREQ_MAX):
            raise OutOfRangeError(
                f"Frequency {freq_hz} Hz out of range "
                f"({self.FREQ_MIN} - {self.FREQ_MAX})"
            )
        return self._send(f"C{channel};F{freq_hz}")

    def set_amplitude(self, channel, dbm):
        """
        Set the output amplitude of a channel.

        Args:
            channel: Channel number (0-3)
            dbm: Power level in dBm (-60 to -7)

        Returns:
            Response lines from the device.
        """
        dbm = int(dbm)
        if not (self.AMP_MIN <= dbm <= self.AMP_MAX):
            raise OutOfRangeError(
                f"Amplitude {dbm} dBm out of range "
                f"({self.AMP_MIN} - {self.AMP_MAX})"
            )
        return self._send(f"C{channel};A{dbm}")

    def set_phase(self, channel, degrees):
        """
        Set the output phase of a channel.

        Args:
            channel: Channel number (0-3)
            degrees: Phase in degrees (0 - 360, integer)

        Returns:
            Response lines from the device.
        """
        degrees = int(degrees)
        if not (self.PHASE_MIN <= degrees <= self.PHASE_MAX):
            raise OutOfRangeError(
                f"Phase {degrees} deg out of range "
                f"({self.PHASE_MIN} - {self.PHASE_MAX})"
            )
        return self._send(f"C{channel};P{degrees}")

    def set_channel(self, channel, freq_hz=None, dbm=None, degrees=None):
        """
        Configure a channel with frequency, amplitude, and/or phase in one atomic command.

        All specified parameters are applied simultaneously by the firmware.

        Args:
            channel: Channel number (0-3)
            freq_hz: Frequency in Hz (optional)
            dbm: Amplitude in dBm (optional)
            degrees: Phase in degrees (optional)

        Returns:
            Response lines from the device.
        """
        if channel not in self.CHANNELS:
            raise OutOfRangeError(f"Channel must be 0-3, got {channel}")

        parts = [f"C{channel}"]

        if freq_hz is not None:
            freq_hz = int(freq_hz)
            if not (self.FREQ_MIN <= freq_hz <= self.FREQ_MAX):
                raise OutOfRangeError(f"Frequency {freq_hz} Hz out of range")
            parts.append(f"F{freq_hz}")

        if dbm is not None:
            dbm = int(dbm)
            if not (self.AMP_MIN <= dbm <= self.AMP_MAX):
                raise OutOfRangeError(f"Amplitude {dbm} dBm out of range")
            parts.append(f"A{dbm}")

        if degrees is not None:
            degrees = int(degrees)
            if not (self.PHASE_MIN <= degrees <= self.PHASE_MAX):
                raise OutOfRangeError(f"Phase {degrees} deg out of range")
            parts.append(f"P{degrees}")

        return self._send(";".join(parts))

    # ── Multi-channel batch ────────────────────────────────────

    def configure(self, channels):
        """
        Configure multiple channels in a single message for phase-coherent updates.

        The firmware processes all commands then applies changes to the DDS
        in one batch, so all channels update simultaneously.

        Note: total message must fit in 64 bytes. For 4 channels with full
        params this may require multiple sends. This method auto-splits if needed.

        Args:
            channels: Dict mapping channel number to params dict.
                      e.g. {0: {'freq_hz': 1e6, 'dbm': -10, 'degrees': 0},
                            1: {'freq_hz': 1e6, 'dbm': -10, 'degrees': 90}}

        Returns:
            All response lines.
        """
        all_responses = []

        # Build command parts per channel
        batches = []
        current_batch = []
        current_len = 0

        for ch in sorted(channels.keys()):
            if ch not in self.CHANNELS:
                raise OutOfRangeError(f"Channel must be 0-3, got {ch}")
            params = channels[ch]
            parts = [f"C{ch}"]

            if 'freq_hz' in params:
                f = int(params['freq_hz'])
                if not (self.FREQ_MIN <= f <= self.FREQ_MAX):
                    raise OutOfRangeError(f"Ch{ch} frequency {f} Hz out of range")
                parts.append(f"F{f}")

            if 'dbm' in params:
                a = int(params['dbm'])
                if not (self.AMP_MIN <= a <= self.AMP_MAX):
                    raise OutOfRangeError(f"Ch{ch} amplitude {a} dBm out of range")
                parts.append(f"A{a}")

            if 'degrees' in params:
                p = int(params['degrees'])
                if not (self.PHASE_MIN <= p <= self.PHASE_MAX):
                    raise OutOfRangeError(f"Ch{ch} phase {p} deg out of range")
                parts.append(f"P{p}")

            fragment = ";".join(parts)
            # +1 for the semicolon joining to previous, +1 for newline
            frag_len = len(fragment) + (1 if current_batch else 0) + 1

            if current_batch and current_len + frag_len > self.MAX_MSG_LEN:
                batches.append(";".join(current_batch))
                current_batch = [fragment]
                current_len = len(fragment) + 1  # +1 for newline
            else:
                if current_batch:
                    current_len += 1  # semicolon separator
                current_batch.append(fragment)
                current_len += len(fragment)
                if not current_batch[:-1]:  # first item
                    current_len += 1  # newline

        if current_batch:
            batches.append(";".join(current_batch))

        for batch in batches:
            all_responses.extend(self._send(batch))

        return all_responses

    # ── Output enable/disable ──────────────────────────────────

    def enable(self):
        """Enable all RF outputs."""
        return self._send("E")

    def disable(self):
        """Disable (power down) all RF outputs."""
        return self._send("D")

    # ── Info queries ───────────────────────────────────────────

    def get_version(self):
        """Get firmware version string."""
        lines = self._send("V")
        return lines[0] if lines else None

    def get_model(self):
        """Get device model string."""
        lines = self._send("M")
        return lines[0] if lines else None

    def get_help(self):
        """Get the help text from the device."""
        return "\n".join(self._send("h"))

    # ── Software sweep ─────────────────────────────────────────

    def sweep_frequency(self, channel, start_hz, stop_hz, step_hz, dwell_s):
        """
        Software-driven frequency sweep on a single channel.

        This sends rapid serial commands - not a hardware sweep.
        For the AD9959's built-in hardware sweep, direct register
        access via a custom firmware would be needed.

        Args:
            channel: Channel number (0-3)
            start_hz: Start frequency in Hz
            stop_hz: Stop frequency in Hz
            step_hz: Step size in Hz (positive; direction auto-detected)
            dwell_s: Dwell time per step in seconds

        Yields:
            (frequency_hz, response_lines) tuples at each step.
        """
        if start_hz <= stop_hz:
            freqs = range(int(start_hz), int(stop_hz) + 1, int(abs(step_hz)))
        else:
            freqs = range(int(start_hz), int(stop_hz) - 1, -int(abs(step_hz)))

        for freq in freqs:
            resp = self.set_frequency(channel, freq)
            yield freq, resp
            if dwell_s > 0:
                time.sleep(dwell_s)

    def sweep_amplitude(self, channel, start_dbm, stop_dbm, step_dbm, dwell_s):
        """
        Software-driven amplitude sweep on a single channel.

        Args:
            channel: Channel number (0-3)
            start_dbm: Start amplitude in dBm
            stop_dbm: Stop amplitude in dBm
            step_dbm: Step size in dBm (positive; direction auto-detected)
            dwell_s: Dwell time per step in seconds

        Yields:
            (amplitude_dbm, response_lines) tuples at each step.
        """
        if start_dbm <= stop_dbm:
            amps = range(int(start_dbm), int(stop_dbm) + 1, int(abs(step_dbm)))
        else:
            amps = range(int(start_dbm), int(stop_dbm) - 1, -int(abs(step_dbm)))

        for amp in amps:
            resp = self.set_amplitude(channel, amp)
            yield amp, resp
            if dwell_s > 0:
                time.sleep(dwell_s)

    def sweep_phase(self, channel, start_deg, stop_deg, step_deg, dwell_s):
        """
        Software-driven phase sweep on a single channel.

        Args:
            channel: Channel number (0-3)
            start_deg: Start phase in degrees
            stop_deg: Stop phase in degrees
            step_deg: Step size in degrees
            dwell_s: Dwell time per step in seconds

        Yields:
            (phase_degrees, response_lines) tuples at each step.
        """
        if start_deg <= stop_deg:
            phases = range(int(start_deg), int(stop_deg) + 1, int(abs(step_deg)))
        else:
            phases = range(int(start_deg), int(stop_deg) - 1, -int(abs(step_deg)))

        for phase in phases:
            resp = self.set_phase(channel, phase)
            yield phase, resp
            if dwell_s > 0:
                time.sleep(dwell_s)
