# AD9959 DDS Serial Protocol Reference

Firmware: HW2.x v2.04 | GRA & AFCH DDS9959

## Connection Settings

| Parameter | Value |
|-----------|-------|
| Baud Rate | 115200 |
| Data Bits | 8 |
| Stop Bits | 1 |
| Parity    | None |
| DTR       | **OFF** (HIGH will reset Arduino MEGA) |
| Line ending | `\n` (LF) |
| Max message | 64 bytes (Arduino HardwareSerial default RX buffer) |
| Serial timeout | 10 ms (`Serial.setTimeout(10)`) |

## Boot Banner

On power-up or reset, the board sends (followed by 3 second delay):
```
DDS AD9959 by GRA & AFCH
HW v2.x
SW v2.04
CoreClock
```

## Command Format

```
<CMD><VALUE>[;<CMD><VALUE>]...\n
```

- Each command is a **single ASCII letter** immediately followed by a **signed integer value** (no space).
- Multiple commands are separated by `;` (semicolon).
- The line must end with `\n` (newline / LF).
- Parsing: `sscanf(token, "%c%ld", &command, &value)` — the value is a `long int`.
- Commands that don't need a value (V, M, h, E, D) still parse a value but ignore it.

### Important: Channel State

The `C` command sets a **global channel variable** that persists until changed or board reset. Commands `F`, `A`, `P` require `C` to have been called first (`C` defaults to `-1` = unset). If channel is not set, these commands print an error and **return early** (remaining chained commands are skipped due to `return`).

## Commands

### C — Select Channel
```
C<channel>
```
| Param | Type | Range | Description |
|-------|------|-------|-------------|
| channel | int | 0–3 | RF output channel (F0–F3) |

**Success response:** `The Channel number is set to: <channel>`
**Error response:** `The Channel number is OUT OF RANGE (0 — 3)`

---

### F — Set Frequency
```
F<frequency_hz>
```
| Param | Type | Range | Description |
|-------|------|-------|-------------|
| frequency_hz | long | 100000–ui32HIGH_FREQ_LIMIT | Frequency in Hz |

`ui32HIGH_FREQ_LIMIT` = `DDS_Core_Clock * 0.45`. At default 500 MHz core clock, this is **225,000,000 Hz** (225 MHz). The limit changes dynamically with core clock configuration.

**Requires:** Channel selected via `C` first.
**Success response:**
```
The Channel number is set to: 0
The Frequency of Channel 0 is set to: 10000000
```
**Error responses:**
- `The output Channel is not selected! Use "C" command to select the Channel.`
- `Frequency is OUT OF RANGE (100000 - 225000000)`

**Internal:** Decomposes Hz value into MHz/kHz/Hz menu fields. Updates DDS hardware via `ApplyChangesToDDS()`.

**Fixed (v2.04+):** The copy-paste bug where channels 1–3 set `F0OutputFreq` has been corrected.

---

### A — Set Amplitude
```
A<dbm>
```
| Param | Type | Range | Description |
|-------|------|-------|-------------|
| dbm | int | -60 to -3 | Power level in dBm (negative) |

**Requires:** Channel selected via `C` first.
**Success response:** `The Power (Amplitude) of Channel 0 is set to: -10`
**Error response:** `Power is OUT OF RANGE (-60 — -3)`

**Internal:** Stores as positive value internally (`value * -1`). Converted to ASF via `dBmToASF()`: `10^((-1*dBm + 3 + 60.206) / 20.0)`.

---

### P — Set Phase
```
P<degrees>[.<fraction>]
```
| Param | Type | Range | Description |
|-------|------|-------|-------------|
| degrees | float | 0–360.0 | Phase offset in degrees (0.1° resolution) |

**Requires:** Channel selected via `C` first.
**Success response:** `The Phase of Channel 0 is set to: 90.5`
**Error response:** `Phase is OUT OF RANGE (0 — 360)`

Supports fractional degrees with 0.1° resolution (e.g., `P90.5` for 90.5°). Bare integer values still work (e.g., `P90` for 90.0°).

**Internal:** Phase converted to Phase Offset Word via `DegToPOW()`: `(degrees * 10 + fraction) / 3600.0 * 16384`.

---

### E — Enable Outputs
```
E           Enable all outputs
E<channel>  Enable single channel (0-3)
```
- `E` (no argument): Enables all 4 RF outputs via `POWER_DOWN_CONTROL_PIN` (pin 13) LOW.
- `E0`–`E3`: Enables a single channel via AD9959 CFR power-down bits.

**Response (all):** `Outputs Enabled`
**Response (single):** `Channel 0 Enabled`

---

### D — Disable Outputs
```
D           Disable all outputs
D<channel>  Disable single channel (0-3)
```
- `D` (no argument): Disables all 4 RF outputs via `POWER_DOWN_CONTROL_PIN` (pin 13) HIGH.
- `D0`–`D3`: Disables a single channel via AD9959 CFR power-down bits.

**Response (all):** `Outputs Disabled`
**Response (single):** `Channel 0 Disabled`

---

### Q — Query Channel State
```
Q
```
Returns the current state of the selected channel.

**Requires:** Channel selected via `C` first.
**Response:** `CH0 F=10000000 A=-10 P=90.0`

The response includes frequency (Hz), amplitude (dBm, negative), and phase (degrees with fraction).

---

### V — Get Firmware Version
```
V
```
**Response:** `2.04` (the float value of `FIRMWAREVERSION`)

---

### M — Get Model
```
M
```
**Response:** `DDS9959 v2.x`

---

### h — Help
```
h
```
**Response:** Multi-line help text from PROGMEM listing all commands and an example.

---

### Unknown Command
Any unrecognized command letter prints:
```
Unknown command:<letter>
```
Followed by the full help text.

## Chained Command Examples

```
C0;F10000000;A-10;P0       Set CH0: 10MHz, -10dBm, 0°
C1;F50000000;A-20;P90.5    Set CH1: 50MHz, -20dBm, 90.5°
C0;F100000000               Set CH0: 100MHz (keep existing amp/phase)
C0;Q                         Query CH0 state
D                            Disable all outputs
D2                           Disable only CH2
E                            Re-enable all outputs
E2                           Re-enable CH2
V                            Query version
```

## Timing Considerations

- `Serial.setTimeout(10)` — the firmware waits only 10 ms for complete message arrival via `readBytesUntil`.
- Send the entire command line as a single write, not character-by-character.
- After sending, allow ~100 ms for processing and response (DDS SPI writes + display update).
- No flow control (no RTS/CTS, no XON/XOFF).

## What's NOT Supported

| Feature | Notes |
|---------|-------|
| Clock configuration via serial | Must use encoder/OLED menu |
| Sweep/modulation control | Not exposed via serial |
| Binary protocol | Text-only, no binary frames |
