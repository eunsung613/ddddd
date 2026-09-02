"""Pico 2 W integrated telemetry and relay runtime.

The school laptop starts this file over USB serial. Relays are active HIGH and
are forced OFF at boot. PE350 access remains read-only (Modbus function 0x04).
"""

import sys
import time

from machine import Pin

try:
    from machine import WDT
except ImportError:
    WDT = None

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
    LED_SCHEDULE_OUTPUT_ARMED,
    LOCAL_SUPPLY_CONTINUOUS_ENABLED,
    RELAY_OFF,
    RELAY_ON,
    RELAY_PINS,
    WATCHDOG_ENABLED,
    WATCHDOG_TIMEOUT_MS,
)
from sensors.pe350 import (
    PE350Modbus,
    ec_us_cm_to_ds_m,
    ph_raw_to_ph,
    temperature_raw_to_c,
)
from sensors.rs485_environment import EnvironmentSensors


TELEMETRY_INTERVAL_MS = 5000

# Conservative device-side limits. The server applies the same or stricter limits.
MAX_ON_SECONDS = {
    "led": 57600,
    "raw_water": 60,
    "supply": 86400,
    "mixing": 300,
    "ec": 15,
    "ph": 5,
    "fan": 1800,
}


def emit(prefix, payload):
    print(prefix + json.dumps(payload))


relays = {}
deadlines = {}
local_supply_continuous = bool(LOCAL_SUPPLY_CONTINUOUS_ENABLED)
for name, pin_number in RELAY_PINS.items():
    relays[name] = Pin(pin_number, Pin.OUT, value=RELAY_OFF)


def all_off(disable_local_supply=False):
    """Turn every relay off; an explicit all-off is also a local override."""
    global local_supply_continuous
    for relay in relays.values():
        relay.value(RELAY_OFF)
    deadlines.clear()
    if disable_local_supply:
        local_supply_continuous = False


def apply_local_supply_policy():
    """Keep only the circulation pump alive when the host/network disappears."""
    if not local_supply_continuous or not ACTUATOR_OUTPUTS_ARMED:
        return
    relays["supply"].value(RELAY_ON)
    deadlines.pop("supply", None)


def make_watchdog():
    if not WATCHDOG_ENABLED or WDT is None:
        return None
    try:
        return WDT(timeout=int(WATCHDOG_TIMEOUT_MS))
    except Exception as error:
        emit("RUNTIME_JSON:", {"status": "watchdog_unavailable", "error": str(error)})
        return None


def set_relay(name, turn_on, duration_seconds=0):
    global local_supply_continuous
    if name not in relays:
        raise ValueError("Unknown actuator: " + str(name))
    if turn_on:
        output_armed = (
            LED_SCHEDULE_OUTPUT_ARMED
            if name == "led"
            else ACTUATOR_OUTPUTS_ARMED
        )
        if not output_armed:
            raise RuntimeError("Pico actuator outputs are not armed")
        duration_seconds = int(duration_seconds)
        if duration_seconds <= 0 or duration_seconds > MAX_ON_SECONDS[name]:
            raise ValueError("Invalid duration for " + name)
        relays[name].value(RELAY_ON)
        if name == "supply" and LOCAL_SUPPLY_CONTINUOUS_ENABLED:
            # A server outage must not let a 24-hour host-issued timeout stop
            # the circulation pump.  An explicit all_off remains available.
            local_supply_continuous = True
            deadlines.pop(name, None)
        else:
            deadlines[name] = time.ticks_add(time.ticks_ms(), duration_seconds * 1000)
    else:
        relays[name].value(RELAY_OFF)
        deadlines.pop(name, None)
        if name == "supply":
            local_supply_continuous = False


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
            all_off(disable_local_supply=True)
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
    watchdog = make_watchdog()
    apply_local_supply_policy()
    emit("RUNTIME_JSON:", {
        "status": "starting",
        "relays": "supply_on_local" if local_supply_continuous else "all_off",
        "actuator_outputs_armed": ACTUATOR_OUTPUTS_ARMED,
        "led_schedule_output_armed": LED_SCHEDULE_OUTPUT_ARMED,
        "local_supply_continuous": local_supply_continuous,
        "watchdog_enabled": watchdog is not None,
        "watchdog_timeout_ms": WATCHDOG_TIMEOUT_MS if watchdog is not None else None,
    })
    # One owner for UART0/DE/RE avoids intermittent RS485 lockups caused by
    # separate driver instances reinitialising the same hardware peripheral.
    environment = EnvironmentSensors()
    pe350 = PE350Modbus(environment.uart, environment.de, environment.re)
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)
    last_telemetry = time.ticks_add(time.ticks_ms(), -TELEMETRY_INTERVAL_MS)

    while True:
        if watchdog:
            watchdog.feed()
        expire_relays()
        apply_local_supply_policy()
        if poll.poll(0):
            handle_command(sys.stdin.readline().strip())

        now = time.ticks_ms()
        if time.ticks_diff(now, last_telemetry) >= TELEMETRY_INTERVAL_MS:
            last_telemetry = now
            try:
                emit("TELEMETRY_JSON:", read_telemetry(environment, pe350))
            except Exception as error:
                emit("TELEMETRY_ERROR:", {"error": str(error)})
        if watchdog:
            watchdog.feed()
        time.sleep_ms(20)


try:
    main()
finally:
    all_off()
