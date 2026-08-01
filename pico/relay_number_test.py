"""Test active-HIGH relay inputs one at a time."""

import time
from machine import Pin


CHANNELS = {
    "1": ("LED", 16),
    "2": ("RAW_WATER", 17),
    "3": ("SUPPLY", 18),
    "4": ("MIXING", 19),
    "5": ("EC", 20),
    "6": ("PH", 21),
    "7": ("FAN", 22),
}

relays = {
    command: (name, Pin(gpio, Pin.OUT, value=0))
    for command, (name, gpio) in CHANNELS.items()
}


def all_off():
    for _, pin in relays.values():
        pin.value(0)


all_off()
print("Active-HIGH relay test")
print("1=LED, 2=RAW_WATER, 3=SUPPLY, 4=MIXING, 5=EC, 6=PH, 7=FAN")
print("Each relay turns ON for 2 seconds and then turns OFF automatically.")
print("0=ALL OFF, q=QUIT")

if input("Type SAFE after disconnecting 24 V actuator power: ").strip() != "SAFE":
    print("Cancelled. All relays are OFF.")
else:
    try:
        while True:
            command = input("relay> ").strip().lower()

            if command == "q":
                break

            if command == "0":
                all_off()
                print("ALL OFF")
                continue

            if command not in relays:
                print("Enter 1-7, 0, or q")
                continue

            all_off()
            name, pin = relays[command]
            pin.value(1)
            print("{} ON".format(name))
            time.sleep(2)
            pin.value(0)
            print("{} OFF".format(name))
    finally:
        all_off()
        print("Test ended. All relays are OFF.")
