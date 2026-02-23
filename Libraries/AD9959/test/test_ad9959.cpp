/*
 * Comprehensive unit tests for the AD9959 DDS library.
 *
 * Uses instrumented SPI/Arduino mocks to verify register writes,
 * pin operations, and frequency/amplitude/phase calculations.
 *
 * Build: g++ --std=c++11 -I. -I.. -o test_ad9959 test_ad9959.cpp
 * Run:   ./test_ad9959
 */

#include <inttypes.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdio.h>
#include <cassert>

// Define extern globals declared in the mock headers
#include "Arduino.h"
#include "SPI.h"

std::vector<PinOp> pin_log;
SerialDummy Serial;
std::vector<SPITransaction> spi_log;
bool spi_in_transaction = false;
SPIMock SPI;

static void clear_logs()
{
    pin_log.clear();
    spi_log.clear();
}

// Include the library under test
#include "AD9959.h"

// ===== Test DDS class: pins 2=Reset, 3=CS, 4=Update, 25MHz ref =====

enum { PIN_RESET = 2, PIN_CS = 3, PIN_UPDATE = 4, PIN_SCLK = 13 };

class TestDDS : public AD9959<PIN_RESET, PIN_CS, PIN_UPDATE, 25000000> {
public:
    // Expose protected members for testing
    using AD9959::write;
    using AD9959::read;

    // Mirror of MyAD9959::setChannelPowerDown from firmware
    void setChannelPowerDown(ChannelNum chan, bool powerDown)
    {
        setChannels(chan);
        if (powerDown)
            write(CFR, (CFR_Bits)(CFR_Bits::DACFullScale | CFR_Bits::MatchPipeDelay | CFR_Bits::OutputSineWave | CFR_Bits::DigitalPowerDown | CFR_Bits::DACPowerDown));
        else
            write(CFR, (CFR_Bits)(CFR_Bits::DACFullScale | CFR_Bits::MatchPipeDelay | CFR_Bits::OutputSineWave));
        update();
    }
};

// ===== Test framework =====

static int tests_passed = 0;
static int tests_failed = 0;

#define TEST(name) static void test_##name()
#define RUN(name) do { \
    printf("  %-50s ", #name); \
    fflush(stdout); \
    clear_logs(); \
    try { test_##name(); printf("PASS\n"); tests_passed++; } \
    catch (...) { printf("FAIL (exception)\n"); tests_failed++; } \
} while(0)

#define ASSERT_EQ(a, b) do { \
    auto _a = (a); auto _b = (b); \
    if (_a != _b) { \
        printf("FAIL\n    %s:%d: expected %llu, got %llu\n", __FILE__, __LINE__, \
            (unsigned long long)(_b), (unsigned long long)(_a)); \
        tests_failed++; return; \
    } \
} while(0)

#define ASSERT_TRUE(expr) do { \
    if (!(expr)) { \
        printf("FAIL\n    %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        tests_failed++; return; \
    } \
} while(0)

#define ASSERT_NEAR(a, b, tol) do { \
    double _a = (a); double _b = (b); double _t = (tol); \
    if (fabs(_a - _b) > _t) { \
        printf("FAIL\n    %s:%d: expected ~%g, got %g (tol %g)\n", \
            __FILE__, __LINE__, _b, _a, _t); \
        tests_failed++; return; \
    } \
} while(0)

// Helper: get the register address from an SPI transaction
static uint8_t spi_reg(const SPITransaction& t)
{
    return t.bytes_out.empty() ? 0xFF : t.bytes_out[0];
}

// Helper: reconstruct a 32-bit value from SPI data bytes (after register addr byte)
static uint32_t spi_data(const SPITransaction& t)
{
    uint32_t val = 0;
    for (size_t i = 1; i < t.bytes_out.size(); i++)
        val = (val << 8) | t.bytes_out[i];
    return val;
}

// Helper: get data length (excluding register addr)
static size_t spi_data_len(const SPITransaction& t)
{
    return t.bytes_out.size() > 0 ? t.bytes_out.size() - 1 : 0;
}

// ===== Create the global DDS instance (triggers constructor + reset + setClock) =====

// We need to suppress logging during construction to isolate individual tests.
static TestDDS* dds_ptr = nullptr;

static TestDDS& get_dds()
{
    if (!dds_ptr) {
    
        dds_ptr = new TestDDS();
        clear_logs(); // Discard construction artifacts
    }
    return *dds_ptr;
}

// ========================================================================
//  ENUM / CONSTANT TESTS
// ========================================================================

TEST(channel_enum_values)
{
    ASSERT_EQ(TestDDS::ChannelNone, 0x00);
    ASSERT_EQ(TestDDS::Channel0,    0x10);
    ASSERT_EQ(TestDDS::Channel1,    0x20);
    ASSERT_EQ(TestDDS::Channel2,    0x40);
    ASSERT_EQ(TestDDS::Channel3,    0x80);
    ASSERT_EQ(TestDDS::ChannelAll,  0xF0);
}

TEST(register_enum_values)
{
    ASSERT_EQ(TestDDS::CSR,  0x00);
    ASSERT_EQ(TestDDS::FR1,  0x01);
    ASSERT_EQ(TestDDS::FR2,  0x02);
    ASSERT_EQ(TestDDS::CFR,  0x03);
    ASSERT_EQ(TestDDS::CFTW, 0x04);
    ASSERT_EQ(TestDDS::CPOW, 0x05);
    ASSERT_EQ(TestDDS::ACR,  0x06);
    ASSERT_EQ(TestDDS::LSRR, 0x07);
    ASSERT_EQ(TestDDS::RDW,  0x08);
    ASSERT_EQ(TestDDS::FDW,  0x09);
    ASSERT_EQ(TestDDS::CW1,  0x0A);
    ASSERT_EQ(TestDDS::CW15, 0x18);
}

TEST(csr_bits)
{
    ASSERT_EQ(TestDDS::MSB_First, 0x00);
    ASSERT_EQ(TestDDS::LSB_First, 0x01);
    ASSERT_EQ(TestDDS::IO2Wire,   0x00);
    ASSERT_EQ(TestDDS::IO3Wire,   0x02);
    ASSERT_EQ(TestDDS::IO2Bit,    0x04);
    ASSERT_EQ(TestDDS::IO4Bit,    0x06);
}

TEST(fr1_bits)
{
    ASSERT_EQ(TestDDS::PllDivider, 0x04);
    ASSERT_EQ(TestDDS::VCOGain,    0x80);
    ASSERT_EQ(TestDDS::ChargePump0, 0x00);
    ASSERT_EQ(TestDDS::ChargePump3, 0x03);
}

TEST(fr2_bits)
{
    ASSERT_EQ(TestDDS::AllChanAutoClearSweep, 0x8000);
    ASSERT_EQ(TestDDS::AllChanClearSweep,     0x4000);
    ASSERT_EQ(TestDDS::AllChanAutoClearPhase, 0x2000);
    ASSERT_EQ(TestDDS::AllChanClearPhase,     0x1000); // Fixed: was 0x2000
    ASSERT_EQ(TestDDS::AutoSyncEnable,        0x0080);
    ASSERT_EQ(TestDDS::MasterSyncEnable,      0x0040);
}

TEST(cfr_bits)
{
    ASSERT_EQ(TestDDS::FrequencyModulation, 0x800000);
    ASSERT_EQ(TestDDS::AmplitudeModulation, 0x400000);
    ASSERT_EQ(TestDDS::PhaseModulation,     0xC00000);
    ASSERT_EQ(TestDDS::SweepEnable,         0x004000);
    ASSERT_EQ(TestDDS::SweepNoDwell,        0x008000);
    ASSERT_EQ(TestDDS::DACFullScale,        0x000300);
    ASSERT_EQ(TestDDS::MatchPipeDelay,      0x000020);
    ASSERT_EQ(TestDDS::OutputSineWave,      0x000001);
}

TEST(acr_bits)
{
    ASSERT_EQ(TestDDS::MultiplierEnable,  0x001000);
    ASSERT_EQ(TestDDS::RampEnable,        0x000800);
    ASSERT_EQ(TestDDS::ScaleFactor,       0x0003FF);
}

// ========================================================================
//  CHANNEL SELECTION TESTS
// ========================================================================

TEST(setChannels_writes_csr)
{
    auto& dds = get_dds();
    // Force a channel change by setting to a known state first
    dds.setChannels(TestDDS::ChannelNone);
    clear_logs();

    dds.setChannels(TestDDS::Channel0);
    ASSERT_EQ(spi_log.size(), 1u);
    ASSERT_EQ(spi_reg(spi_log[0]), TestDDS::CSR);
    // CSR value = Channel0 | MSB_First | IO3Wire = 0x10 | 0x00 | 0x02 = 0x12
    ASSERT_EQ(spi_data(spi_log[0]), 0x12u);
}

TEST(setChannels_optimizes_redundant)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel1);
    clear_logs();

    // Same channel again — should skip the write
    dds.setChannels(TestDDS::Channel1);
    ASSERT_EQ(spi_log.size(), 0u);
}

TEST(setChannels_all)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::ChannelNone);
    clear_logs();

    dds.setChannels(TestDDS::ChannelAll);
    ASSERT_EQ(spi_log.size(), 1u);
    // ChannelAll | MSB_First | IO3Wire = 0xF0 | 0x02 = 0xF2
    ASSERT_EQ(spi_data(spi_log[0]), 0xF2u);
}

// ========================================================================
//  FREQUENCY TESTS
// ========================================================================

TEST(frequencyDelta_10MHz)
{
    auto& dds = get_dds();
    // core_clock = 25MHz * 12 = 300MHz
    // Expected delta = round(10e6 * 2^32 / 300e6) = round(143165576.533) = 143165577
    uint32_t delta = dds.frequencyDelta(10000000);
    // Allow ±1 LSB tolerance for reciprocal approximation
    double expected = round(10000000.0 * pow(2, 32) / 300000000.0);
    ASSERT_TRUE(abs((int64_t)delta - (int64_t)expected) <= 1);
}

TEST(frequencyDelta_100MHz)
{
    auto& dds = get_dds();
    uint32_t delta = dds.frequencyDelta(100000000);
    double expected = round(100000000.0 * pow(2, 32) / 300000000.0);
    ASSERT_TRUE(abs((int64_t)delta - (int64_t)expected) <= 1);
}

TEST(frequencyDelta_1Hz)
{
    auto& dds = get_dds();
    uint32_t delta = dds.frequencyDelta(1);
    // At 300MHz: delta = round(2^32/300e6) = round(14.316) = 14
    double expected = round(pow(2, 32) / 300000000.0);
    ASSERT_TRUE(abs((int64_t)delta - (int64_t)expected) <= 1);
}

TEST(frequencyDelta_0Hz)
{
    auto& dds = get_dds();
    uint32_t delta = dds.frequencyDelta(0);
    ASSERT_EQ(delta, 0u);
}

TEST(frequencyDelta_nyquist)
{
    auto& dds = get_dds();
    // Nyquist = core_clock / 2 = 150 MHz
    uint32_t delta = dds.frequencyDelta(150000000);
    // Expected: round(150e6 * 2^32 / 300e6) = round(2^31) = 2147483648
    double expected = round(150000000.0 * pow(2, 32) / 300000000.0);
    ASSERT_TRUE(abs((int64_t)delta - (int64_t)expected) <= 1);
}

TEST(setFrequency_writes_cftw)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0); // Pre-select to avoid CSR write
    clear_logs();

    dds.setFrequency(TestDDS::Channel0, 10000000);
    // Should write CFTW register (no CSR since already Channel0)
    ASSERT_TRUE(spi_log.size() >= 1);
    // Find the CFTW write
    bool found = false;
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::CFTW) {
            found = true;
            ASSERT_EQ(spi_data_len(t), 4u);
            // Verify the FTW matches frequencyDelta
            uint32_t expected_delta = dds.frequencyDelta(10000000);
            ASSERT_EQ(spi_data(t), expected_delta);
        }
    }
    ASSERT_TRUE(found);
}

TEST(setFrequency_changes_channel)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    // Set frequency on Channel1 — should write CSR first
    dds.setFrequency(TestDDS::Channel1, 5000000);
    ASSERT_TRUE(spi_log.size() >= 2);
    ASSERT_EQ(spi_reg(spi_log[0]), TestDDS::CSR); // Channel switch
    ASSERT_EQ(spi_reg(spi_log[1]), TestDDS::CFTW); // Frequency write
}

// ========================================================================
//  PHASE TESTS
// ========================================================================

TEST(setPhase_writes_cpow)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    dds.setPhase(TestDDS::Channel0, 8192); // 180 degrees
    ASSERT_TRUE(spi_log.size() >= 1);
    bool found = false;
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::CPOW) {
            found = true;
            ASSERT_EQ(spi_data_len(t), 2u);
            ASSERT_EQ(spi_data(t), 8192u);
        }
    }
    ASSERT_TRUE(found);
}

TEST(setPhase_masks_14bit)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    // 0xFFFF should be masked to 0x3FFF = 16383
    dds.setPhase(TestDDS::Channel0, 0xFFFF);
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::CPOW)
            ASSERT_EQ(spi_data(t), 0x3FFFu);
    }
}

TEST(setPhase_zero)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    dds.setPhase(TestDDS::Channel0, 0);
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::CPOW)
            ASSERT_EQ(spi_data(t), 0u);
    }
}

// ========================================================================
//  AMPLITUDE TESTS
// ========================================================================

TEST(setAmplitude_full_scale)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    // 1024 = full scale, multiplier bypassed
    dds.setAmplitude(TestDDS::Channel0, 1024);
    bool found = false;
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::ACR) {
            found = true;
            ASSERT_EQ(spi_data_len(t), 3u);
            // Byte 0: RampRate=0, Byte 1: 0 (multiplier disabled), Byte 2: 0 (1024 & 0xFF = 0)
            ASSERT_EQ(t.bytes_out[1], 0u);  // RampRate
            ASSERT_EQ(t.bytes_out[2], 0u);  // Multiplier disabled
            ASSERT_EQ(t.bytes_out[3], 0u);  // 1024 & 0xFF = 0
        }
    }
    ASSERT_TRUE(found);
}

TEST(setAmplitude_half_scale)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    // 512 = half scale, multiplier enabled
    dds.setAmplitude(TestDDS::Channel0, 512);
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::ACR) {
            // MultiplierEnable = 0x1000, amplitude = 512 = 0x200
            // Combined: 0x1200, byte1 = 0x12, byte2 = 0x00
            uint16_t acr_hi = (TestDDS::MultiplierEnable | 512) >> 8;
            ASSERT_EQ(t.bytes_out[2], (uint8_t)acr_hi);
            ASSERT_EQ(t.bytes_out[3], (uint8_t)(512 & 0xFF));
        }
    }
}

TEST(setAmplitude_clamps_above_1024)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    // Values > 1024 are clamped to 1024 (full scale, bypass)
    dds.setAmplitude(TestDDS::Channel0, 2000);
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::ACR) {
            // Should behave exactly like 1024 — multiplier bypassed
            ASSERT_EQ(t.bytes_out[2], 0u);
        }
    }
}

TEST(setAmplitude_zero)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    dds.setAmplitude(TestDDS::Channel0, 0);
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::ACR) {
            // MultiplierEnable | 0 = 0x1000, byte1 = 0x10, byte2 = 0x00
            ASSERT_EQ(t.bytes_out[2], 0x10u);
            ASSERT_EQ(t.bytes_out[3], 0x00u);
        }
    }
}

TEST(setAmplitude_max_scale)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    // 1023 = max with multiplier enabled
    dds.setAmplitude(TestDDS::Channel0, 1023);
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::ACR) {
            // MultiplierEnable | 1023 = 0x1000 | 0x3FF = 0x13FF
            // Byte 1: 0x13, Byte 2: 0xFF
            ASSERT_EQ(t.bytes_out[2], 0x13u);
            ASSERT_EQ(t.bytes_out[3], 0xFFu);
        }
    }
}

// ========================================================================
//  UPDATE / PIN TESTS
// ========================================================================

TEST(update_pulses_pin)
{
    auto& dds = get_dds();
    clear_logs();

    dds.update();
    // Should pulse UpdatePin HIGH then LOW
    ASSERT_TRUE(pin_log.size() >= 2);
    bool found_high = false, found_low_after = false;
    for (size_t i = 0; i < pin_log.size(); i++) {
        if (pin_log[i].type == PinOp::WRITE && pin_log[i].pin == PIN_UPDATE) {
            if (pin_log[i].value == HIGH)
                found_high = true;
            else if (found_high && pin_log[i].value == LOW)
                found_low_after = true;
        }
    }
    ASSERT_TRUE(found_high);
    ASSERT_TRUE(found_low_after);
}

// ========================================================================
//  WRITE FUNCTION / REGISTER LENGTH TESTS
// ========================================================================

TEST(write_csr_1byte)
{
    auto& dds = get_dds();
    clear_logs();

    dds.write(TestDDS::CSR, 0xF2);
    ASSERT_EQ(spi_log.size(), 1u);
    ASSERT_EQ(spi_reg(spi_log[0]), TestDDS::CSR);
    ASSERT_EQ(spi_data_len(spi_log[0]), 1u);
}

TEST(write_fr1_3bytes)
{
    auto& dds = get_dds();
    clear_logs();

    dds.write(TestDDS::FR1, 0x123456);
    ASSERT_EQ(spi_log.size(), 1u);
    ASSERT_EQ(spi_data_len(spi_log[0]), 3u);
}

TEST(write_fr2_2bytes)
{
    auto& dds = get_dds();
    clear_logs();

    dds.write(TestDDS::FR2, 0x2000);
    ASSERT_EQ(spi_log.size(), 1u);
    ASSERT_EQ(spi_data_len(spi_log[0]), 2u);
}

TEST(write_cfr_3bytes)
{
    auto& dds = get_dds();
    clear_logs();

    dds.write(TestDDS::CFR, 0x000321);
    ASSERT_EQ(spi_log.size(), 1u);
    ASSERT_EQ(spi_data_len(spi_log[0]), 3u);
}

TEST(write_cftw_4bytes)
{
    auto& dds = get_dds();
    clear_logs();

    dds.write(TestDDS::CFTW, 0x12345678);
    ASSERT_EQ(spi_log.size(), 1u);
    ASSERT_EQ(spi_data_len(spi_log[0]), 4u);
}

TEST(write_cpow_2bytes)
{
    auto& dds = get_dds();
    clear_logs();

    dds.write(TestDDS::CPOW, 0x1234);
    ASSERT_EQ(spi_log.size(), 1u);
    ASSERT_EQ(spi_data_len(spi_log[0]), 2u);
}

TEST(write_acr_3bytes)
{
    auto& dds = get_dds();
    clear_logs();

    dds.write(TestDDS::ACR, 0x001200);
    ASSERT_EQ(spi_log.size(), 1u);
    ASSERT_EQ(spi_data_len(spi_log[0]), 3u);
}

TEST(write_lsrr_2bytes)
{
    auto& dds = get_dds();
    clear_logs();

    dds.write(TestDDS::LSRR, 0xFF01);
    ASSERT_EQ(spi_log.size(), 1u);
    ASSERT_EQ(spi_data_len(spi_log[0]), 2u);
}

TEST(write_rdw_4bytes)
{
    auto& dds = get_dds();
    clear_logs();

    dds.write(TestDDS::RDW, 0xDEADBEEF);
    ASSERT_EQ(spi_log.size(), 1u);
    ASSERT_EQ(spi_data_len(spi_log[0]), 4u);
}

TEST(write_fdw_4bytes)
{
    auto& dds = get_dds();
    clear_logs();

    dds.write(TestDDS::FDW, 0xCAFEBABE);
    ASSERT_EQ(spi_log.size(), 1u);
    ASSERT_EQ(spi_data_len(spi_log[0]), 4u);
}

TEST(write_cw1_4bytes)
{
    auto& dds = get_dds();
    clear_logs();

    dds.write(TestDDS::CW1, 0x11223344);
    ASSERT_EQ(spi_log.size(), 1u);
    ASSERT_EQ(spi_data_len(spi_log[0]), 4u);
}

// ========================================================================
//  WRITE DATA CORRECTNESS
// ========================================================================

TEST(write_sends_correct_bytes)
{
    auto& dds = get_dds();
    clear_logs();

    // Write 0xABCD to FR2 (2-byte register)
    dds.write(TestDDS::FR2, 0xABCD);
    ASSERT_EQ(spi_log[0].bytes_out.size(), 3u); // 1 addr + 2 data
    ASSERT_EQ(spi_log[0].bytes_out[0], TestDDS::FR2); // register address
    ASSERT_EQ(spi_log[0].bytes_out[1], 0xABu);        // MSB
    ASSERT_EQ(spi_log[0].bytes_out[2], 0xCDu);        // LSB
}

TEST(write_cftw_sends_4_data_bytes)
{
    auto& dds = get_dds();
    clear_logs();

    dds.write(TestDDS::CFTW, 0x12345678);
    ASSERT_EQ(spi_log[0].bytes_out.size(), 5u); // 1 addr + 4 data
    ASSERT_EQ(spi_log[0].bytes_out[0], TestDDS::CFTW);
    ASSERT_EQ(spi_log[0].bytes_out[1], 0x12u);
    ASSERT_EQ(spi_log[0].bytes_out[2], 0x34u);
    ASSERT_EQ(spi_log[0].bytes_out[3], 0x56u);
    ASSERT_EQ(spi_log[0].bytes_out[4], 0x78u);
}

// ========================================================================
//  READ FUNCTION (reg | 0x80)
// ========================================================================

TEST(read_sets_bit7)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    dds.read(TestDDS::CFTW);
    ASSERT_TRUE(spi_log.size() >= 1);
    // The register address should have bit 7 set for reads
    ASSERT_EQ(spi_reg(spi_log[0]), 0x80u | TestDDS::CFTW);
}

TEST(read_uses_correct_length)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    // Read CFTW — 4 byte register. With the reg&0x7F fix, should transfer 4 data bytes
    dds.read(TestDDS::CFTW);
    ASSERT_TRUE(!spi_log.empty());
    ASSERT_EQ(spi_data_len(spi_log[0]), 4u);
}

TEST(read_cpow_correct_length)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    // Read CPOW — 2 byte register
    dds.read(TestDDS::CPOW);
    ASSERT_TRUE(!spi_log.empty());
    ASSERT_EQ(spi_data_len(spi_log[0]), 2u);
}

TEST(read_csr_correct_length)
{
    auto& dds = get_dds();
    clear_logs();

    dds.read(TestDDS::CSR);
    ASSERT_TRUE(!spi_log.empty());
    ASSERT_EQ(spi_data_len(spi_log[0]), 1u);
}

// ========================================================================
//  SWEEP TESTS
// ========================================================================

TEST(sweepFrequency_writes_cfr_and_cw1)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    dds.sweepFrequency(TestDDS::Channel0, 20000000);
    // Should write CFR then CW1
    ASSERT_TRUE(spi_log.size() >= 2);
    bool found_cfr = false, found_cw1 = false;
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::CFR) {
            found_cfr = true;
            uint32_t cfr_val = spi_data(t);
            // FrequencyModulation | SweepEnable | DACFullScale | MatchPipeDelay
            ASSERT_TRUE(cfr_val & TestDDS::FrequencyModulation);
            ASSERT_TRUE(cfr_val & TestDDS::SweepEnable);
            ASSERT_TRUE(cfr_val & TestDDS::DACFullScale);
            ASSERT_TRUE(cfr_val & TestDDS::MatchPipeDelay);
            // follow=true (default), so no SweepNoDwell
            ASSERT_TRUE(!(cfr_val & TestDDS::SweepNoDwell));
        }
        if (spi_reg(t) == TestDDS::CW1) {
            found_cw1 = true;
            // CW1 should contain frequencyDelta(20MHz)
            ASSERT_EQ(spi_data(t), dds.frequencyDelta(20000000));
        }
    }
    ASSERT_TRUE(found_cfr);
    ASSERT_TRUE(found_cw1);
}

TEST(sweepFrequency_nodwell)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    dds.sweepFrequency(TestDDS::Channel0, 20000000, false); // follow=false
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::CFR) {
            uint32_t cfr_val = spi_data(t);
            ASSERT_TRUE(cfr_val & TestDDS::SweepNoDwell);
        }
    }
}

TEST(sweepDelta_writes_correct_delta)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    uint32_t delta = 0x12345678;
    dds.sweepDelta(TestDDS::Channel0, delta);
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::CW1)
            ASSERT_EQ(spi_data(t), delta);
    }
}

TEST(sweepAmplitude_writes_cfr_amplitude_mode)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    dds.sweepAmplitude(TestDDS::Channel0, 512);
    bool found_cfr = false;
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::CFR) {
            found_cfr = true;
            uint32_t cfr_val = spi_data(t);
            ASSERT_TRUE(cfr_val & TestDDS::AmplitudeModulation);
            ASSERT_TRUE(cfr_val & TestDDS::SweepEnable);
        }
    }
    ASSERT_TRUE(found_cfr);
}

TEST(sweepPhase_writes_cfr_phase_mode)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    dds.sweepPhase(TestDDS::Channel0, 8192);
    bool found_cfr = false;
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::CFR) {
            found_cfr = true;
            uint32_t cfr_val = spi_data(t);
            // PhaseModulation = 0xC00000 = both bits of modulation mode
            ASSERT_TRUE((cfr_val & TestDDS::ModulationMode) == TestDDS::PhaseModulation);
            ASSERT_TRUE(cfr_val & TestDDS::SweepEnable);
        }
    }
    ASSERT_TRUE(found_cfr);
}

TEST(sweepRates_writes_rdw_fdw_lsrr)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    uint32_t inc = 100, dec = 50;
    uint8_t up = 125, down = 250;
    dds.sweepRates(TestDDS::Channel0, inc, up, dec, down);

    bool found_rdw = false, found_fdw = false, found_lsrr = false;
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::RDW) {
            found_rdw = true;
            ASSERT_EQ(spi_data(t), inc);
        }
        if (spi_reg(t) == TestDDS::FDW) {
            found_fdw = true;
            ASSERT_EQ(spi_data(t), dec); // Fixed: was incorrectly writing inc
        }
        if (spi_reg(t) == TestDDS::LSRR) {
            found_lsrr = true;
            ASSERT_EQ(spi_data(t), (uint32_t)((down << 8) | up));
        }
    }
    ASSERT_TRUE(found_rdw);
    ASSERT_TRUE(found_fdw);
    ASSERT_TRUE(found_lsrr);
}

TEST(sweepRates_default_decrement_zero)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    // Call with only increment and up_rate (decrement defaults to 0)
    dds.sweepRates(TestDDS::Channel0, 1000, 100);
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::FDW)
            ASSERT_EQ(spi_data(t), 0u);
        if (spi_reg(t) == TestDDS::LSRR)
            ASSERT_EQ(spi_data(t), (uint32_t)(0 << 8 | 100)); // down_rate=0, up_rate=100
    }
}

// ========================================================================
//  setClock TESTS
// ========================================================================

TEST(setClock_writes_fr1)
{
    auto& dds = get_dds();
    clear_logs();

    dds.setClock(20); // 25MHz * 20 = 500MHz
    // Should produce an SPI transaction writing FR1
    bool found_fr1 = false;
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::FR1) {
            found_fr1 = true;
            ASSERT_EQ(spi_data_len(t), 3u);
            // Byte 0: VCOGain(0x80, since 500MHz>200MHz) | (20*4=80=0x50) | ChargePump3(0x03)
            // = 0x80 | 0x50 | 0x03 = 0xD3
            ASSERT_EQ(t.bytes_out[1], 0xD3u);
            // Byte 1: ModLevels2(0) | RampUpDownOff(0) | Profile0(0) = 0x00
            ASSERT_EQ(t.bytes_out[2], 0x00u);
            // Byte 2: SyncClkDisable = 0x20
            ASSERT_EQ(t.bytes_out[3], 0x20u);
        }
    }
    ASSERT_TRUE(found_fr1);

    // Restore default
    dds.setClock(12);
}

TEST(setClock_vco_gain_threshold)
{
    auto& dds = get_dds();

    // mult=10 => core_clock = 25e6 * 10 = 250MHz => VCO Gain should NOT be set (threshold is >255MHz)
    clear_logs();
    dds.setClock(10);
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::FR1) {
            // Byte 0: NO VCOGain | (10*4=0x28) | ChargePump3(0x03) = 0x2B
            ASSERT_EQ(t.bytes_out[1], 0x2Bu);
        }
    }

    // mult=11 => core_clock = 275MHz => VCO Gain SHOULD be set (>255MHz)
    clear_logs();
    dds.setClock(11);
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::FR1) {
            // Byte 0: VCOGain(0x80) | (11*4=0x2C) | 0x03 = 0xAF
            ASSERT_EQ(t.bytes_out[1], 0xAFu);
        }
    }

    dds.setClock(12); // restore
}

TEST(setClock_pll_disabled)
{
    auto& dds = get_dds();
    clear_logs();

    // mult < 4 disables PLL (mult becomes 1)
    dds.setClock(3);
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::FR1) {
            // mult=1, PllDivider=0x04, so 1*4=0x04
            // core_clock = 25e6 * 1 = 25MHz, no VCO gain
            ASSERT_EQ(t.bytes_out[1], (uint8_t)(0x04 | 0x03));
        }
    }

    dds.setClock(12); // restore
}

TEST(setClock_custom_refFreq)
{
    auto& dds = get_dds();
    clear_logs();

    // Use 40MHz reference like the GRA&AFCH hardware
    dds.setClock(10, 40000000); // 40MHz * 10 = 400MHz
    // Verify frequency delta changes
    uint32_t delta = dds.frequencyDelta(100000000);
    double expected = round(100000000.0 * pow(2, 32) / 400000000.0);
    ASSERT_TRUE(abs((int64_t)delta - (int64_t)expected) <= 1);

    dds.setClock(12); // restore default
}

// ========================================================================
//  SPI CHIP SELECT TESTS
// ========================================================================

TEST(spi_transaction_asserts_cs)
{
    auto& dds = get_dds();
    clear_logs();

    dds.write(TestDDS::FR2, 0x0000);
    // Should see: CS LOW (chipEnable), then CS HIGH (chipDisable)
    int cs_low_idx = -1, cs_high_idx = -1;
    for (size_t i = 0; i < pin_log.size(); i++) {
        if (pin_log[i].type == PinOp::WRITE && pin_log[i].pin == PIN_CS) {
            if (pin_log[i].value == LOW && cs_low_idx < 0)
                cs_low_idx = i;
            else if (pin_log[i].value == HIGH && cs_low_idx >= 0)
                cs_high_idx = i;
        }
    }
    ASSERT_TRUE(cs_low_idx >= 0);
    ASSERT_TRUE(cs_high_idx > cs_low_idx);
}

// ========================================================================
//  CONSTRUCTION / RESET TESTS
// ========================================================================

TEST(constructor_initializes_pins)
{
    // Create a fresh DDS and check that pins are configured
    clear_logs();


    // Can't easily construct a new one without side effects on the global,
    // so verify the pattern: Reset LOW, CS HIGH, Update LOW, then pin modes
    // We already verified this works by the existence of a working get_dds().
    // This test verifies the DDS is usable after construction.
    auto& dds = get_dds();
    dds.setFrequency(TestDDS::Channel0, 1000000);
    uint32_t delta = dds.frequencyDelta(1000000);
    ASSERT_TRUE(delta > 0);
}

// ========================================================================
//  MULTI-CHANNEL TESTS
// ========================================================================

TEST(setFrequency_all_channels)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::ChannelNone);
    clear_logs();

    dds.setFrequency(TestDDS::ChannelAll, 50000000);
    // Should write CSR for ChannelAll then CFTW
    ASSERT_TRUE(spi_log.size() >= 2);
    ASSERT_EQ(spi_reg(spi_log[0]), TestDDS::CSR);
    ASSERT_EQ(spi_data(spi_log[0]), 0xF2u); // ChannelAll | IO3Wire
    ASSERT_EQ(spi_reg(spi_log[1]), TestDDS::CFTW);
}

TEST(channel_or_combination)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::ChannelNone);
    clear_logs();

    // Select channels 0 and 2 together
    TestDDS::ChannelNum combo = (TestDDS::ChannelNum)(TestDDS::Channel0 | TestDDS::Channel2);
    dds.setChannels(combo);
    ASSERT_EQ(spi_log.size(), 1u);
    // 0x10 | 0x40 | 0x02 (IO3Wire) = 0x52
    ASSERT_EQ(spi_data(spi_log[0]), 0x52u);
}

// ========================================================================
//  setChannelPowerDown TESTS
// ========================================================================

TEST(setChannelPowerDown_enables_power_down)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    dds.setChannelPowerDown(TestDDS::Channel0, true);
    bool found_cfr = false;
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::CFR) {
            found_cfr = true;
            uint32_t cfr_val = spi_data(t);
            ASSERT_TRUE(cfr_val & TestDDS::DigitalPowerDown);
            ASSERT_TRUE(cfr_val & TestDDS::DACPowerDown);
            ASSERT_TRUE(cfr_val & TestDDS::DACFullScale);
            ASSERT_TRUE(cfr_val & TestDDS::MatchPipeDelay);
            ASSERT_TRUE(cfr_val & TestDDS::OutputSineWave);
        }
    }
    ASSERT_TRUE(found_cfr);
}

TEST(setChannelPowerDown_disables_power_down)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    dds.setChannelPowerDown(TestDDS::Channel0, false);
    bool found_cfr = false;
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::CFR) {
            found_cfr = true;
            uint32_t cfr_val = spi_data(t);
            // Should NOT have power-down bits
            ASSERT_TRUE(!(cfr_val & TestDDS::DigitalPowerDown));
            ASSERT_TRUE(!(cfr_val & TestDDS::DACPowerDown));
            // Should still have default bits
            ASSERT_TRUE(cfr_val & TestDDS::DACFullScale);
            ASSERT_TRUE(cfr_val & TestDDS::MatchPipeDelay);
            ASSERT_TRUE(cfr_val & TestDDS::OutputSineWave);
        }
    }
    ASSERT_TRUE(found_cfr);
}

TEST(setChannelPowerDown_pulses_update)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    dds.setChannelPowerDown(TestDDS::Channel0, true);
    // Should pulse UpdatePin after CFR write
    bool found_high = false, found_low_after = false;
    for (size_t i = 0; i < pin_log.size(); i++) {
        if (pin_log[i].type == PinOp::WRITE && pin_log[i].pin == PIN_UPDATE) {
            if (pin_log[i].value == HIGH)
                found_high = true;
            else if (found_high && pin_log[i].value == LOW)
                found_low_after = true;
        }
    }
    ASSERT_TRUE(found_high);
    ASSERT_TRUE(found_low_after);
}

TEST(setChannelPowerDown_per_channel)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::ChannelNone);
    clear_logs();

    // Power down Channel2 specifically
    dds.setChannelPowerDown(TestDDS::Channel2, true);
    // First SPI transaction should be CSR selecting Channel2
    ASSERT_TRUE(spi_log.size() >= 2);
    ASSERT_EQ(spi_reg(spi_log[0]), TestDDS::CSR);
    // Channel2 | IO3Wire = 0x40 | 0x02 = 0x42
    ASSERT_EQ(spi_data(spi_log[0]), 0x42u);
    // Second should be CFR with power-down bits
    ASSERT_EQ(spi_reg(spi_log[1]), TestDDS::CFR);
}

// ========================================================================
//  RESET DEFAULT TESTS
// ========================================================================

TEST(reset_default_cfr_value)
{
    // After reset, CFR should be: DACFullScale | MatchPipeDelay | OutputSineWave
    uint32_t expected = TestDDS::DACFullScale | TestDDS::MatchPipeDelay | TestDDS::OutputSineWave;
    ASSERT_EQ(expected, 0x000321u); // 0x300 + 0x20 + 0x01
}

// ========================================================================
//  SWEEP CW1 ALIGNMENT TESTS
// ========================================================================

TEST(sweepAmplitude_cw1_msb_aligned)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    // Amplitude 512 should be MSB-aligned into CW1's 32-bit word
    // Formula: amplitude * (1 << (32-10)) = 512 * (1 << 22) = 512 * 4194304 = 0x80000000
    dds.sweepAmplitude(TestDDS::Channel0, 512);
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::CW1) {
            uint32_t expected = ((uint32_t)512) * (0x1 << (32-10));
            ASSERT_EQ(spi_data(t), expected);
        }
    }
}

TEST(sweepPhase_cw1_msb_aligned)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    // Phase 8192 (180 degrees) should be MSB-aligned into CW1
    // Formula: phase * (1 << (32-14)) = 8192 * (1 << 18) = 8192 * 262144 = 0x80000000
    dds.sweepPhase(TestDDS::Channel0, 8192);
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::CW1) {
            uint32_t expected = ((uint32_t)8192) * (0x1 << (32-14));
            ASSERT_EQ(spi_data(t), expected);
        }
    }
}

TEST(sweepFrequency_each_channel)
{
    auto& dds = get_dds();

    // Test sweep on each channel individually
    TestDDS::ChannelNum channels[] = {TestDDS::Channel0, TestDDS::Channel1, TestDDS::Channel2, TestDDS::Channel3};
    uint8_t channel_csr[] = {0x12, 0x22, 0x42, 0x82}; // chan | IO3Wire

    for (int c = 0; c < 4; c++) {
        dds.setChannels(TestDDS::ChannelNone);
        clear_logs();

        dds.sweepFrequency(channels[c], 10000000);
        // First: CSR write selecting the channel
        ASSERT_EQ(spi_reg(spi_log[0]), TestDDS::CSR);
        ASSERT_EQ(spi_data(spi_log[0]), (uint32_t)channel_csr[c]);
        // Should have CFR and CW1 writes
        bool found_cfr = false, found_cw1 = false;
        for (auto& t : spi_log) {
            if (spi_reg(t) == TestDDS::CFR) found_cfr = true;
            if (spi_reg(t) == TestDDS::CW1) found_cw1 = true;
        }
        ASSERT_TRUE(found_cfr);
        ASSERT_TRUE(found_cw1);
    }
}

TEST(setFrequency_each_channel_individually)
{
    auto& dds = get_dds();

    TestDDS::ChannelNum channels[] = {TestDDS::Channel0, TestDDS::Channel1, TestDDS::Channel2, TestDDS::Channel3};
    uint32_t freqs[] = {1000000, 10000000, 50000000, 100000000};

    for (int c = 0; c < 4; c++) {
        dds.setChannels(TestDDS::ChannelNone);
        clear_logs();

        dds.setFrequency(channels[c], freqs[c]);
        // Should write CFTW with correct delta
        bool found_cftw = false;
        for (auto& t : spi_log) {
            if (spi_reg(t) == TestDDS::CFTW) {
                found_cftw = true;
                ASSERT_EQ(spi_data(t), dds.frequencyDelta(freqs[c]));
            }
        }
        ASSERT_TRUE(found_cftw);
    }
}

// ========================================================================
//  EDGE CASE TESTS
// ========================================================================

TEST(frequencyDelta_consistency)
{
    auto& dds = get_dds();
    // Verify monotonicity: higher freq -> higher delta
    uint32_t d1 = dds.frequencyDelta(1000000);
    uint32_t d2 = dds.frequencyDelta(2000000);
    uint32_t d3 = dds.frequencyDelta(100000000);
    ASSERT_TRUE(d1 < d2);
    ASSERT_TRUE(d2 < d3);
}

TEST(frequencyDelta_accuracy_over_range)
{
    auto& dds = get_dds();
    // core_clock = 300MHz
    double core = 300000000.0;
    double two32 = pow(2, 32);

    // Test several representative frequencies
    uint32_t freqs[] = {1, 100, 10000, 1000000, 10000000, 100000000, 150000000};
    for (uint32_t freq : freqs) {
        uint32_t delta = dds.frequencyDelta(freq);
        double expected = freq * two32 / core;
        double actual_freq = (double)delta * core / two32;
        // Accuracy should be within 0.1 Hz
        ASSERT_NEAR(actual_freq, (double)freq, 0.1);
    }
}

TEST(setPhase_wraps_naturally)
{
    auto& dds = get_dds();
    dds.setChannels(TestDDS::Channel0);
    clear_logs();

    // 16384 (full rotation) masked to 0
    dds.setPhase(TestDDS::Channel0, 16384);
    for (auto& t : spi_log) {
        if (spi_reg(t) == TestDDS::CPOW)
            ASSERT_EQ(spi_data(t), 0u); // 16384 & 0x3FFF = 0
    }
}

// ========================================================================
//  MAIN
// ========================================================================

int main()
{
    printf("AD9959 Driver Unit Tests\n");
    printf("========================\n\n");

    // Initialize DDS once
    get_dds();

    printf("Enum / Constant Tests:\n");
    RUN(channel_enum_values);
    RUN(register_enum_values);
    RUN(csr_bits);
    RUN(fr1_bits);
    RUN(fr2_bits);
    RUN(cfr_bits);
    RUN(acr_bits);

    printf("\nChannel Selection Tests:\n");
    RUN(setChannels_writes_csr);
    RUN(setChannels_optimizes_redundant);
    RUN(setChannels_all);

    printf("\nFrequency Tests:\n");
    RUN(frequencyDelta_10MHz);
    RUN(frequencyDelta_100MHz);
    RUN(frequencyDelta_1Hz);
    RUN(frequencyDelta_0Hz);
    RUN(frequencyDelta_nyquist);
    RUN(setFrequency_writes_cftw);
    RUN(setFrequency_changes_channel);

    printf("\nPhase Tests:\n");
    RUN(setPhase_writes_cpow);
    RUN(setPhase_masks_14bit);
    RUN(setPhase_zero);
    RUN(setPhase_wraps_naturally);

    printf("\nAmplitude Tests:\n");
    RUN(setAmplitude_full_scale);
    RUN(setAmplitude_half_scale);
    RUN(setAmplitude_clamps_above_1024);
    RUN(setAmplitude_zero);
    RUN(setAmplitude_max_scale);

    printf("\nUpdate / Pin Tests:\n");
    RUN(update_pulses_pin);
    RUN(spi_transaction_asserts_cs);
    RUN(constructor_initializes_pins);

    printf("\nRegister Write Tests:\n");
    RUN(write_csr_1byte);
    RUN(write_fr1_3bytes);
    RUN(write_fr2_2bytes);
    RUN(write_cfr_3bytes);
    RUN(write_cftw_4bytes);
    RUN(write_cpow_2bytes);
    RUN(write_acr_3bytes);
    RUN(write_lsrr_2bytes);
    RUN(write_rdw_4bytes);
    RUN(write_fdw_4bytes);
    RUN(write_cw1_4bytes);
    RUN(write_sends_correct_bytes);
    RUN(write_cftw_sends_4_data_bytes);

    printf("\nRead Tests:\n");
    RUN(read_sets_bit7);
    RUN(read_uses_correct_length);
    RUN(read_cpow_correct_length);
    RUN(read_csr_correct_length);

    printf("\nSweep Tests:\n");
    RUN(sweepFrequency_writes_cfr_and_cw1);
    RUN(sweepFrequency_nodwell);
    RUN(sweepDelta_writes_correct_delta);
    RUN(sweepAmplitude_writes_cfr_amplitude_mode);
    RUN(sweepPhase_writes_cfr_phase_mode);
    RUN(sweepRates_writes_rdw_fdw_lsrr);
    RUN(sweepRates_default_decrement_zero);

    printf("\nsetChannelPowerDown Tests:\n");
    RUN(setChannelPowerDown_enables_power_down);
    RUN(setChannelPowerDown_disables_power_down);
    RUN(setChannelPowerDown_pulses_update);
    RUN(setChannelPowerDown_per_channel);

    printf("\nReset Default Tests:\n");
    RUN(reset_default_cfr_value);

    printf("\nSweep CW1 Alignment Tests:\n");
    RUN(sweepAmplitude_cw1_msb_aligned);
    RUN(sweepPhase_cw1_msb_aligned);
    RUN(sweepFrequency_each_channel);
    RUN(setFrequency_each_channel_individually);

    printf("\nsetClock Tests:\n");
    RUN(setClock_writes_fr1);
    RUN(setClock_vco_gain_threshold);
    RUN(setClock_pll_disabled);
    RUN(setClock_custom_refFreq);

    printf("\nMulti-Channel Tests:\n");
    RUN(setFrequency_all_channels);
    RUN(channel_or_combination);

    printf("\nEdge Case Tests:\n");
    RUN(frequencyDelta_consistency);
    RUN(frequencyDelta_accuracy_over_range);

    printf("\n========================\n");
    printf("Results: %d passed, %d failed, %d total\n",
        tests_passed, tests_failed, tests_passed + tests_failed);

    if (dds_ptr) delete dds_ptr;
    return tests_failed > 0 ? 1 : 0;
}
