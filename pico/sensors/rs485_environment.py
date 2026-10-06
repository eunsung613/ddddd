"""Read-only RS485 environment sensor drivers for the Pico smart-farm runtime."""

import time

from machine import Pin, UART

import config
from sensors.pe350 import add_crc, valid_crc


READ_HOLDING_REGISTERS = 0x03
READ_INPUT_REGISTERS = 0x04


def signed_word(value):
    return value - 65536 if value & 0x8000 else value


class EnvironmentSensors:
    """Read SHTC3 and KCD-HP100 without changing any Modbus setting."""

    def __init__(self):
        self.de = Pin(config.RS485_DE_PIN, Pin.OUT, value=0)
        self.re = Pin(config.RS485_RE_PIN, Pin.OUT, value=0)
        self.uart = UART(
            config.UART_ID,
            baudrate=config.SHTC3_BAUD_RATE,
            bits=config.RS485_BITS,
            parity=config.RS485_PARITY,
            stop=config.RS485_STOP,
            tx=Pin(config.UART_TX_PIN),
            rx=Pin(config.UART_RX_PIN),
            timeout=50,
            timeout_char=8,
        )
        self.baud_rate = None
        self.set_baud_rate(config.SHTC3_BAUD_RATE)

    def set_baud_rate(self, baud_rate):
        if self.baud_rate == baud_rate:
            return
        self.de.value(0)
        self.re.value(0)
        self.uart.init(
            baudrate=baud_rate,
            bits=config.RS485_BITS,
            parity=config.RS485_PARITY,
            stop=config.RS485_STOP,
            timeout=50,
            timeout_char=8,
        )
        self.baud_rate = baud_rate
        self.clear_rx()
        time.sleep_ms(20)

    def clear_rx(self):
        while self.uart.any():
            self.uart.read()

    def query(self, frame, timeout_ms=600):
        self.clear_rx()
        self.re.value(1)
        self.de.value(1)
        time.sleep_us(100)
        written = self.uart.write(frame)
        if written is not None and written != len(frame):
            self.de.value(0)
            self.re.value(0)
            raise RuntimeError("RS485 UART write failed")
        if hasattr(self.uart, "flush"):
            self.uart.flush()
        else:
            time.sleep_us(len(frame) * 11 * 1000000 // self.baud_rate + 200)
        self.de.value(0)
        self.re.value(0)

        response = bytearray()
        started = time.ticks_ms()
        last_byte = started
        while time.ticks_diff(time.ticks_ms(), started) < timeout_ms:
            available = self.uart.any()
            if available:
                chunk = self.uart.read(available)
                if chunk:
                    response.extend(chunk)
                    last_byte = time.ticks_ms()
            if response and time.ticks_diff(time.ticks_ms(), last_byte) >= 12:
                break
            time.sleep_ms(1)
        return bytes(response)

    def read_registers(self, slave_id, function_code, register, count):
        frame = add_crc(bytes((
            slave_id,
            function_code,
            (register >> 8) & 0xFF,
            register & 0xFF,
            (count >> 8) & 0xFF,
            count & 0xFF,
        )))
        response = self.query(frame)
        if not response:
            raise RuntimeError("response timeout")
        if len(response) < 5 or not valid_crc(response):
            raise RuntimeError("invalid CRC or short response")
        if response[0] != slave_id:
            raise RuntimeError("unexpected slave id {}".format(response[0]))
        if response[1] == (function_code | 0x80):
            raise RuntimeError("Modbus exception 0x{:02X}".format(response[2]))
        if response[1] != function_code or response[2] != count * 2:
            raise RuntimeError("unexpected Modbus response")
        return [
            (response[3 + offset * 2] << 8) | response[4 + offset * 2]
            for offset in range(count)
        ]

    def read(self):
        payload = {}
        errors = {}
        try:
            self.set_baud_rate(config.SHTC3_BAUD_RATE)
            humidity_raw, temperature_raw = self.read_registers(
                config.SHTC3_SLAVE_ID,
                READ_HOLDING_REGISTERS,
                config.SHTC3_HUMIDITY_REGISTER,
                2,
            )
            payload["air_temp"] = round(signed_word(temperature_raw) / 10.0, 2)
            payload["humidity"] = round(humidity_raw / 10.0, 2)
        except Exception as error:
            errors["rs485_shtc3"] = str(error)

        try:
            self.set_baud_rate(config.KCD_HP100_CO2_BAUD_RATE)
            co2_raw = self.read_registers(
                config.KCD_HP100_CO2_SLAVE_ID,
                READ_INPUT_REGISTERS,
                config.KCD_HP100_CO2_REGISTER,
                1,
            )[0]
            payload["co2"] = int(co2_raw)
        except Exception as error:
            errors["rs485_co2"] = str(error)
        return payload, errors
