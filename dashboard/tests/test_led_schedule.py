from datetime import datetime
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dashboard.server import (
    SEOUL,
    led_seconds_until_off,
    led_should_be_on,
    photoperiod_minutes,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError("{}: {!r} != {!r}".format(label, actual, expected))


def main():
    noon = datetime(2026, 8, 19, 12, 0, tzinfo=SEOUL)
    night = datetime(2026, 8, 19, 23, 0, tzinfo=SEOUL)
    early = datetime(2026, 8, 19, 2, 0, tzinfo=SEOUL)

    assert_equal(photoperiod_minutes("06:00", "22:00"), 960, "16-hour limit")
    assert_equal(led_should_be_on("06:00", "22:00", noon), True, "day schedule on")
    assert_equal(led_should_be_on("06:00", "22:00", night), False, "day schedule off")
    assert_equal(led_should_be_on("18:00", "06:00", night), True, "overnight schedule before midnight")
    assert_equal(led_should_be_on("18:00", "06:00", early), True, "overnight schedule after midnight")
    assert_equal(led_seconds_until_off("22:00", noon), 36000, "seconds until off")

    try:
        photoperiod_minutes("05:00", "22:00")
    except ValueError:
        pass
    else:
        raise AssertionError("photoperiod longer than 16 hours was accepted")

    print("LED schedule tests passed")


if __name__ == "__main__":
    main()
