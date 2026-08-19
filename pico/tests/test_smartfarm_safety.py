from pathlib import Path
import sys


PICO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PICO_DIR))

import smartfarm_pins


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError("{}: {!r} != {!r}".format(label, actual, expected))


def main():
    assert_equal(smartfarm_pins.RELAY_OFF, 0, "active-HIGH OFF level")
    assert_equal(smartfarm_pins.RELAY_ON, 1, "active-HIGH ON level")
    assert_equal(
        smartfarm_pins.ACTUATOR_OUTPUTS_ARMED,
        False,
        "device-side output lock",
    )
    assert_equal(
        smartfarm_pins.RELAY_PINS,
        {
            "led": 16,
            "raw_water": 17,
            "supply": 18,
            "mixing": 19,
            "ec": 20,
            "ph": 21,
            "fan": 22,
        },
        "verified relay mapping",
    )
    print("Smart-farm relay safety tests passed")


if __name__ == "__main__":
    main()
