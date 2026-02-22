# AD9959 Library Complete Reference

> **File**: `Libraries/AD9959/AD9959.h`
> **Origin**: Fork of [cjheath/AD9959](https://github.com/cjheath/AD9959), modified by GRA & AFCH
> **Chip**: Analog Devices AD9959 — 4-channel DDS, 500MHz core clock, 10-bit DAC

---

## 1. Architecture

The library is a **single header-file C++ template class**. Pin assignments and reference frequency are compile-time template parameters. There are no `.cpp` files, no virtual functions, no heap allocation.

**SPI Configuration**: 3-wire mode (SDIO_0 = MOSI, SDIO_2 = MISO, SDIO_3 = GND, SDIO_1 = float). SPI_MODE3 (CPOL=1, CPHA=1), MSB-first.

**GRA&AFCH Modifications** (vs upstream cjheath):
- Added `#define GRA_AND_AFCH_AD9959_MOD` guard
- Added runtime `refFreq` parameter to `setClock()` (upstream uses compile-time only)
- Changed default PLL multiplier from 20 to 12
- ~~**Dropped** the `reg&0x7F` mask fix in `write()` (regression bug)~~ — **FIXED** (dds-ycn)

---

## 2. Template Parameters

```cpp
template <
    uint8_t       ResetPin,                    // Arduino pin -> AD9959 RESET (active high)
    uint8_t       ChipEnablePin,               // Arduino pin -> AD9959 CS (active low)
    uint8_t       UpdatePin,                   // Arduino pin -> AD9959 I/O_UPDATE (pulse high to apply)
    unsigned long reference_freq = 25000000,   // Crystal/TCXO frequency in Hz
    long          SPIRate = 2000000,           // SPI clock rate (bits/sec)
    uint8_t       SPIClkPin = 13,              // IGNORED - uses hardware SPI
    uint8_t       SPIMISOPin = 12,             // IGNORED - uses hardware SPI
    uint8_t       SPIMOSIPin = 11              // IGNORED - uses hardware SPI
>
```

| Param | Used At | Notes |
|-------|---------|-------|
| `ResetPin` | `reset()`, constructor | Directly driven via `digitalWrite` |
| `ChipEnablePin` | `chipEnable()`/`chipDisable()` | Low = selected |
| `UpdatePin` | `update()`, `reset()` | Pulsed to latch staged register values |
| `reference_freq` | `setClock()` default arg | Can be overridden at runtime (GRA&AFCH mod) |
| `SPIRate` | `spiBegin()` | Passed to `SPISettings()` |
| `SPIClkPin` | `reset()` only | Pulsed once during reset to enter serial mode |
| `SPIMISOPin` | Never used | Declared but ignored |
| `SPIMOSIPin` | Never used | Declared but ignored |

---

## 3. Private Members

```cpp
uint32_t core_clock;      // Effective DDS core frequency (Hz) = refFreq * PLL_mult * calibration
uint32_t reciprocal;      // Precomputed: 2^(32+shift) / core_clock  (for fast freq->delta)
uint8_t  shift;           // Bit position so reciprocal fits in 32 bits (typically 28-32)
uint8_t  last_channels;   // Cached CSR channel selection (optimization to skip redundant writes)
```

With `DDS_MAX_PRECISION` defined (not used in firmware):
```cpp
uint64_t reciprocal;      // Full precision: (2^64-1) / core_clock
// shift is not needed
```

**Frequency delta computation** (`frequencyDelta()`):
```
FTWD = freq * 2^32 / core_clock
     ≈ freq * reciprocal >> shift    (fast 32x32->64 widening multiply on AVR)
```

---

## 4. Register Map (enum Register)

All registers are accessed via the `write()` function. Registers 0x00-0x02 are global; 0x03-0x18 are per-channel (written to whichever channels are selected in CSR).

| Enum | Addr | Width | Datasheet Name | Description |
|------|------|-------|----------------|-------------|
| `CSR` | 0x00 | 1 byte | Channel Select Register | Channel enable bits [7:4], I/O mode [2:1], bit order [0] |
| `FR1` | 0x01 | 3 bytes | Function Register 1 | PLL multiplier, VCO gain, charge pump, modulation config, sync, power-down |
| `FR2` | 0x02 | 2 bytes | Function Register 2 | All-channel sweep/phase clear, multi-chip sync |
| `CFR` | 0x03 | 3 bytes | Channel Function Register | Per-channel: modulation mode, sweep enable, DAC scale, power-down, pipe delay, accumulator clear, sine/cosine |
| `CFTW` | 0x04 | 4 bytes | Channel Freq Tuning Word | 32-bit frequency tuning word: `f_out = CFTW * f_sysclk / 2^32` |
| `CPOW` | 0x05 | 2 bytes | Channel Phase Offset Word | 14-bit phase offset [13:0], bits [15:14] unused |
| `ACR` | 0x06 | 3 bytes | Amplitude Control Register | Ramp rate [23:16], step size [15:14], multiplier enable [12], ramp enable [11], scale factor [9:0] |
| `LSRR` | 0x07 | 2 bytes | Linear Sweep Rate Register | Falling rate [15:8], rising rate [7:0]. Each tick = 4 * core_clock cycles |
| `RDW` | 0x08 | 4 bytes | Rising Delta Word | Step size added per rising sweep tick |
| `FDW` | 0x09 | 4 bytes | Falling Delta Word | Step size subtracted per falling sweep tick |
| `CW1`-`CW15` | 0x0A-0x18 | 4 bytes each | Channel Word 1-15 | Modulation values or sweep destination (CW1). Format depends on modulation mode |

**Register length lookup table** (in `write()`):
```cpp
// Index:  CSR  FR1  FR2  CFR  CFTW CPOW ACR  LSRR
//         0    1    2    3    4    5    6    7
           1,   3,   2,   3,   4,   2,   3,   2    // registers >= 0x08 default to 4 bytes
```

---

## 5. Bit Field Enums

### 5.1 CSR_Bits (Channel Select Register — 1 byte)

| Enum | Value | Bits | Description |
|------|-------|------|-------------|
| `MSB_First` | 0x00 | [0] | MSB-first bit ordering (default) |
| `LSB_First` | 0x01 | [0] | LSB-first bit ordering |
| `IO2Wire` | 0x00 | [2:1] | 2-wire SPI (SDIO_0 bidirectional) |
| `IO3Wire` | 0x02 | [2:1] | 3-wire SPI (SDIO_0=in, SDIO_2=out) **[used by library]** |
| `IO2Bit` | 0x04 | [2:1] | 2-bit parallel I/O |
| `IO4Bit` | 0x06 | [2:1] | 4-bit parallel I/O |

Channel select is in bits [7:4]: Ch0=0x10, Ch1=0x20, Ch2=0x40, Ch3=0x80.

### 5.2 FR1_Bits (Function Register 1 — 3 bytes)

Written as 3 separate `SPI.transfer()` calls in `setClock()`.

**Byte 0 (MSB):**

| Enum | Value | Bits | Description |
|------|-------|------|-------------|
| `ChargePump0` | 0x00 | [1:0] | Lowest charge pump current (75 uA) |
| `ChargePump1` | 0x01 | [1:0] | |
| `ChargePump2` | 0x02 | [1:0] | |
| `ChargePump3` | 0x03 | [1:0] | Highest (387.5 uA) — fastest lock, most noise **[used]** |
| `PllDivider` | 0x04 | — | Multiply by this to shift multiplier value into bits [6:2] |
| `VCOGain` | 0x80 | [7] | 0=low range (<160MHz), 1=high range (>255MHz) |

**Byte 1 (middle):**

| Enum | Value | Bits | Description |
|------|-------|------|-------------|
| `ModLevels2` | 0x00 | [1:0] | 2-level modulation (profile pin 0 only) **[used]** |
| `ModLevels4` | 0x01 | [1:0] | 4-level modulation (profile pins 0-1) |
| `ModLevels8` | 0x02 | [1:0] | 8-level modulation (profile pins 0-2) |
| `ModLevels16` | 0x03 | [1:0] | 16-level modulation (profile pins 0-3) |
| `RampUpDownOff` | 0x00 | [3:2] | Amplitude ramping disabled **[used]** |
| `RampUpDownP2P3` | 0x04 | [3:2] | Ramp controlled by profile pins 2,3 |
| `RampUpDownP3` | 0x08 | [3:2] | Ramp controlled by profile pin 3 only |
| `RampUpDownSDIO123` | 0x0C | [3:2] | Ramp via SDIO pins (1-bit I/O mode only) |
| `Profile0` | 0x00 | [6:4] | Profile pin mapping (each chan gets own pin) **[used]** |
| `Profile7` | 0x07 | [6:4] | All channels share same profile pins |

**Byte 2 (LSB):**

| Enum | Value | Bits | Description |
|------|-------|------|-------------|
| `SyncAuto` | 0x00 | [1:0] | Automatic sync via SYNC_OUT/SYNC_IN |
| `SyncSoft` | 0x01 | [1:0] | Software sync (slips one clock cycle per write) |
| `SyncHard` | 0x02 | [1:0] | Hardware sync via SYNC_IN pin |
| `DACRefPwrDown` | 0x10 | [4] | Power down DAC reference |
| `SyncClkDisable` | 0x20 | [5] | Disable SYNC_CLK output **[used — always set]** |
| `ExtFullPwrDown` | 0x40 | [6] | External power-down = full power-down |
| `RefClkInPwrDown` | 0x80 | [7] | Power down reference clock input |

### 5.3 FR2_Bits (Function Register 2 — 2 bytes)

| Enum | Value | Bits | Description |
|------|-------|------|-------------|
| `AllChanAutoClearSweep` | 0x8000 | [15] | Auto-clear all sweep accumulators on I/O_UPDATE |
| `AllChanClearSweep` | 0x4000 | [14] | Clear all sweep accumulators immediately |
| `AllChanAutoClearPhase` | 0x2000 | [13] | Auto-clear all phase accumulators on I/O_UPDATE |
| `AllChanClearPhase` | 0x2000 | [12] | Clear all phase accumulators immediately |
| `AutoSyncEnable` | 0x0080 | [7] | Enable automatic multi-chip synchronization |
| `MasterSyncEnable` | 0x0040 | [6] | This chip is the sync master |
| `MasterSyncStatus` | 0x0020 | [5] | Read-only: sync status |
| `MasterSyncMask` | 0x0010 | [4] | Mask sync status output |
| `SystemClockOffset` | 0x0003 | [1:0] | 2-bit system clock offset for sync tuning |

> **BUG (dds-gt5)**: `AllChanClearPhase` is 0x2000, same as `AllChanAutoClearPhase`. Per datasheet bit 12 should be 0x1000.

### 5.4 CFR_Bits (Channel Function Register — 3 bytes, per-channel)

| Enum | Value | Bits | Description |
|------|-------|------|-------------|
| `ModulationMode` | 0xC00000 | [23:22] | Mask for modulation mode field |
| `AmplitudeModulation` | 0x400000 | [23:22]=01 | Amplitude modulation/sweep |
| `FrequencyModulation` | 0x800000 | [23:22]=10 | Frequency modulation/sweep |
| `PhaseModulation` | 0xC00000 | [23:22]=11 | Phase modulation/sweep |
| `SweepNoDwell` | 0x008000 | [15] | Sweep auto-returns to start after reaching endpoint |
| `SweepEnable` | 0x004000 | [14] | Enable linear sweep |
| `SweepStepTimerExt` | 0x002000 | [13] | Reset sweep step timer on I/O_UPDATE |
| `DACFullScale` | 0x000300 | [9:8] | DAC current: 00=1/8, 01=1/4, 10=1/2, 11=full **[always full]** |
| `DigitalPowerDown` | 0x000080 | [7] | Power down DDS core (clocks off) |
| `DACPowerDown` | 0x000040 | [6] | Power down DAC |
| `MatchPipeDelay` | 0x000020 | [5] | Compensate pipeline delay across channels **[always set]** |
| `AutoclearSweep` | 0x000010 | [4] | Clear sweep accumulator on I/O_UPDATE |
| `ClearSweep` | 0x000008 | [3] | Clear sweep accumulator immediately |
| `AutoclearPhase` | 0x000004 | [2] | Clear phase accumulator on I/O_UPDATE |
| `ClearPhase` | 0x000002 | [1] | Clear phase accumulator immediately |
| `OutputSineWave` | 0x000001 | [0] | 1=sine, 0=cosine **[always sine]** |

### 5.5 ACR_Bits (Amplitude Control Register — 3 bytes, per-channel)

| Enum | Value | Bits | Description |
|------|-------|------|-------------|
| `RampRate` | 0xFF0000 | [23:16] | Time between ramp steps (N * 4 core clocks) |
| `StepSize` | 0x00C000 | [15:14] | Amplitude step: 00=1, 01=2, 10=4, 11=8 |
| `MultiplierEnable` | 0x001000 | [12] | Enable the amplitude scaling multiplier |
| `RampEnable` | 0x000800 | [11] | Enable automatic amplitude ramping |
| `LoadARRAtIOUpdate` | 0x000400 | [10] | Reload amplitude ramp rate on I/O_UPDATE |
| `ScaleFactor` | 0x0003FF | [9:0] | 10-bit amplitude scale (0-1023) |

---

## 6. Channel Numbers (enum ChannelNum)

| Enum | Value | CSR bits | Description |
|------|-------|----------|-------------|
| `ChannelNone` | 0x00 | [7:4]=0000 | No channels selected |
| `Channel0` | 0x10 | [7:4]=0001 | Channel 0 only |
| `Channel1` | 0x20 | [7:4]=0010 | Channel 1 only |
| `Channel2` | 0x40 | [7:4]=0100 | Channel 2 only |
| `Channel3` | 0x80 | [7:4]=1000 | Channel 3 only |
| `ChannelAll` | 0xF0 | [7:4]=1111 | All channels simultaneously |

Channels can be OR'd: `Channel0 | Channel1` selects both.

---

## 7. Public Methods

### 7.1 Constructor

```cpp
AD9959()
```

**Sequence**:
1. `SPI.begin()` — initializes hardware SPI
2. Set ResetPin LOW, configure as OUTPUT
3. Set ChipEnablePin HIGH (deselected), configure as OUTPUT
4. Set UpdatePin LOW, configure as OUTPUT
5. Calls `reset()`

**Note**: The DDS chip is fully reset and the PLL is started during construction. Execution takes >1ms for PLL lock. The constructor runs before `setup()` if declared globally.

### 7.2 reset()

```cpp
void reset(CFR_Bits cfr = DACFullScale | MatchPipeDelay | OutputSineWave)
```

**Sequence**:
1. Pulse ResetPin HIGH/LOW (hardware reset, needs 5 cycles of 30MHz ref clock = ~167ns)
2. Pulse SPIClkPin — enters serial I/O loading mode
3. Pulse UpdatePin — latches serial mode
4. Select all channels, write CFR with provided bits
5. Select no channels (sets 3-wire MSB mode in CSR)
6. Pulse UpdatePin to apply
7. Calls `setClock()` — starts PLL

**Default CFR bits**: Full-scale DAC current, pipeline delay compensation, sine wave output.

### 7.3 setClock()

```cpp
void setClock(int mult = 12, uint32_t refFreq = reference_freq, int32_t calibration = 0)
```

| Param | Range | Description |
|-------|-------|-------------|
| `mult` | 4-20 (or <4 to disable PLL) | PLL multiplication factor |
| `refFreq` | Hz | Reference clock frequency (GRA&AFCH addition) |
| `calibration` | parts-per-billion | Frequency error correction |

**Computation**:
```
core_clock = refFreq * (1000000000 + calibration) / 1000000000 * mult
```

Then computes the `reciprocal` and `shift` values for fast frequency-to-delta conversion.

**SPI writes** (FR1 register, 3 bytes):
- Byte 0: VCO Gain (if core_clock > 200 **[BUG: should be >200000000]**) | PLL multiplier | ChargePump3
- Byte 1: ModLevels2 | RampUpDownOff | Profile0
- Byte 2: SyncClkDisable

> **BUG (dds-2k7)**: VCO Gain threshold compares against 200 (literal) instead of 200000000 (Hz). VCO Gain is always enabled.

### 7.4 frequencyDelta()

```cpp
uint32_t frequencyDelta(uint32_t freq) const
```

Converts a frequency in Hz to a 32-bit Frequency Tuning Word (FTW).

**Formula**: `FTW = round(freq * 2^32 / core_clock)`

**Implementation**: Uses precomputed reciprocal for a fast 32x32->64 widening multiply (avoids 64-bit division at runtime, ~33us on AVR).

**Accuracy**: Standard deviation < 0.05 Hz across full range per the test suite.

### 7.5 setFrequency()

```cpp
void setFrequency(ChannelNum chan, uint32_t freq)
```

Shorthand for `setDelta(chan, frequencyDelta(freq))`.

**SPI transactions**: 2 (one for CSR if channel changed, one for CFTW).

**Does NOT call `update()`** — changes are staged until `update()` is called.

### 7.6 setDelta()

```cpp
void setDelta(ChannelNum chan, uint32_t delta)
```

Writes a precomputed frequency tuning word directly to the CFTW register.

**Use case**: When the same frequency is set repeatedly, compute the delta once with `frequencyDelta()` and reuse it.

### 7.7 setAmplitude()

```cpp
void setAmplitude(ChannelNum chan, uint16_t amplitude)
```

| Value | Meaning |
|-------|---------|
| 0-1023 | Scaled output. Multiplier enabled, scale factor = amplitude |
| 1024 | Full scale. Multiplier bypassed (no attenuation) |
| >1024 | Clamped to 1024 |

**SPI sequence** (manual ACR write, not via `write()`):
- Byte 0: RampRate = 0 (no ramping)
- Byte 1: MultiplierEnable | amplitude[9:8] (if <1024), else 0 (bypass)
- Byte 2: amplitude[7:0]

**Note**: The 10-bit scale factor is a linear multiplier on the DAC output. The firmware converts dBm to ASF using: `ASF = 10^((-dBm + 3 + 60.206) / 20)`.

### 7.8 setPhase()

```cpp
void setPhase(ChannelNum chan, uint16_t phase)
```

Writes a 14-bit phase offset word to CPOW. Values 0-16383 map linearly to 0-360 degrees.

**Masking**: `phase & 0x3FFF` — top 2 bits are stripped.

**Conversion**: The firmware converts degrees to POW using: `POW = (degrees_x10 / 3600.0) * 16384`.

### 7.9 update()

```cpp
void update()
```

Pulses the I/O_UPDATE pin HIGH then LOW. This atomically latches all staged register changes into the active registers of the DDS. All channels update simultaneously.

### 7.10 sweepFrequency()

```cpp
void sweepFrequency(ChannelNum chan, uint32_t freq, bool follow = true)
```

Configures a frequency sweep to the target `freq`. Calls `sweepDelta()` with the computed delta.

### 7.11 sweepDelta()

```cpp
void sweepDelta(ChannelNum chan, uint32_t delta, bool follow = true)
```

**SPI writes**:
1. CFR = FrequencyModulation | SweepEnable | DACFullScale | MatchPipeDelay | (NoDwell if !follow)
2. CW1 = delta (sweep endpoint)

**Sweep direction** is controlled by profile pins (not by the library). Profile HIGH = sweep up, LOW = sweep down.

| Mode | `follow=true` | `follow=false` (NoDwell) |
|------|---------------|--------------------------|
| Behavior | Follows profile pin up/down | Sweeps up on rising edge, then snaps back |

### 7.12 sweepAmplitude()

```cpp
void sweepAmplitude(ChannelNum chan, uint16_t amplitude, bool follow = true)
```

Configures an amplitude sweep. Writes CW1 with amplitude MSB-aligned: `amplitude << 22`.

### 7.13 sweepPhase()

```cpp
void sweepPhase(ChannelNum chan, uint16_t phase, bool follow = true)
```

Configures a phase sweep. Writes CW1 with phase MSB-aligned: `phase << 18`.

> **BUG (dds-4q1)**: Contains typo `MatchPipeDela` — won't compile.

### 7.14 sweepRates()

```cpp
void sweepRates(ChannelNum chan, uint32_t increment, uint8_t up_rate,
                uint32_t decrement = 0, uint8_t down_rate = 0)
```

Configures sweep step sizes and rates.

**SPI writes**:
1. RDW = `increment` (rising sweep step size)
2. FDW = `increment` (falling sweep step size) **[BUG: should be `decrement`]**
3. LSRR = `(down_rate << 8) | up_rate`

**Rate timing**: Each rate unit = 4 core clock cycles. At 500MHz core: rate=1 gives 8ns steps, rate=125 gives 1us, rate=255 gives 2.04us.

> **BUG (dds-dr8)**: FDW is written with `increment` instead of `decrement`. Asymmetric sweeps are impossible.

### 7.15 setChannels()

```cpp
void setChannels(ChannelNum chan)
```

Writes CSR to select which channels receive subsequent register writes. Optimized: skips the SPI transaction if `chan` matches `last_channels`.

**CSR value written**: `chan | MSB_First | IO3Wire`

### 7.16 read()

```cpp
uint32_t read(Register reg)
```

Reads back a register value. **Must first select exactly one channel** via `setChannels()` for per-channel registers.

**Implementation**: Calls `write(0x80 | reg, 0)` — the 0x80 bit signals a read to the AD9959.

> **BUG (dds-ycn)**: The `write()` function doesn't mask off bit 7 when looking up register length. All reads default to 4-byte length, corrupting reads of shorter registers.

---

## 8. Protected Methods

### 8.1 write()

```cpp
uint32_t write(uint8_t reg, uint32_t value)
```

The core SPI transfer function. Handles both reads and writes.

**Protocol**:
1. `spiBegin()` — start SPI transaction, assert CS
2. Transfer register address byte (bit 7 = read flag)
3. Transfer `len` data bytes MSB-first, collecting return data
4. `spiEnd()` — deassert CS, end transaction

**Register length determination**:
```cpp
static constexpr uint8_t register_length[8] = { 1, 3, 2, 3, 4, 2, 3, 2 };
int len = reg < sizeof(register_length) ? register_length[reg] : 4;
```

> **BUG**: For reads, `reg` has bit 7 set (e.g., 0x84 for CFTW). The comparison `0x84 < 8` is always false, so all reads use len=4. The upstream fix uses `(reg&0x7F)` for comparison and `register_length[reg&0x07]` for indexing.

### 8.2 Pin Helpers

```cpp
void pulse(uint8_t pin)   // raise then lower
void lower(uint8_t pin)   // digitalWrite LOW
void raise(uint8_t pin)   // digitalWrite HIGH
void chipEnable()          // lower(ChipEnablePin)
void chipDisable()         // raise(ChipEnablePin)
```

### 8.3 SPI Helpers

```cpp
void spiBegin()   // SPI.beginTransaction(SPISettings(SPIRate, MSBFIRST, SPI_MODE3)); chipEnable()
void spiEnd()     // chipDisable(); SPI.endTransaction()
```

---

## 9. Firmware Usage Map (HW2.x v2.04)

### 9.1 Instantiation

```cpp
// DDS9959v2.2_Firmware.ino:76-89
class MyAD9959 : public AD9959<
    12,          // ResetPin
    6,           // ChipEnablePin
    5,           // UpdatePin (I/O_UPDATE)
    40000000     // 40MHz reference (TCXO)
> {
  public:
    void AllChanAutoClearPhase() {
      write(MyAD9959::FR2, FR2_Bits::AllChanAutoClearPhase);
    }
};
MyAD9959 dds;
```

**Note**: The firmware subclasses AD9959 to add `AllChanAutoClearPhase()` which directly writes FR2. This accesses the `protected` `write()` method, hence the subclass.

### 9.2 Initialization Sequence

```
Global construction (before setup()):
  1. AD9959() constructor
     -> SPI.begin()
     -> Configure pins (Reset=12, CS=6, Update=5)
     -> reset()
        -> Pulse reset, SCLK, update pins
        -> Write CFR to all channels (DACFullScale | MatchPipeDelay | OutputSineWave)
        -> setClock(mult=12, refFreq=40000000, cal=0)
           -> core_clock = 40MHz * 12 = 480MHz
           -> Writes FR1: VCOGain=1, PLL=12, ChargePump3, ModLevels2, SyncClkDisable

setup():
  2. LoadClockSettings() [Menu.ino:462]
     -> Reads EEPROM (or uses defaults: TCXO src, 50MHz ref, N=10)
     -> selectClockSrcPath() — sets hardware RF switch
     -> dds.setClock(N, RefClk, 0)
        -> For defaults: setClock(10, 50000000, 0) -> core_clock = 500MHz

  3. LoadMainSettings() [Menu.ino:298]
     -> Reads per-channel freq/amplitude/phase from EEPROM
     -> (or uses defaults: 100MHz, -3dBm, 0.0 deg)

  4. dds.AllChanAutoClearPhase() [line 212]
     -> Writes FR2 = AllChanAutoClearPhase (0x2000)

  5. ApplyChangesToDDS() [line 213]
     -> For each channel 0-3:
        dds.setFrequency(channelN, freqN)
        dds.setAmplitude(channelN, dBmToASF(amplitudeN))
        dds.setPhase(channelN, DegToPOW(phaseN))
     -> dds.update()
```

### 9.3 Runtime Usage

**Encoder rotation (edit mode)**:
```
loop() -> curItem->incValue()/decValue() -> ApplyChangesToDDS()
  -> setFrequency() x4, setAmplitude() x4, setPhase() x4, update()
```
All 4 channels are rewritten on every encoder tick.

**Serial commands**:
```
ReadSerialCommands() -> modifies menu values -> ApplyChangesToDDS()
```

**Clock source change (via SETUP menu)**:
```
CoreClockSaveClass::goToEditMode() -> dds.setClock(N, RefClk, 0) -> ApplyChangesToDDS()
```

### 9.4 Library Functions Used by Firmware

| Function | Called From | Frequency |
|----------|-----------|-----------|
| `AD9959()` constructor | Global init | Once |
| `reset()` | Via constructor | Once |
| `setClock(mult, refFreq, 0)` | `LoadClockSettings()`, clock menu save | On boot + clock change |
| `setFrequency(chan, freq)` | `ApplyChangesToDDS()` | Every encoder tick / serial cmd |
| `setAmplitude(chan, asf)` | `ApplyChangesToDDS()` | Every encoder tick / serial cmd |
| `setPhase(chan, pow)` | `ApplyChangesToDDS()` | Every encoder tick / serial cmd |
| `update()` | `ApplyChangesToDDS()` | Every encoder tick / serial cmd |
| `write(FR2, ...)` | `AllChanAutoClearPhase()` | Once at boot |

### 9.5 Library Functions NOT Used by Firmware

| Function | Why Not Used |
|----------|-------------|
| `frequencyDelta()` | Called indirectly via `setFrequency()` |
| `setDelta()` | Called indirectly via `setFrequency()` |
| `sweepFrequency()` | No sweep feature in firmware |
| `sweepDelta()` | No sweep feature in firmware |
| `sweepAmplitude()` | No sweep feature in firmware |
| `sweepPhase()` | Would not compile (typo bug) |
| `sweepRates()` | No sweep feature in firmware |
| `setChannels()` | Called indirectly by set* functions |
| `read()` | No register readback in firmware |

### 9.6 Firmware Conversion Functions

```cpp
// Degrees (with 0.1 resolution) to 14-bit Phase Offset Word
uint32_t DegToPOW(uint16_t deg_x10) {
    return (deg_x10 / 3600.0) * 16384;
}

// dBm (positive, representing negative) to 10-bit Amplitude Scale Factor
uint16_t dBmToASF(uint8_t dBm) {
    return (uint16_t)powf(10, (-1*dBm + 3 + 60.206) / 20.0);
}
// Formula: ASF = 10^((P_dBm + 3 + 20*log10(1024)) / 20)
// At -3dBm: ASF = 1024 (full scale)
// At -60dBm: ASF ≈ 1
```

---

## 10. What the Chip CAN Do That the Library DOESN'T Support

### 10.1 Modulation (Profile Pin Multiplexed Values)

The AD9959 supports **2/4/8/16-level modulation** of frequency, amplitude, or phase using profile pins and the CW1-CW15 registers.

| Levels | Profile Pins Used | Registers |
|--------|-------------------|-----------|
| 2 | P0 | CFTW + CW1 |
| 4 | P0, P1 | CFTW + CW1-CW3 |
| 8 | P0, P1, P2 | CFTW + CW1-CW7 |
| 16 | P0, P1, P2, P3 | CFTW + CW1-CW15 |

This enables FSK, PSK, ASK keying. The library defines the CW registers and FR1 modulation level bits but provides no API to load them or configure modulation.

**What's needed**: A `setModulation()` function that writes CFR modulation mode, FR1 modulation levels, and loads CW register values.

### 10.2 Per-Channel Power Down

The chip supports independent power-down of each channel's DDS core (CFR bit 7) and DAC (CFR bit 6). The library defines these bits but has no API.

The firmware uses an external GPIO pin (pin 13, `POWER_DOWN_CONTROL_PIN`) for all-channel on/off, which is less granular.

**What's needed**: `setChannelPower(chan, bool digital, bool dac)`.

### 10.3 Amplitude Ramping

The ACR register supports automatic amplitude ramping: when RampEnable is set, the DAC output ramps from current to target amplitude at a configurable rate and step size.

This is useful for:
- Soft start/stop to avoid transients
- Shaped-envelope keying
- Amplitude tapering during frequency sweeps

The library defines all ACR bits but `setAmplitude()` hardcodes RampRate=0 and never sets RampEnable.

**What's needed**: `setAmplitudeRamp(chan, target, rate, stepSize)`.

### 10.4 Multi-Chip Synchronization

The AD9959 has a synchronization system for phase-coherent operation across multiple chips:
- SYNC_CLK output (currently disabled by the library)
- SYNC_IN input
- FR2 sync bits: AutoSyncEnable, MasterSyncEnable, SystemClockOffset
- FR1 sync modes: SyncAuto, SyncSoft, SyncHard

**What's needed**: `configureSyncMaster()` / `configureSyncSlave()`.

### 10.5 Profile Pin Control

The library mentions profile pins in comments but doesn't provide any control. The AD9959 uses profile pins [P0:P3] for:
- Starting/stopping sweeps (sweep direction follows pin state)
- Selecting modulation levels (pin combination selects CW register)
- Amplitude ramp up/down direction

The firmware defines profile pins (P0=16, P1=15, P2=14, P3=4) and sets them LOW at boot, but never changes them.

**What's needed**: Either library-level `setProfilePins()` or at minimum documentation of which pins do what.

### 10.6 DAC Current Scaling

CFR bits [9:8] control DAC full-scale current in 4 steps (1/8, 1/4, 1/2, full). The library always sets `DACFullScale` (0x300 = both bits = full scale).

**What's needed**: `setDACScale(chan, scale)` for power management.

### 10.7 Sweep Step Timer Reset

CFR bit 13 (`SweepStepTimerExt`) resets the sweep step timer on I/O_UPDATE, allowing precise sweep restart synchronization. The bit is defined but never used.

### 10.8 Register Readback (Broken)

The `read()` function exists but is broken due to the missing `reg&0x7F` mask in `write()`. Even if fixed, the firmware never reads back registers.

### 10.9 LSB-First / Parallel I/O Modes

The CSR supports LSB-first bit ordering and 2-bit/4-bit parallel I/O modes. The library hardcodes MSB-first + 3-wire serial.

---

## 11. Known Bugs (All Fixed — Convoy dds-63u)

### P1 — Critical (FIXED)

| Bead | Line | Bug | Fix |
|------|------|-----|-----|
| dds-ycn | 451 | `write()` missing `reg&0x7F` mask — reads used wrong register length | Added `(reg&0x7F)` mask to both bounds check and array index |
| dds-4q1 | 376 | `sweepPhase()` typo `MatchPipeDela` — won't compile | Corrected to `MatchPipeDelay` |
| dds-dr8 | 388 | `sweepRates()` writes `increment` to FDW — decrement ignored | Changed to write `decrement` to FDW |

### P2 — Significant (FIXED)

| Bead | Line | Bug | Fix |
|------|------|-----|-----|
| dds-2k7 | 268 | VCO Gain threshold `> 200` — always enabled | Changed to `> 200000000` (200MHz) |
| dds-gt5 | 161 | `AllChanClearPhase` = 0x2000 duplicates AutoClearPhase | Changed to `0x1000` (bit 12) per datasheet |

### P3 — Documentation/Minor (FIXED)

| Bead | Line | Bug | Fix |
|------|------|-----|-----|
| dds-65y | 245 | README documents default PLL mult=20, actual is 12 | Updated README to reflect GRA&AFCH defaults and setClock() signature |

---

## 12. SPI Transaction Summary

Every library call that touches the DDS results in one or more SPI transactions. Each transaction is: assert CS, send register address byte, send/receive N data bytes, deassert CS.

| Operation | Transactions | Bytes on wire |
|-----------|-------------|---------------|
| `setFrequency(chan, freq)` | 1-2 | CSR(2) + CFTW(5) = 7 max |
| `setAmplitude(chan, amp)` | 1-2 | CSR(2) + ACR(4) = 6 max |
| `setPhase(chan, phase)` | 1-2 | CSR(2) + CPOW(3) = 5 max |
| `update()` | 0 (GPIO only) | 0 |
| `setClock(...)` | 1 | FR1(4) = 4 |
| `ApplyChangesToDDS()` | ~13 | ~4 CSR + 4 CFTW + 4 ACR + 4 CPOW + 1 update |

At 2Mbps SPI: `ApplyChangesToDDS()` transfers ~65 bytes = ~260us of SPI time.

---

## 13. Quick Reference Card

```
INIT:    AD9959<ResetPin, CSPin, UpdatePin, RefFreq> dds;
         dds.setClock(mult, refFreq, calibration_ppb);

SET:     dds.setFrequency(Channel0, 10000000);   // 10 MHz
         dds.setAmplitude(Channel0, 512);          // Half scale
         dds.setPhase(Channel0, 8192);             // 180 degrees
         dds.update();                             // Apply all

SWEEP:   dds.sweepFrequency(Channel0, 20000000);  // Sweep target
         dds.sweepRates(Channel0, inc, 125, dec, 250);
         dds.update();
         // Toggle profile pin to start sweep

READ:    dds.setChannels(Channel0);
         uint32_t ftw = dds.read(AD9959::CFTW);

CHANNELS: Channel0=0x10  Channel1=0x20  Channel2=0x40  Channel3=0x80
          ChannelAll=0xF0  (OR them: Channel0|Channel1)

LIMITS:  Frequency: 0 to core_clock/2 (typ. 0-250MHz)
         Amplitude: 0-1023 (scaled), 1024 (full, bypass)
         Phase:     0-16383 (14-bit, 0-360 degrees)
         PLL mult:  4-20 (or disabled)
```
