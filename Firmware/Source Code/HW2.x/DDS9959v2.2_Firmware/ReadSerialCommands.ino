/*
By default, the maximum length of one message is 64 bytes, you can change it in HardwareSerial.h, string #46: #define SERIAL_TX_BUFFER_SIZE 64
*/

int C=-1; //Номер канала(выхода) для управления, по умолчанию не задан (-1), допустимые значения: 0 - 3

#define SERIAL_PACKAGE_MAX_LENGTH 110
char Buff[SERIAL_PACKAGE_MAX_LENGTH + 1];

const char HELP_STRING [] PROGMEM = "C — Set the current output Channel: (0 — 3)\n"
          "F — Sets Frequency in Hz (100000 — 225000000)\n"
          "A — Sets the power (Amplitude) level of the selected channel in dBm (-60 — -3)\n"
          "P — Sets the Phase of the selected channel in degrees (0 — 360.0, e.g. P90.5)\n"
          "Q — Query current channel state (frequency, amplitude, phase)\n"
          "M — Gets Model\n"
          "E - Enable Outputs (ALL), E0-E3 enables single channel\n"
          "D - Disable Outputs (ALL), D0-D3 disables single channel\n"
          "V — Gets Firmware Version\n"
          "h — This Help\n"
          "; — Commands Separator"
          "\n"
          "Example:\n"
          "C0;F100000;A-10\n"
          "Sets the Frequency to 100 kHz, and Output Power (Amplitude) to -10 dBm on Channel 0 (RF OUT0).\n"
          "Any number of commands in any order is allowed, but the very first command must be \"C\".\n"
          "Note: by default, the maximum length of one message is 64 bytes";


bool inRange(int32_t val, int32_t minimum, int32_t maximum)
{
  return ((minimum <= val) && (val <= maximum));
}

void ReadSerialCommands()
{
  if (!Serial.available()) return;
  int RcvCounter=0;
  RcvCounter = Serial.readBytesUntil('\n', Buff, 110);
  if (RcvCounter == 0) return;
  Buff[RcvCounter]='\0';
  
  int32_t value=0;
  char command;

    GParser data(Buff, ';');
    int commandsCounter = data.split();

    for (int i=0; i < commandsCounter; i++)
    {
      int nParsed = sscanf(data[i], "%c%ld", &command, &value);
      switch (command)
      {

        case 'C': //Current Channel (0 - 3)
          if (inRange(value, 0, 3))
          {
            Serial.print(F("The Channel number is set to: "));
            Serial.println(value);
            C = value;
          } else Serial.println(F("The Channel number is OUT OF RANGE (0 — 3)"));
        break;

        case 'F': //RF Frequency
          if (C==-1) {Serial.println(F("The output Channel is not selected! Use \"C\" command to select the Channel.")); return;}
          if (inRange(value, LOW_FREQ_LIMIT, ui32HIGH_FREQ_LIMIT))
          {
            Serial.print(F("The Frequency of Channel "));
            Serial.print(C);
            Serial.print(F(" is set to: "));
            Serial.println(value);
            uint16_t H, K, M;
            H = value % 1000;
            K = (value / 1000) % 1000;
            M = value / 1000000;
            switch (C)
            {
              case 0:
                F0_Hz.value = H;
                F0_kHz.value = K;
                F0_MHz.value = M;
                F0OutputFreq = value;
              break;
              case 1:
                F1_Hz.value = H;
                F1_kHz.value = K;
                F1_MHz.value = M;
                F1OutputFreq = value;
              break;
              case 2:
                F2_Hz.value = H;
                F2_kHz.value = K;
                F2_MHz.value = M;
                F2OutputFreq = value;
              break;
              case 3:
                F3_Hz.value = H;
                F3_kHz.value = K;
                F3_MHz.value = M;
                F3OutputFreq = value;
              break;
            }
          } else 
          {
            Serial.print(F("Frequency is OUT OF RANGE ("));
            Serial.println(String(LOW_FREQ_LIMIT) + " - " + String(ui32HIGH_FREQ_LIMIT) + ")");
          }
        break;

        case 'A': //Power(Amplitude), dBm -60 - -7
          if (C==-1) {Serial.println(F("The output Channel is not selected! Use \"C\" command to select the Channel.")); return;}
          if (inRange(value, -60, -3))
          {
            Serial.print(F("The Power (Amplitude) of Channel "));
            Serial.print(C);
            Serial.print(F(" is set to: "));
            Serial.println(value);
            switch (C)
            {
              case 0:
                F0_Amplitude.value = -1 * value;
              break;
              case 1:
                F1_Amplitude.value = -1 * value;
              break;
              case 2:
                F2_Amplitude.value = -1 * value;
              break;
              case 3:
                F3_Amplitude.value = -1 * value;
              break;
            }
          } else Serial.println(F("Power is OUT OF RANGE (-60 — -3)"));
        break;

        case 'P': //Phase, 0.0 - 360.0
          if (C==-1) {Serial.println(F("The output Channel is not selected! Use \"C\" command to select the Channel.")); return;}
          if (inRange(value, 0, 360))
          {
            // Parse fractional part (e.g., P90.5 -> fraction=5)
            uint8_t fraction = 0;
            {
              const char *dot = strchr(data[i], '.');
              if (dot && dot[1] >= '0' && dot[1] <= '9') fraction = dot[1] - '0';
            }
            // Clamp: 360.1+ is invalid
            if (value == 360 && fraction > 0) fraction = 0;
            Serial.print(F("The Phase of Channel "));
            Serial.print(C);
            Serial.print(F(" is set to: "));
            Serial.print(value);
            Serial.print(F("."));
            Serial.println(fraction);
            switch (C)
            {
              case 0:
                F0_Phase.value = value;
                F0_PhaseFraction.value = fraction;
              break;
              case 1:
                F1_Phase.value = value;
                F1_PhaseFraction.value = fraction;
              break;
              case 2:
                F2_Phase.value = value;
                F2_PhaseFraction.value = fraction;
              break;
              case 3:
                F3_Phase.value = value;
                F3_PhaseFraction.value = fraction;
              break;
            }
          } else Serial.println(F("Phase is OUT OF RANGE (0 — 360)"));
        break;

        case 'D': //Disable outputs
          if (nParsed == 2 && inRange(value, 0, 3))
          {
            static const MyAD9959::ChannelNum chMap[] = {MyAD9959::Channel0, MyAD9959::Channel1, MyAD9959::Channel2, MyAD9959::Channel3};
            dds.setChannelPowerDown(chMap[value], true);
            Serial.print(F("Channel "));
            Serial.print(value);
            Serial.println(F(" Disabled"));
          } else {
            Serial.println(F("Outputs Disabled"));
            digitalWrite(POWER_DOWN_CONTROL_PIN, HIGH);
            isPWR_DWN = true;
          }
        break;

        case 'E': //Enable outputs
          if (nParsed == 2 && inRange(value, 0, 3))
          {
            static const MyAD9959::ChannelNum chMap[] = {MyAD9959::Channel0, MyAD9959::Channel1, MyAD9959::Channel2, MyAD9959::Channel3};
            dds.setChannelPowerDown(chMap[value], false);
            Serial.print(F("Channel "));
            Serial.print(value);
            Serial.println(F(" Enabled"));
          } else {
            Serial.println(F("Outputs Enabled"));
            digitalWrite(POWER_DOWN_CONTROL_PIN, LOW);
            isPWR_DWN = false;
          }
        break;

        case 'V': //Firmware Version request
          Serial.println(FIRMWAREVERSION);
          //Serial.println(value);
        break;

        case 'M': //Model request
          Serial.println(F("DDS9959 v2.x"));
          //Serial.println(value);
        break;

        case 'h': //Help
          Serial.println((const __FlashStringHelper *) HELP_STRING);
        break;

        case 'Q': //Query channel state
          if (C==-1) {Serial.println(F("The output Channel is not selected! Use \"C\" command to select the Channel.")); return;}
          {
            uint32_t freq=0;
            int16_t amp=0;
            int16_t phase=0;
            uint8_t phaseFrac=0;
            switch (C)
            {
              case 0: freq=F0OutputFreq; amp=F0_Amplitude.value; phase=F0_Phase.value; phaseFrac=F0_PhaseFraction.value; break;
              case 1: freq=F1OutputFreq; amp=F1_Amplitude.value; phase=F1_Phase.value; phaseFrac=F1_PhaseFraction.value; break;
              case 2: freq=F2OutputFreq; amp=F2_Amplitude.value; phase=F2_Phase.value; phaseFrac=F2_PhaseFraction.value; break;
              case 3: freq=F3OutputFreq; amp=F3_Amplitude.value; phase=F3_Phase.value; phaseFrac=F3_PhaseFraction.value; break;
            }
            Serial.print(F("CH"));
            Serial.print(C);
            Serial.print(F(" F="));
            Serial.print(freq);
            Serial.print(F(" A=-"));
            Serial.print(amp);
            Serial.print(F(" P="));
            Serial.print(phase);
            Serial.print(F("."));
            Serial.println(phaseFrac);
          }
        break;

        default:
        Serial.print(F("Unknown command:"));
        Serial.println(command);
        Serial.println((const __FlashStringHelper *) HELP_STRING);
      } //switch
    } //for

    DisplayMenu(menuType);
    ApplyChangesToDDS();
    mainSettingsDirty=true;
    mainSettingsLastChange=millis();
}