from pathlib import Path
import sys


PICO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PICO_DIR))

import config
from sensors.pe350 import (
    add_crc,
    ec_us_cm_to_ds_m,
    make_read_input_register_request,
    parse_single_register_response,
    ph_raw_to_ph,
    temperature_raw_to_c,
    valid_crc,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError("{}: {!r} != {!r}".format(label, actual, expected))


def response_for(raw):
    payload = bytes((
        config.PE350_SLAVE_ID,
        0x04,
        0x02,
        (raw >> 8) & 0xFF,
        raw & 0xFF,
    ))
    return add_crc(payload)


def main():
    assert_equal(
        make_read_input_register_request(config.PE350_EC_REGISTER),
        bytes.fromhex("1F 04 00 01 00 01 63 B4"),
        "EC request",
    )
    assert_equal(
        make_read_input_register_request(config.PE350_PH_REGISTER),
        bytes.fromhex("1F 04 00 02 00 01 93 B4"),
        "pH request",
    )
    assert_equal(
        make_read_input_register_request(config.PE350_TEMPERATURE_REGISTER),
        bytes.fromhex("1F 04 00 03 00 01 C2 74"),
        "temperature request",
    )

    ec_response = response_for(800)
    ph_response = response_for(618)
    temperature_response = response_for(224)

    assert_equal(valid_crc(ec_response), True, "EC CRC")
    assert_equal(parse_single_register_response(ec_response), 800, "EC parse")
    assert_equal(parse_single_register_response(ph_response), 618, "pH parse")
    assert_equal(
        parse_single_register_response(temperature_response),
        224,
        "temperature parse",
    )

    assert_equal(ec_us_cm_to_ds_m(800), 0.8, "EC conversion")
    assert_equal(ph_raw_to_ph(618), 6.18, "pH conversion")
    assert_equal(temperature_raw_to_c(224), 22.4, "temperature conversion")

    print("PE350 protocol tests passed")


if __name__ == "__main__":
    main()

