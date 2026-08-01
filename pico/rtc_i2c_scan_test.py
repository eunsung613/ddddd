"""Scan the shared I2C1 bus for a DS3231 RTC."""

from machine import I2C, Pin


I2C_ID = 1
SDA_PIN = 14
SCL_PIN = 15
DS3231_ADDRESS = 0x68

i2c = I2C(
    I2C_ID,
    sda=Pin(SDA_PIN),
    scl=Pin(SCL_PIN),
    freq=100000,
)

print("I2C1 scan: SDA=GP{}, SCL=GP{}".format(SDA_PIN, SCL_PIN))
addresses = i2c.scan()

if not addresses:
    print("NO I2C DEVICE FOUND")
else:
    print("Found:", ", ".join("0x{:02X}".format(address) for address in addresses))

if DS3231_ADDRESS in addresses:
    print("PASS: DS3231 RTC found at 0x68")
else:
    print("FAIL: DS3231 RTC address 0x68 not found")
