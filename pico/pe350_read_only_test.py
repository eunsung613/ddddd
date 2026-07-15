"""
PE350 read-only console test for Raspberry Pi Pico 2.

Upload these files to the Pico 2 with Thonny:
    config.py
    sensors/__init__.py
    sensors/pe350.py
    pe350_read_only_test.py

Run pe350_read_only_test.py first. Do not connect pump outputs during this test.
"""

import time

import config
from sensors.pe350 import (
    PE350Modbus,
    ec_us_cm_to_ds_m,
    ph_raw_to_ph,
    temperature_raw_to_c,
)


def main():
    pe350 = PE350Modbus()

    print("PE350 read-only Modbus RTU test")
    print("UART{}: {}bps, 8N1".format(config.UART_ID, config.RS485_BAUD_RATE))
    print("Pins: TX=GP{}, RX=GP{}, DE=GP{}, ~RE=GP{}".format(
        config.UART_TX_PIN,
        config.UART_RX_PIN,
        config.RS485_DE_PIN,
        config.RS485_RE_PIN,
    ))
    print("Slave ID:", config.PE350_SLAVE_ID)
    print("Expected EC TX : 1F 04 00 01 00 01 63 B4")
    print("Expected pH TX : 1F 04 00 02 00 01 93 B4")
    print("Expected temp TX: 1F 04 00 03 00 01 C2 74")

    while True:
        try:
            ec_raw = pe350.read_ec_us_cm()
            time.sleep_ms(100)

            ph_raw = pe350.read_ph_raw()
            time.sleep_ms(100)

            temperature_raw = pe350.read_temperature_raw()

            ec_ds_m = ec_us_cm_to_ds_m(ec_raw)
            ph = ph_raw_to_ph(ph_raw)
            temperature_c = temperature_raw_to_c(temperature_raw)

            print("-" * 40)
            print("EC         : {:.3f} dS/m ({} uS/cm)".format(
                ec_ds_m,
                ec_raw,
            ))
            print("pH         : {:.2f}".format(ph))
            print("Temperature: {:.1f} C".format(
                temperature_c,
            ))
            print(
                'SENSOR_JSON:{"ec":%.3f,"ph":%.2f,"solution_temp":%.1f}'
                % (ec_ds_m, ph, temperature_c)
            )

        except RuntimeError as error:
            print("PE350 communication error:", error)
            print("SENSOR_ERROR:", error)
            print("Check power -> wiring -> GND -> A/B -> baud/address -> DE/~RE")

        time.sleep_ms(1000)


if __name__ == "__main__":
    main()
