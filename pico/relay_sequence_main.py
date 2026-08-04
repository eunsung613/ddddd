"""Autonomous no-load relay sequence test.

Save this file to the Pico as main.py.
Do not connect actuators while this test is installed.
"""

import time
from machine import Pin


ON_SECONDS = 2
OFF_GAP_SECONDS = 1

SEQUENCE = (
    ("LED", 16),
    ("RAW_WATER", 17),
    ("SUPPLY", 18),
    ("MC", 19),
    ("EC", 20),
    ("PH", 21),
    ("FAN", 22),
)

relays = [(name, Pin(gpio, Pin.OUT, value=0)) for name, gpio in SEQUENCE]


def all_off():
    for _, relay in relays:
        relay.value(0)


all_off()
time.sleep(3)

try:
    while True:
        for name, relay in relays:
            relay.value(1)
            print("{} ON".format(name))
            time.sleep(ON_SECONDS)

            relay.value(0)
            print("{} OFF".format(name))
            time.sleep(OFF_GAP_SECONDS)
finally:
    all_off()
