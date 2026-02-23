// Instrumented SPI mock for AD9959 unit tests
#ifndef _MOCK_SPI_H_
#define _MOCK_SPI_H_

#include <stdint.h>
#include <vector>

typedef enum { LSBFIRST = 0, MSBFIRST = 1 } SPIEndian;
typedef enum { SPI_MODE0 = 0, SPI_MODE3 = 3 } SPIMode;

struct SPISettings {
    int rate;
    SPIEndian endian;
    SPIMode mode;
    SPISettings(int r, int e, int m) : rate(r), endian((SPIEndian)e), mode((SPIMode)m) {}
};

struct SPITransaction {
    std::vector<uint8_t> bytes_out;
};

extern std::vector<SPITransaction> spi_log;
extern bool spi_in_transaction;

struct SPIMock {
    void begin() {}

    uint8_t transfer(uint8_t out)
    {
        if (spi_in_transaction && !spi_log.empty())
            spi_log.back().bytes_out.push_back(out);
        return 0;
    }

    void beginTransaction(SPISettings)
    {
        spi_in_transaction = true;
        spi_log.push_back({});
    }

    void endTransaction()
    {
        spi_in_transaction = false;
    }
} extern SPI;

#endif
