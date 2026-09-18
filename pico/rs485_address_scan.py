"""Read-only RS485 / Modbus RTU address scanner for Pico 2 W.

This tool is for identifying the slave address (국번) and baud rate of the
RS485 sensors now connected to the Pico.  It only sends Modbus read requests:

* SHTC3 RS485 temperature/humidity: function 0x03, registers 0x0000..0x0001
* SenseCube KCD-HP100 CO2:          function 0x04, register  0x0004
* SenseCube PE350 EC/pH:            function 0x04, register  0x0001

It never sends function 0x06, 0x10, or any relay command.  In particular, it
cannot change a sensor address, baud rate, calibration, or a pump state.

Before running from Thonny:
    1. Save this file on the Pico as rs485_address_scan.py.
    2. Verify that the normal Pico main.py is still saved on the Pico.
    3. Run this file, copy the complete console result, then press Ctrl-D to
       soft-reboot back into the normal main.py runtime.

The normal runtime owns every relay.  This test deliberately keeps the local
continuous supply pump ON while it runs, but it does not operate any other
actuator.  Do not run it if GP18 is wired differently from smartfarm_pins.py.
"""

import time

from machine import Pin, UART

try:
    from machine import WDT
except ImportError:
    WDT = None

try:
    import config
except ImportError:
    # Allows this diagnostic to run on a newly flashed Pico that has no
    # project files yet.  These are the verified PmodRS485 pin assignments.
    class config:
        UART_ID = 0
        RS485_BAUD_RATE = 9600
        RS485_BITS = 8
        RS485_PARITY = None
        RS485_STOP = 1
        UART_TX_PIN = 0
        UART_RX_PIN = 1
        RS485_DE_PIN = 2
        RS485_RE_PIN = 3


try:
    from sensors.pe350 import add_crc, format_hex, valid_crc
except ImportError:
    def modbus_crc(data):
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc & 0xFFFF

    def add_crc(frame):
        crc = modbus_crc(frame)
        return frame + bytes((crc & 0xFF, (crc >> 8) & 0xFF))

    def valid_crc(frame):
        if len(frame) < 4:
            return False
        return (frame[-2] | (frame[-1] << 8)) == modbus_crc(frame[:-2])

    def format_hex(data):
        return " ".join("{:02X}".format(byte) for byte in data)

try:
    from smartfarm_pins import (
        ACTUATOR_OUTPUTS_ARMED,
        LOCAL_SUPPLY_CONTINUOUS_ENABLED,
        RELAY_ON,
        RELAY_PINS,
        WATCHDOG_ENABLED,
        WATCHDOG_TIMEOUT_MS,
    )
except ImportError:
    # The scanner still works in a minimal test upload, but then it will not
    # attempt to preserve the supply-pump state.
    ACTUATOR_OUTPUTS_ARMED = False
    LOCAL_SUPPLY_CONTINUOUS_ENABLED = False
    WATCHDOG_ENABLED = False
    WATCHDOG_TIMEOUT_MS = 8000


# The current equipment's known/default addresses are 1 and 31.  The default
# range is intentionally small so an incorrect cable does not leave the normal
# runtime stopped for several minutes.  Change ADDRESS_LAST to 247 only if
# this scan finds nothing and the wiring/power have already been checked.
ADDRESS_FIRST = 1
ADDRESS_LAST = 31

# Set to a tuple such as (1, 20, 31) for a quick, known-address re-scan.
# Leave as None for the complete ADDRESS_FIRST..ADDRESS_LAST sweep.
ADDRESS_CANDIDATES = None

# Known/default rates: generic SHTC3=4800, PE350=9600, KCD-HP100=38400.
BAUD_RATES = (4800, 9600, 19200, 38400, 57600)
RESPONSE_TIMEOUT_MS = 130
FRAME_SILENCE_MS = 8
BETWEEN_REQUESTS_MS = 8


def request_frame(slave_id, function_code, start_register, quantity):
    return add_crc(bytes((
        slave_id,
        function_code,
        (start_register >> 8) & 0xFF,
        start_register & 0xFF,
        (quantity >> 8) & 0xFF,
        quantity & 0xFF,
    )))


def signed_word(high, low):
    value = (high << 8) | low
    return value - 65536 if value & 0x8000 else value


class Rs485Bus:
    def __init__(self, watchdog=None):
        self.de = Pin(config.RS485_DE_PIN, Pin.OUT, value=0)
        self.re = Pin(config.RS485_RE_PIN, Pin.OUT, value=0)
        self.uart = None
        self.baud_rate = None
        self.watchdog = watchdog

    def feed_watchdog(self):
        if self.watchdog is not None:
            self.watchdog.feed()

    def set_baud_rate(self, baud_rate):
        if self.baud_rate == baud_rate and self.uart is not None:
            return
        self.de.value(0)
        self.re.value(0)
        self.uart = UART(
            config.UART_ID,
            baudrate=baud_rate,
            bits=config.RS485_BITS,
            parity=config.RS485_PARITY,
            stop=config.RS485_STOP,
            tx=Pin(config.UART_TX_PIN),
            rx=Pin(config.UART_RX_PIN),
            timeout=30,
            timeout_char=5,
        )
        self.baud_rate = baud_rate
        self.clear_rx()
        time.sleep_ms(20)

    def clear_rx(self):
        while self.uart.any():
            self.uart.read()

    def query(self, frame):
        self.feed_watchdog()
        self.clear_rx()
        self.re.value(1)  # ~RE high: receiver disabled during transmit.
        self.de.value(1)
        time.sleep_us(100)
        written = self.uart.write(frame)
        if written is not None and written != len(frame):
            self.de.value(0)
            self.re.value(0)
            raise RuntimeError("UART write failed")
        if hasattr(self.uart, "flush"):
            self.uart.flush()
        else:
            time.sleep_us(len(frame) * 11 * 1000000 // self.baud_rate + 200)
        self.de.value(0)
        self.re.value(0)

        received = bytearray()
        started = time.ticks_ms()
        last_byte = started
        while time.ticks_diff(time.ticks_ms(), started) < RESPONSE_TIMEOUT_MS:
            self.feed_watchdog()
            waiting = self.uart.any()
            if waiting:
                chunk = self.uart.read(waiting)
                if chunk:
                    received.extend(chunk)
                    last_byte = time.ticks_ms()
            if received and time.ticks_diff(time.ticks_ms(), last_byte) >= FRAME_SILENCE_MS:
                break
            time.sleep_ms(1)
        return bytes(received)


def parse_response(response, slave_id, function_code):
    """Return (kind, detail), accepting normal and Modbus exception replies."""
    if not response:
        return None
    if len(response) < 5 or not valid_crc(response):
        return ("invalid", format_hex(response))
    if response[0] != slave_id:
        return ("other_id", format_hex(response))
    if response[1] == (function_code | 0x80):
        return ("exception", "0x{:02X}".format(response[2]))
    if response[1] != function_code:
        return ("unexpected_function", format_hex(response))
    byte_count = response[2]
    if len(response) != byte_count + 5:
        return ("invalid", format_hex(response))
    return ("ok", response[3:-2])


def describe_shtc3(data):
    if len(data) != 4:
        return "data=" + format_hex(data)
    humidity = ((data[0] << 8) | data[1]) / 10.0
    temperature = signed_word(data[2], data[3]) / 10.0
    return "humidity={:.1f}% temp={:.1f}C".format(humidity, temperature)


def describe_co2(data):
    if len(data) != 2:
        return "data=" + format_hex(data)
    return "co2={} ppm".format((data[0] << 8) | data[1])


def describe_pe350(data):
    if len(data) != 2:
        return "data=" + format_hex(data)
    return "ec_raw={} ({:.3f} dS/m)".format(
        (data[0] << 8) | data[1],
        ((data[0] << 8) | data[1]) / 1000.0,
    )


PROFILES = (
    ("SHTC3_RS485_TEMP_HUM", 0x03, 0x0000, 0x0002, describe_shtc3),
    ("KCD_HP100_CO2", 0x04, 0x0004, 0x0001, describe_co2),
    ("PE350_EC_PH", 0x04, 0x0001, 0x0001, describe_pe350),
)

# A Modbus device can legally answer both 0x03 and 0x04.  Once the SHTC3
# temperature/humidity signature has identified an address+baud pair, values
# from other register probes at that *same* pair are not separate devices.
shtc3_detected_pairs = set()


def keep_supply_pump_running():
    """Preserve the Pico's existing offline circulation-pump policy only."""
    if not (LOCAL_SUPPLY_CONTINUOUS_ENABLED and ACTUATOR_OUTPUTS_ARMED):
        print("Supply pump preservation: disabled by smartfarm_pins.py")
        return None
    supply_pin = Pin(RELAY_PINS["supply"], Pin.OUT, value=RELAY_ON)
    print("Supply pump preservation: GP{} held ON during scan".format(
        RELAY_PINS["supply"],
    ))
    return supply_pin


def continue_existing_watchdog():
    """Keep the normal runtime's already-enabled Pico watchdog alive."""
    if not WATCHDOG_ENABLED or WDT is None:
        return None
    try:
        watchdog = WDT(timeout=int(WATCHDOG_TIMEOUT_MS))
        watchdog.feed()
        print("Watchdog: fed during scan ({} ms)".format(WATCHDOG_TIMEOUT_MS))
        return watchdog
    except Exception as error:
        # A scan will complete quickly, but tell the operator if this Pico
        # firmware refuses a second WDT handle instead of silently rebooting.
        print("WARN watchdog handle unavailable: {}".format(error))
        return None


def scan_profile(bus, baud_rate, profile):
    name, function_code, start_register, quantity, describe = profile
    found = []
    bus.set_baud_rate(baud_rate)
    addresses = ADDRESS_CANDIDATES
    if addresses is None:
        addresses = range(ADDRESS_FIRST, ADDRESS_LAST + 1)
    for slave_id in addresses:
        frame = request_frame(slave_id, function_code, start_register, quantity)
        try:
            response = bus.query(frame)
        except Exception as error:
            print("WARN baud={} id={}: {}".format(baud_rate, slave_id, error))
            continue
        parsed = parse_response(response, slave_id, function_code)
        if not parsed:
            continue
        kind, detail = parsed
        if kind == "ok":
            summary = describe(detail)
            pair = (slave_id, baud_rate)
            if name == "SHTC3_RS485_TEMP_HUM":
                shtc3_detected_pairs.add(pair)
            elif pair in shtc3_detected_pairs:
                print("ANSWERED same SHTC3 device       id={:<3} baud={:<5} {}".format(
                    slave_id, baud_rate, summary,
                ))
                time.sleep_ms(BETWEEN_REQUESTS_MS)
                continue
            print("FOUND {:<22} id={:<3} baud={:<5} {}".format(
                name, slave_id, baud_rate, summary,
            ))
            found.append((name, slave_id, baud_rate, summary))
        elif kind == "exception":
            # An exception proves a Modbus device answered at this address and
            # baud, but that it does not expose this profile's register.
            print("ANSWERED unknown-profile      id={:<3} baud={:<5} {} exception={}".format(
                slave_id, baud_rate, name, detail,
            ))
            found.append(("unknown-profile", slave_id, baud_rate, name))
        elif kind == "invalid":
            print("WARN invalid frame id={} baud={}: {}".format(
                slave_id, baud_rate, detail,
            ))
        time.sleep_ms(BETWEEN_REQUESTS_MS)
    return found


def main():
    shtc3_detected_pairs.clear()
    watchdog = continue_existing_watchdog()
    # Retain a reference so the pin stays configured while the scan is active.
    supply_pin = keep_supply_pump_running()
    _ = supply_pin
    print("=" * 60)
    print("RS485 Modbus read-only address scan")
    print("UART{} TX=GP{} RX=GP{} DE=GP{} ~RE=GP{}".format(
        config.UART_ID,
        config.UART_TX_PIN,
        config.UART_RX_PIN,
        config.RS485_DE_PIN,
        config.RS485_RE_PIN,
    ))
    if ADDRESS_CANDIDATES is None:
        address_label = "{}..{}".format(ADDRESS_FIRST, ADDRESS_LAST)
    else:
        address_label = str(ADDRESS_CANDIDATES)
    print("Addresses: {} / baud: {}".format(address_label, BAUD_RATES))
    print("No Modbus write commands are sent.")
    print("=" * 60)

    bus = Rs485Bus(watchdog)
    detected = []
    for baud_rate in BAUD_RATES:
        print("\n--- {} bps ---".format(baud_rate))
        for profile in PROFILES:
            detected.extend(scan_profile(bus, baud_rate, profile))

    print("\n" + "=" * 60)
    if detected:
        print("SCAN COMPLETE: {} response(s)".format(len(detected)))
        print("Record each FOUND line.  Do not change a device ID or baud yet.")
    else:
        print("SCAN COMPLETE: no response")
        print("Check 5V/24V power label, common GND, A/B polarity, and RS485 wiring.")
    print("Then press Ctrl-D in Thonny to reboot the saved main.py runtime.")
    print("=" * 60)


if __name__ == "__main__":
    main()
