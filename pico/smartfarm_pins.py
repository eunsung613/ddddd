"""Verified control-box relay mapping (GPIO numbers, active HIGH).

Physical actuator output has a separate device-side arm switch.  Keep it
disabled until the relay inputs have been tested with actuator power removed.
"""

RELAY_ON = 1
RELAY_OFF = 0

# This is intentionally independent from the dashboard's CONTROL_ENABLED flag.
# Both guards must be enabled before the Pico can energize an actuator.
ACTUATOR_OUTPUTS_ARMED = False

RELAY_PINS = {
    "led": 16,
    "raw_water": 17,
    "supply": 18,
    "mixing": 19,
    "ec": 20,
    "ph": 21,
    "fan": 22,
}
