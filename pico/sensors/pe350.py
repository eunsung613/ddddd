"""
Read-only PE350 / PE300 compatible Modbus RTU driver.

Safety rule:
    This module only uses function code 0x04 (Read Input Registers).
    It does not write PE350 settings and does not control pumps.
"""

import time

import config


READ_INPUT_REGISTERS = 0x04
SINGLE_REGISTER_COUNT = 0x0001


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
    received_crc = frame[-2] | (frame[-1] << 8)
    return received_crc == modbus_crc(frame[:-2])


def make_read_input_register_request(register, slave_id=config.PE350_SLAVE_ID):
    payload = bytes((
        slave_id,
        READ_INPUT_REGISTERS,
        (register >> 8) & 0xFF,
        register & 0xFF,
        (SINGLE_REGISTER_COUNT >> 8) & 0xFF,
        SINGLE_REGISTER_COUNT & 0xFF,
    ))
    return add_crc(payload)


def format_hex(data):
    return " ".join("{:02X}".format(byte) for byte in data)


def parse_single_register_response(response, slave_id=config.PE350_SLAVE_ID):
    if not response:
        raise RuntimeError("PE350 response timeout")
    if len(response) != 7:
        raise RuntimeError("Unexpected response length: {} bytes".format(len(response)))
    if not valid_crc(response):
        raise RuntimeError("PE350 CRC error")
    if response[0] != slave_id:
        raise RuntimeError("Unexpected slave id: {}".format(response[0]))
    if response[1] & 0x80:
        raise RuntimeError("Modbus exception: 0x{:02X}".format(response[2]))
    if response[1] != READ_INPUT_REGISTERS:
        raise RuntimeError("Unexpected function code: 0x{:02X}".format(response[1]))
    if response[2] != 0x02:
        raise RuntimeError("Unexpected byte count: {}".format(response[2]))
    return (response[3] << 8) | response[4]


def ec_us_cm_to_ds_m(raw):
    return raw / 1000.0


def ph_raw_to_ph(raw):
    return raw / 100.0


def temperature_raw_to_c(raw):
    return raw / 10.0


class PE350Modbus:
    def __init__(self, uart=None, de=None, re=None):
        """Use the shared RS485 UART when environment sensors already own it.

        Creating two UART(0) objects on MicroPython can leave the peripheral in
        an inconsistent state after repeated 9600/38400 bps changes.  Standalone
        test scripts may still instantiate this class without arguments.
        """
        if uart is None:
            from machine import Pin, UART
            uart = UART(
                config.UART_ID,
                baudrate=config.RS485_BAUD_RATE,
                bits=config.RS485_BITS,
                parity=config.RS485_PARITY,
                stop=config.RS485_STOP,
                tx=Pin(config.UART_TX_PIN),
                rx=Pin(config.UART_RX_PIN),
                timeout=100,
                timeout_char=20,
            )
            de = Pin(config.RS485_DE_PIN, Pin.OUT, value=0)
            re = Pin(config.RS485_RE_PIN, Pin.OUT, value=0)
        if de is None or re is None:
            raise ValueError("Shared RS485 UART requires DE and RE pins")
        self.uart = uart
        self.de = de
        self.re = re
        self.baud_rate = config.RS485_BAUD_RATE
        self.receive_mode()

    def configure_uart(self):
        """Restore PE350's 9600bps before each query on the shared bus."""
        self.receive_mode()
        self.uart.init(
            baudrate=config.RS485_BAUD_RATE,
            bits=config.RS485_BITS,
            parity=config.RS485_PARITY,
            stop=config.RS485_STOP,
            timeout=100,
            timeout_char=20,
        )
        self.baud_rate = config.RS485_BAUD_RATE
        self.clear_rx()
        time.sleep_ms(20)

    def receive_mode(self):
        self.de.value(0)
        self.re.value(0)

    def transmit_mode(self):
        self.re.value(1)
        self.de.value(1)

    def clear_rx(self):
        while self.uart.any():
            self.uart.read()

    def send(self, frame):
        self.configure_uart()
        self.clear_rx()
        time.sleep_ms(5)

        self.transmit_mode()
        time.sleep_us(100)

        written = self.uart.write(frame)
        if written is not None and written != len(frame):
            self.receive_mode()
            raise RuntimeError("UART write failed: {} / {} bytes".format(
                written,
                len(frame),
            ))

        if hasattr(self.uart, "flush"):
            self.uart.flush()
        else:
            tx_time_us = len(frame) * 10 * 1000000 // config.RS485_BAUD_RATE
            time.sleep_us(tx_time_us + 100)
        self.receive_mode()

    def receive(self, timeout_ms=config.PE350_RESPONSE_TIMEOUT_MS):
        response = bytearray()
        start = time.ticks_ms()
        last_byte = start

        while time.ticks_diff(time.ticks_ms(), start) < timeout_ms:
            available = self.uart.any()
            if available:
                chunk = self.uart.read(available)
                if chunk:
                    response.extend(chunk)
                    last_byte = time.ticks_ms()

            if response and time.ticks_diff(
                time.ticks_ms(),
                last_byte,
            ) >= config.PE350_FRAME_SILENCE_MS:
                break

            time.sleep_ms(1)

        return bytes(response)

    def read_register(self, register):
        request = make_read_input_register_request(register)
        if getattr(config, "PE350_DEBUG", False):
            print("TX:", format_hex(request))
        self.send(request)

        response = self.receive()
        if getattr(config, "PE350_DEBUG", False):
            print("RX:", format_hex(response) if response else "NO RESPONSE")
        return parse_single_register_response(response)

    def read_ec_us_cm(self):
        return self.read_register(config.PE350_EC_REGISTER)

    def read_ph_raw(self):
        return self.read_register(config.PE350_PH_REGISTER)

    def read_temperature_raw(self):
        return self.read_register(config.PE350_TEMPERATURE_REGISTER)
