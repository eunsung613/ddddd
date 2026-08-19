"""Verified control-box relay mapping (GPIO numbers, active LOW)."""

RELAY_ON = 0
RELAY_OFF = 1

RELAY_PINS = {
    "led": 16,
    "raw_water": 13,
    "supply": 18,
    "mixing": 19,
    "ec": 20,
    "ph": 21,
    "fan": 22,
}
