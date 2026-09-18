"""Read-only console display for the installed RS485 farm sensors.

Reads only:
  * SHTC3 temperature/humidity, slave 1, 9600bps, function 0x03
  * PE350 EC/pH/solution temperature, slave 21, 9600bps, function 0x04
  * KCD-HP100 CO2, slave 31, 38400bps, function 0x04

No Modbus write functions and no GPIO relay pins are used.
"""

import time

from machine import Pin, UART


UART_ID = 0
UART_TX_PIN = 0
UART_RX_PIN = 1
RS485_DE_PIN = 2
RS485_RE_PIN = 3
SHTC3_BAUD_RATE = 9600
PE350_BAUD_RATE = 9600
CO2_BAUD_RATE = 38400
TIMEOUT_MS = 500
FRAME_SILENCE_MS = 12

SHTC3_SLAVE_ID = 1
PE350_SLAVE_ID = 21
CO2_SLAVE_ID = 31


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


def request(slave_id, function_code, register, count):
    return add_crc(bytes((
        slave_id,
        function_code,
        (register >> 8) & 0xFF,
        register & 0xFF,
        (count >> 8) & 0xFF,
        count & 0xFF,
    )))


def signed_word(high, low):
    value = (high << 8) | low
    return value - 65536 if value & 0x8000 else value


class Rs485Bus:
    def __init__(self):
        self.uart = None
        self.baud_rate = None
        self.de = Pin(RS485_DE_PIN, Pin.OUT, value=0)
        self.re = Pin(RS485_RE_PIN, Pin.OUT, value=0)
        self.set_baud_rate(SHTC3_BAUD_RATE)

    def set_baud_rate(self, baud_rate):
        if self.uart is not None and self.baud_rate == baud_rate:
            return
        self.de.value(0)
        self.re.value(0)
        self.uart = UART(
            UART_ID,
            baudrate=baud_rate,
            bits=8,
            parity=None,
            stop=1,
            tx=Pin(UART_TX_PIN),
            rx=Pin(UART_RX_PIN),
            timeout=50,
            timeout_char=8,
        )
        self.baud_rate = baud_rate
        self.clear_rx()
        time.sleep_ms(20)

    def clear_rx(self):
        while self.uart.any():
            self.uart.read()

    def query(self, frame):
        self.clear_rx()
        self.re.value(1)
        self.de.value(1)
        time.sleep_us(100)
        self.uart.write(frame)
        if hasattr(self.uart, "flush"):
            self.uart.flush()
        else:
            time.sleep_us(len(frame) * 11 * 1000000 // self.baud_rate + 200)
        self.de.value(0)
        self.re.value(0)

        response = bytearray()
        started = time.ticks_ms()
        last_byte = started
        while time.ticks_diff(time.ticks_ms(), started) < TIMEOUT_MS:
            available = self.uart.any()
            if available:
                chunk = self.uart.read(available)
                if chunk:
                    response.extend(chunk)
                    last_byte = time.ticks_ms()
            if response and time.ticks_diff(time.ticks_ms(), last_byte) >= FRAME_SILENCE_MS:
                break
            time.sleep_ms(1)
        return bytes(response)


def read_registers(bus, slave_id, function_code, register, count):
    response = bus.query(request(slave_id, function_code, register, count))
    if not response:
        raise RuntimeError("timeout")
    if len(response) < 5:
        raise RuntimeError("short response")
    if (response[-2] | (response[-1] << 8)) != modbus_crc(response[:-2]):
        raise RuntimeError("CRC error")
    if response[0] != slave_id:
        raise RuntimeError("unexpected slave id {}".format(response[0]))
    if response[1] == (function_code | 0x80):
        raise RuntimeError("Modbus exception 0x{:02X}".format(response[2]))
    if response[1] != function_code:
        raise RuntimeError("unexpected function 0x{:02X}".format(response[1]))
    if response[2] != count * 2:
        raise RuntimeError("unexpected byte count {}".format(response[2]))
    return [
        (response[3 + index * 2] << 8) | response[4 + index * 2]
        for index in range(count)
    ]


def main():
    bus = Rs485Bus()
    print("RS485 sensor readout (read-only)")
    bus.set_baud_rate(SHTC3_BAUD_RATE)
    print("SHTC3: id={} / {}bps".format(SHTC3_SLAVE_ID, SHTC3_BAUD_RATE))
    try:
        humidity_raw, temperature_raw = read_registers(
            bus, SHTC3_SLAVE_ID, 0x03, 0x0000, 2,
        )
        print("온도: {:.1f} °C".format(signed_word(
            temperature_raw >> 8, temperature_raw & 0xFF,
        ) / 10.0))
        print("습도: {:.1f} %RH".format(humidity_raw / 10.0))
    except Exception as error:
        print("온습도 오류:", error)

    bus.set_baud_rate(PE350_BAUD_RATE)
    print("PE350: id={} / {}bps".format(PE350_SLAVE_ID, PE350_BAUD_RATE))
    try:
        ec_raw = read_registers(bus, PE350_SLAVE_ID, 0x04, 0x0001, 1)[0]
        ph_raw = read_registers(bus, PE350_SLAVE_ID, 0x04, 0x0002, 1)[0]
        solution_temp_raw = read_registers(
            bus, PE350_SLAVE_ID, 0x04, 0x0003, 1,
        )[0]
        print("EC: {:.3f} dS/m".format(ec_raw / 1000.0))
        print("pH: {:.2f}".format(ph_raw / 100.0))
        print("양액 온도: {:.1f} °C".format(solution_temp_raw / 10.0))
    except Exception as error:
        print("PE350 오류:", error)

    bus.set_baud_rate(CO2_BAUD_RATE)
    print("KCD-HP100 CO2: id={} / {}bps".format(CO2_SLAVE_ID, CO2_BAUD_RATE))
    try:
        co2_raw = read_registers(bus, CO2_SLAVE_ID, 0x04, 0x0004, 1)[0]
        print("CO2: {} ppm".format(co2_raw))
    except Exception as error:
        print("CO2 오류:", error)


if __name__ == "__main__":
    main()
