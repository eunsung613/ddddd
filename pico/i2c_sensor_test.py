from machine import I2C, Pin
import time

try:
    import ujson as json
except ImportError:
    import json


I2C_ID = 1
I2C_SDA_PIN = 14
I2C_SCL_PIN = 15

AHT10_ADDRESS = 0x38
SCD40_ADDRESS = 0x62


i2c = I2C(
    I2C_ID,
    sda=Pin(I2C_SDA_PIN),
    scl=Pin(I2C_SCL_PIN),
    freq=100000,
)


def crc8(data):
    crc = 0xFF

    for value in data:
        crc ^= value

        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x31) & 0xFF
            else:
                crc = (crc << 1) & 0xFF

    return crc


def read_scd40_word(data, index):
    value_bytes = data[index:index + 2]

    if crc8(value_bytes) != data[index + 2]:
        raise ValueError("SCD40 CRC error")

    return (value_bytes[0] << 8) | value_bytes[1]


def init_aht10():
    i2c.writeto(AHT10_ADDRESS, b"\xE1\x08\x00")
    time.sleep_ms(20)


def read_aht10():
    i2c.writeto(AHT10_ADDRESS, b"\xAC\x33\x00")
    time.sleep_ms(100)
    data = i2c.readfrom(AHT10_ADDRESS, 6)

    if data[0] & 0x80:
        raise RuntimeError("AHT10 is busy")

    raw_humidity = (
        (data[1] << 12)
        | (data[2] << 4)
        | (data[3] >> 4)
    )
    raw_temperature = (
        ((data[3] & 0x0F) << 16)
        | (data[4] << 8)
        | data[5]
    )

    humidity = raw_humidity * 100.0 / 1048576
    temperature = raw_temperature * 200.0 / 1048576 - 50.0
    return temperature, humidity


def start_scd40():
    i2c.writeto(SCD40_ADDRESS, b"\x21\xB1")
    print("SCD40 warm-up: 5 seconds")
    time.sleep_ms(5000)


def read_scd40():
    i2c.writeto(SCD40_ADDRESS, b"\xEC\x05")
    time.sleep_ms(10)
    data = i2c.readfrom(SCD40_ADDRESS, 9)

    co2 = read_scd40_word(data, 0)
    raw_temperature = read_scd40_word(data, 3)
    raw_humidity = read_scd40_word(data, 6)

    temperature = -45.0 + 175.0 * raw_temperature / 65535
    humidity = 100.0 * raw_humidity / 65535
    return co2, temperature, humidity


devices = i2c.scan()
print("I2C1 scan: SDA=GP14, SCL=GP15")
print("Detected:", ", ".join(hex(address) for address in devices))

if AHT10_ADDRESS not in devices:
    raise RuntimeError("AHT10 not found at 0x38")

if SCD40_ADDRESS not in devices:
    raise RuntimeError("SCD40 not found at 0x62")

init_aht10()
start_scd40()

while True:
    print("-" * 40)

    aht_ok = False
    scd40_ok = False

    try:
        aht_temperature, aht_humidity = read_aht10()
        print("AHT10 temperature: {:.1f} C".format(aht_temperature))
        print("AHT10 humidity   : {:.1f} %".format(aht_humidity))
        aht_ok = True
    except Exception as error:
        print("AHT10 error:", error)

    try:
        co2, scd_temperature, scd_humidity = read_scd40()
        print("SCD40 CO2        : {} ppm".format(co2))
        print("SCD40 temperature: {:.1f} C".format(scd_temperature))
        print("SCD40 humidity   : {:.1f} %".format(scd_humidity))
        scd40_ok = True
    except Exception as error:
        print("SCD40 error:", error)

    if aht_ok and scd40_ok:
        payload = {
            "type": "i2c_telemetry",
            "air_temp_c": round(aht_temperature, 2),
            "humidity_pct": round(aht_humidity, 2),
            "co2_ppm": co2,
            "scd40_temp_c": round(scd_temperature, 2),
            "scd40_humidity_pct": round(scd_humidity, 2),
        }
        print("I2C_JSON:" + json.dumps(payload))

    time.sleep(5)
