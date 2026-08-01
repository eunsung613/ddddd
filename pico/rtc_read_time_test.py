"""Read date and time from a DS3231 RTC without changing it."""

import time
from machine import I2C, Pin


SDA_PIN = 14
SCL_PIN = 15
DS3231_ADDRESS = 0x68


def bcd_to_int(value):
    return ((value >> 4) * 10) + (value & 0x0F)


def decode_hour(value):
    if value & 0x40:
        hour = bcd_to_int(value & 0x1F)
        is_pm = bool(value & 0x20)
        if hour == 12:
            return 12 if is_pm else 0
        return hour + 12 if is_pm else hour
    return bcd_to_int(value & 0x3F)


i2c = I2C(1, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=100000)

if DS3231_ADDRESS not in i2c.scan():
    raise RuntimeError("DS3231 RTC address 0x68 not found")

status = i2c.readfrom_mem(DS3231_ADDRESS, 0x0F, 1)[0]
if status & 0x80:
    print("WARNING: RTC time may be invalid because OSF is set")

print("Reading DS3231 time 10 times")
for _ in range(10):
    data = i2c.readfrom_mem(DS3231_ADDRESS, 0x00, 7)

    second = bcd_to_int(data[0] & 0x7F)
    minute = bcd_to_int(data[1] & 0x7F)
    hour = decode_hour(data[2])
    weekday = data[3] & 0x07
    day = bcd_to_int(data[4] & 0x3F)
    month = bcd_to_int(data[5] & 0x1F)
    year = 2000 + bcd_to_int(data[6])
    if data[5] & 0x80:
        year += 100

    print(
        "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d} weekday={}".format(
            year, month, day, hour, minute, second, weekday
        )
    )
    time.sleep(1)

print("PASS: DS3231 time registers were read")
