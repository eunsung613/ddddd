"""Pico 2 W control GPIO voltage test.

Disconnect IN1-IN7 and all 24 V actuator power before running this file.
Measure each Pico pin against Pico GND with a multimeter.
"""

import time
from machine import Pin

from config import (
    RELAY_S1_LED_PIN,
    RELAY_S2_RAW_WATER_PIN,
    RELAY_S3_SUPPLY_PUMP_PIN,
    RELAY_S4_MIXING_PUMP_PIN,
    RELAY_S5_EC_PUMP_PIN,
    RELAY_S6_PH_PUMP_PIN,
    RELAY_S7_FAN_PIN,
)


CHANNELS = (
    ("LED", RELAY_S1_LED_PIN, 21),
    ("RAW_WATER", RELAY_S2_RAW_WATER_PIN, 22),
    ("SUPPLY", RELAY_S3_SUPPLY_PUMP_PIN, 24),
    ("MIXING", RELAY_S4_MIXING_PUMP_PIN, 25),
    ("EC", RELAY_S5_EC_PUMP_PIN, 26),
    ("PH", RELAY_S6_PH_PUMP_PIN, 27),
    ("FAN", RELAY_S7_FAN_PIN, 29),
)

outputs = [(name, Pin(gpio, Pin.OUT, value=0), gpio, physical) for name, gpio, physical in CHANNELS]

print("GPIO voltage test")
print("IN1-IN7 and 24 V actuator power must be disconnected.")
if input("Type TEST to continue: ").strip() != "TEST":
    print("Cancelled. All test pins remain LOW.")
else:
    try:
        for name, pin, gpio, physical in outputs:
            print("{}: GP{} / physical pin {} -> HIGH for 5 seconds".format(name, gpio, physical))
            pin.value(1)
            time.sleep(5)
            pin.value(0)
            print("{} -> LOW".format(name))
            time.sleep(1)

        print("PASS: test sequence completed.")
    finally:
        for _, pin, _, _ in outputs:
            pin.value(0)
        print("All test pins are LOW.")
