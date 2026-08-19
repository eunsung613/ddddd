# School laptop I2C dashboard test

This dashboard displays actual AHT10 temperature/humidity and SCD40 CO2 data.
It is an independent I2C test and does not run the PE350 test at the same time.

## One-time setup

1. Copy `config.school.example.json` to `config.school.json`.
2. Set `serial_port` to the Pico 2 W COM port.
3. Close Thonny.
4. Install the dependencies:

```powershell
py -m pip install -r requirements.txt
```

## Start

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\school_server\run_i2c_dashboard.ps1
```

Open `http://127.0.0.1:8765` on the school server laptop.

## Pass criteria

- Temperature and humidity change from sample values to AHT10 live values.
- CO2 changes from the sample value to the SCD40 live value.
- The dashboard shows `I2C LIVE` and the receive age stays below 15 seconds.
- EC and pH remain offline during this independent I2C test.
