"""Verified control-box relay mapping (GPIO numbers, active HIGH).

Physical actuator output has a separate device-side arm switch.  Keep it
disabled until the relay inputs have been tested with actuator power removed.
"""

RELAY_ON = 1
RELAY_OFF = 0

# This is intentionally independent from the dashboard's CONTROL_ENABLED flag.
# Hardware commissioning for all seven outputs was verified on 2026-08-21.
ACTUATOR_OUTPUTS_ARMED = True

# LED photoperiod commands have a separate, narrow device-side permission.
# This does not arm pumps, valves, mixers, or the fan.
LED_SCHEDULE_OUTPUT_ARMED = True

# Autonomous device policy.  This lets the supply pump survive a laptop,
# Wi-Fi, MQTT, or dashboard outage.  Chemical pumps never inherit this policy.
LOCAL_SUPPLY_CONTINUOUS_ENABLED = True

# RP2040's watchdog is local to the Pico and has no network dependency.  The
# runtime feeds it each event-loop pass; a hang reboots to the safe defaults.
WATCHDOG_ENABLED = True
WATCHDOG_TIMEOUT_MS = 8000

RELAY_PINS = {
    "led": 16,
    "raw_water": 17,
    "supply": 18,
    "mixing": 19,
    "ec": 20,
    "ph": 21,
    "fan": 22,
}
