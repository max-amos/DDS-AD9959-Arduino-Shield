// Instrumented Arduino mock for AD9959 unit tests
#ifndef _MOCK_ARDUINO_H_
#define _MOCK_ARDUINO_H_

#define ARDUINO 10600

#include <stdio.h>
#include <stdint.h>
#include <vector>

typedef enum { LOW = 0, HIGH = 1 } PinValue;
typedef enum { INPUT = 0, OUTPUT = 1 } PinMode;

struct PinOp {
    enum Type { WRITE, MODE } type;
    int pin;
    int value;
};

extern std::vector<PinOp> pin_log;

inline void digitalWrite(int pin, bool value)
{
    pin_log.push_back({PinOp::WRITE, pin, value ? 1 : 0});
}

inline void pinMode(int pin, PinMode mode)
{
    pin_log.push_back({PinOp::MODE, pin, mode});
}

struct SerialDummy {
    void nl() { printf("\n"); }
    void print(const char* s) { printf("%s", s); }
    void println(const char* s) { print(s); nl(); }
    void print(uint32_t i) { printf("%u", i); }
    void println(uint32_t i) { print(i); nl(); }
} extern Serial;

#endif
