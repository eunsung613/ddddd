# Pico 2 W I2C sensor test

This test reads the SCD40 and AHT10 connected to the school server laptop's Pico 2 W.

## Wiring used by this test

| Signal | Pico 2 W GPIO |
|---|---:|
| I2C1 SDA | GP14 |
| I2C1 SCL | GP15 |
| GND | GND |

Expected I2C addresses:

| Device | Address |
|---|---:|
| AHT10 | `0x38` |
| SCD40 | `0x62` |
| DS3231 EEPROM, if connected | `0x57` |
| DS3231 RTC, if connected | `0x68` |

## Run from the school server laptop

1. Pull the latest `main` branch.
2. Close Thonny so that it does not hold the Pico serial port.
3. Install mpremote once:

```powershell
py -m pip install mpremote
```

4. From the repository root, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\school_server\run_pico_i2c_test.ps1
```

The script runs from the laptop without replacing `main.py` on the Pico.
Stop the continuous test with `Ctrl+C`.

## Pass criteria

- The scan includes `0x38` and `0x62`.
- AHT10 temperature and humidity are printed every 5 seconds.
- SCD40 CO2, temperature, and humidity are printed every 5 seconds.
- No repeated `CRC error`, `not found`, or I/O error is printed.

SCD40 readings can drift during the first minute. Do not breathe directly onto the sensor while checking it.
