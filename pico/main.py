"""Pico 2 W boot entry point for offline smart-farm operation.

MicroPython runs this file after power-on and watchdog reset. Keeping this
file intentionally small ensures the tested runtime owns every relay default
and safety policy in one place.
"""

exec(open("smartfarm_runtime.py").read())
