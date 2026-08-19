"""Pico 2 W integrated telemetry and relay runtime.

The school laptop starts this file over USB serial. Relays are active HIGH and
are forced OFF at boot. PE350 access remains read-only (Modbus function 0x04).
"""

import sys
import time

from machine import I2C, Pin

try:
    import ujson as json
except ImportError:
    import json

try:
    import uselect as select
except ImportError:
    import select

import config
from smartfarm_pins import (
    ACTUATOR_OUTPUTS_ARMED,
    RELAY_OFF,
    RELAY_ON,
    RELAY_PINS,
)
from sensors.pe350 import (
    PE350Modbus,
    ec_us_cm_to_ds_m,
    ph_raw_to_ph,
    temperature_raw_to_c,
)


AHT10_ADDRESS = 0x38
SCD40_ADDRESS = 0x62
TELEMETRY_INTERVAL_MS = 5000

# Conservative device-side limits. The server applies the same or stricter limits.
MAX_ON_SECONDS = {
    "led": 57600,
    "raw_water": 60,
    "supply": 120,
    "mixing": 300,
    "ec": 5,
    "ph": 5,
    "fan": 1800,
}


def emit(prefix, payload):
    print(prefix + json.dumps(payload))


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


def read_word(data, index):
    value_bytes = data[index:index + 2]
    if crc8(value_bytes) != data[index + 2]:
        raise ValueError("SCD40 CRC error")
    return (value_bytes[0] << 8) | value_bytes[1]


class EnvironmentSensors:
    def __init__(self):
        self.i2c = I2C(
            config.I2C_ID,
            sda=Pin(config.I2C_SDA_PIN),
            scl=Pin(config.I2C_SCL_PIN),
            freq=100000,
        )
        devices = self.i2c.scan()
        self.aht10_available = AHT10_ADDRESS in devices
        self.scd40_available = SCD40_ADDRESS in devices
        self.startup_errors = {}

        if self.aht10_available:
            try:
                self.i2c.writeto(AHT10_ADDRESS, b"\xE1\x08\x00")
                time.sleep_ms(20)
            except Exception as error:
                self.aht10_available = False
                self.startup_errors["aht10"] = str(error)
        else:
            self.startup_errors["aht10"] = "not found at 0x38"

        if self.scd40_available:
            try:
                self.i2c.writeto(SCD40_ADDRESS, b"\x21\xB1")
                time.sleep_ms(5000)
            except Exception as error:
                self.scd40_available = False
                self.startup_errors["scd40"] = str(error)
        else:
            self.startup_errors["scd40"] = "not found at 0x62"

    def read(self):
        payload = {}
        errors = dict(self.startup_errors)

        if self.aht10_available:
            try:
                self.i2c.writeto(AHT10_ADDRESS, b"\xAC\x33\x00")
                time.sleep_ms(100)
                aht = self.i2c.readfrom(AHT10_ADDRESS, 6)
                if aht[0] & 0x80:
                    raise RuntimeError("AHT10 is busy")
                raw_humidity = (aht[1] << 12) | (aht[2] << 4) | (aht[3] >> 4)
                raw_temperature = ((aht[3] & 0x0F) << 16) | (aht[4] << 8) | aht[5]
                payload["air_temp"] = round(
                    raw_temperature * 200.0 / 1048576 - 50.0,
                    2,
                )
                payload["humidity"] = round(
                    raw_humidity * 100.0 / 1048576,
                    2,
                )
                errors.pop("aht10", None)
            except Exception as error:
                errors["aht10"] = str(error)

        if self.scd40_available:
            try:
                self.i2c.writeto(SCD40_ADDRESS, b"\xEC\x05")
                time.sleep_ms(10)
                scd = self.i2c.readfrom(SCD40_ADDRESS, 9)
                payload["co2"] = int(read_word(scd, 0))
                payload["scd40_temp"] = round(
                    -45.0 + 175.0 * read_word(scd, 3) / 65535,
                    2,
                )
                payload["scd40_humidity"] = round(
                    100.0 * read_word(scd, 6) / 65535,
                    2,
                )
                errors.pop("scd40", None)
            except Exception as error:
                errors["scd40"] = str(error)

        return payload, errors


relays = {}
deadlines = {}
for name, pin_number in RELAY_PINS.items():
    relays[name] = Pin(pin_number, Pin.OUT, value=RELAY_OFF)


def all_off():
    for relay in relays.values():
        relay.value(RELAY_OFF)
    deadlines.clear()


def set_relay(name, turn_on, duration_seconds=0):
    if name not in relays:
        raise ValueError("Unknown actuator: " + str(name))
    if turn_on:
        if not ACTUATOR_OUTPUTS_ARMED:
            raise RuntimeError("Pico actuator outputs are not armed")
        duration_seconds = int(duration_seconds)
        if duration_seconds <= 0 or duration_seconds > MAX_ON_SECONDS[name]:
            raise ValueError("Invalid duration for " + name)
        relays[name].value(RELAY_ON)
        deadlines[name] = time.ticks_add(time.ticks_ms(), duration_seconds * 1000)
    else:
        relays[name].value(RELAY_OFF)
        deadlines.pop(name, None)


def expire_relays():
    now = time.ticks_ms()
    for name in list(deadlines):
        if time.ticks_diff(now, deadlines[name]) >= 0:
            set_relay(name, False)
            emit("ACK_JSON:", {
                "cmd_id": None,
                "actuator": name,
                "state": "off",
                "result": "timeout_off",
            })


def handle_command(line):
    if not line.startswith("CMD_JSON:"):
        return
    command = json.loads(line.split(":", 1)[1])
    cmd_id = command.get("cmd_id")
    try:
        action = command.get("action")
        if action == "all_off":
            all_off()
            emit("ACK_JSON:", {"cmd_id": cmd_id, "result": "ok", "state": "all_off"})
            return
        if action != "set":
            raise ValueError("Unsupported action")
        name = command.get("actuator")
        state = command.get("state")
        if state not in ("on", "off"):
            raise ValueError("State must be on or off")
        set_relay(name, state == "on", command.get("duration_seconds", 0))
        emit("ACK_JSON:", {
            "cmd_id": cmd_id,
            "actuator": name,
            "state": state,
            "result": "ok",
        })
    except Exception as error:
        emit("ACK_JSON:", {"cmd_id": cmd_id, "result": "error", "error": str(error)})


def read_telemetry(environment, pe350):
    environment_payload, sensor_errors = environment.read()
    payload = {
        "type": "telemetry",
        "actuators": {
            name: "on" if relay.value() == RELAY_ON else "off"
            for name, relay in relays.items()
        },
    }
    payload.update(environment_payload)
    try:
        ec_raw = pe350.read_ec_us_cm()
        time.sleep_ms(100)
        ph_raw = pe350.read_ph_raw()
        time.sleep_ms(100)
        solution_temp_raw = pe350.read_temperature_raw()
        payload.update({
            "ec": round(ec_us_cm_to_ds_m(ec_raw), 3),
            "ph": round(ph_raw_to_ph(ph_raw), 2),
            "solution_temp": round(temperature_raw_to_c(solution_temp_raw), 1),
        })
        sensor_errors.pop("pe350", None)
    except Exception as error:
        sensor_errors["pe350"] = str(error)
    payload["sensor_errors"] = sensor_errors
    return payload


def main():
    all_off()
    emit("RUNTIME_JSON:", {
        "status": "starting",
        "relays": "all_off",
        "actuator_outputs_armed": ACTUATOR_OUTPUTS_ARMED,
    })
    environment = EnvironmentSensors()
    pe350 = PE350Modbus()
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)
    last_telemetry = time.ticks_add(time.ticks_ms(), -TELEMETRY_INTERVAL_MS)

    while True:
        expire_relays()
        if poll.poll(0):
            handle_command(sys.stdin.readline().strip())

        now = time.ticks_ms()
        if time.ticks_diff(now, last_telemetry) >= TELEMETRY_INTERVAL_MS:
            last_telemetry = now
            try:
                emit("TELEMETRY_JSON:", read_telemetry(environment, pe350))
            except Exception as error:
                emit("TELEMETRY_ERROR:", {"error": str(error)})
        time.sleep_ms(20)


try:
    main()
finally:
    all_off()
