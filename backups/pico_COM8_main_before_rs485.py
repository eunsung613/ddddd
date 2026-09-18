"""
목적:
    Raspberry Pi Pico 2 + Digilent PmodRS485를 사용하여
    Modbus RTU 센서의 Slave Address(국번)를 자동 검색합니다.

환경:
    - Raspberry Pi Pico 2
    - MicroPython
    - Digilent PmodRS485
    - Modbus RTU RS485 센서

Pico2 <-> PmodRS485:
    GP2 -> ~RE
    GP0 -> TxD
    GP1 -> RxD
    GP3 -> DE
    GND -> GND
    3V3 -> VCC

기본 통신 조건:
    9600 bps
    8 data bits
    No parity
    1 stop bit

외부 라이브러리:
    없음
"""

from machine import Pin, UART
import time


# ============================================================
# 사용자 설정
# ============================================================

UART_ID = 0

TX_PIN = 0
RX_PIN = 1

RE_PIN = 2
DE_PIN = 3

# 센서 통신속도를 알고 있다면 하나만 넣는 것이 좋습니다.
BAUD_RATES = [
    9600,
]

# 예:
# BAUD_RATES = [4800, 9600, 19200]

DATA_BITS = 8
PARITY = None
STOP_BITS = 1

# Modbus Slave Address 검색 범위
SLAVE_START = 1
SLAVE_END = 247

# 테스트할 Holding Register
TEST_REGISTER = 0x0000

# 응답 대기시간
RESPONSE_TIMEOUT_MS = 80

# 검색 재시도 횟수
RETRIES = 2


# ============================================================
# CRC16 MODBUS
# ============================================================

def modbus_crc16(data: bytes) -> int:
    """
    Modbus RTU CRC-16 계산
    Polynomial: 0xA001
    """

    crc = 0xFFFF

    for byte in data:
        crc ^= byte

        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1

    return crc


# ============================================================
# RS485 방향 제어
# ============================================================

re_pin = Pin(RE_PIN, Pin.OUT)
de_pin = Pin(DE_PIN, Pin.OUT)


def set_receive_mode() -> None:
    """
    PmodRS485를 수신 모드로 설정

    ~RE = 0 : Receiver Enable
    DE  = 0 : Driver Disable
    """

    de_pin.value(0)
    re_pin.value(0)


def set_transmit_mode() -> None:
    """
    PmodRS485를 송신 모드로 설정

    ~RE = 1 : Receiver Disable
    DE  = 1 : Driver Enable
    """

    re_pin.value(1)
    de_pin.value(1)


# 초기 상태는 수신 모드
set_receive_mode()


# ============================================================
# Modbus 요청 프레임 생성
# ============================================================

def make_read_request(
    slave_address: int,
    register_address: int = 0x0000,
) -> bytes:
    """
    Function 03 - Read Holding Registers

    레지스터 1개 읽기 요청
    """

    function_code = 0x03
    register_count = 1

    frame = bytes([
        slave_address,
        function_code,
        (register_address >> 8) & 0xFF,
        register_address & 0xFF,
        (register_count >> 8) & 0xFF,
        register_count & 0xFF,
    ])

    crc = modbus_crc16(frame)

    return frame + bytes([
        crc & 0xFF,
        (crc >> 8) & 0xFF,
    ])


# ============================================================
# UART 버퍼 비우기
# ============================================================

def clear_uart_buffer(uart: UART) -> None:
    """UART RX 버퍼를 비웁니다."""

    while uart.any():
        uart.read()

    time.sleep_ms(2)


# ============================================================
# RS485 송수신
# ============================================================

def send_modbus_request(
    uart: UART,
    request: bytes,
    baudrate: int,
) -> bytes:
    """
    Modbus 요청 송신 후 응답을 수신합니다.
    """

    clear_uart_buffer(uart)

    # --------------------------------------------------------
    # 송신 모드
    # --------------------------------------------------------

    set_transmit_mode()

    time.sleep_us(100)

    uart.write(request)

    # UART.write() 직후 바로 DE를 LOW로 만들면
    # 마지막 byte가 아직 전송 중일 수 있습니다.
    #
    # 8N1 = 대략 한 문자당 10 bit
    #
    # 여기에 2 문자 정도의 여유시간을 추가합니다.

    transmission_time_us = int(
        ((len(request) + 2) * 10 * 1_000_000)
        / baudrate
    )

    time.sleep_us(transmission_time_us)

    # --------------------------------------------------------
    # 수신 모드
    # --------------------------------------------------------

    set_receive_mode()

    time.sleep_us(200)

    # --------------------------------------------------------
    # 응답 수신
    # --------------------------------------------------------

    response = bytearray()

    start_time = time.ticks_ms()
    last_receive_time = None

    while (
        time.ticks_diff(
            time.ticks_ms(),
            start_time,
        )
        < RESPONSE_TIMEOUT_MS
    ):

        if uart.any():
            data = uart.read()

            if data:
                response.extend(data)
                last_receive_time = time.ticks_ms()

        # 데이터가 들어온 뒤 일정 시간 추가 데이터가 없다면
        # 하나의 Modbus frame이 끝났다고 판단
        if last_receive_time is not None:

            if (
                time.ticks_diff(
                    time.ticks_ms(),
                    last_receive_time,
                )
                > 5
            ):
                break

        time.sleep_ms(1)

    return bytes(response)


# ============================================================
# 정상 Modbus 응답 프레임 찾기
# ============================================================

def find_valid_response(
    raw_data: bytes,
    expected_address: int,
) -> bytes | None:
    """
    수신 데이터에서 유효한 Modbus RTU 응답을 찾습니다.

    정상 Function 03 응답뿐 아니라
    Exception Response(0x83)도 인정합니다.

    Exception 응답이라도 해당 국번의 장치가 실제로
    요청을 수신하여 응답했다는 의미이기 때문입니다.
    """

    if len(raw_data) < 5:
        return None

    for start in range(len(raw_data)):

        if raw_data[start] != expected_address:
            continue

        if start + 2 >= len(raw_data):
            continue

        function_code = raw_data[start + 1]

        # ----------------------------------------------------
        # 정상 Function 03 응답
        # ----------------------------------------------------

        if function_code == 0x03:

            if start + 3 > len(raw_data):
                continue

            byte_count = raw_data[start + 2]

            frame_length = 3 + byte_count + 2

        # ----------------------------------------------------
        # Exception Response
        # 0x03 + 0x80 = 0x83
        # ----------------------------------------------------

        elif function_code == 0x83:

            frame_length = 5

        else:
            continue

        end = start + frame_length

        if end > len(raw_data):
            continue

        frame = raw_data[start:end]

        # CRC 확인
        received_crc = (
            frame[-2]
            | (frame[-1] << 8)
        )

        calculated_crc = modbus_crc16(
            frame[:-2]
        )

        if received_crc == calculated_crc:
            return frame

    return None


# ============================================================
# 주소 하나 검사
# ============================================================

def test_slave_address(
    uart: UART,
    baudrate: int,
    slave_address: int,
) -> bytes | None:
    """
    특정 Slave Address가 존재하는지 검사합니다.
    """

    request = make_read_request(
        slave_address,
        TEST_REGISTER,
    )

    for _ in range(RETRIES):

        response = send_modbus_request(
            uart,
            request,
            baudrate,
        )

        valid_frame = find_valid_response(
            response,
            slave_address,
        )

        if valid_frame is not None:
            return valid_frame

        time.sleep_ms(5)

    return None


# ============================================================
# Modbus Address Scan
# ============================================================

def scan_modbus_addresses(
    baudrate: int,
) -> list[int]:
    """
    Slave Address 1~247 검색
    """

    print()
    print("=" * 60)
    print("Modbus RTU Slave Address Scanner")
    print("=" * 60)

    print("Baudrate :", baudrate)
    print(
        "Range    :",
        SLAVE_START,
        "~",
        SLAVE_END,
    )

    print()

    uart = UART(
        UART_ID,
        baudrate=baudrate,
        bits=DATA_BITS,
        parity=PARITY,
        stop=STOP_BITS,
        tx=Pin(TX_PIN),
        rx=Pin(RX_PIN),
        timeout=RESPONSE_TIMEOUT_MS,
    )

    found_addresses: list[int] = []

    for address in range(
        SLAVE_START,
        SLAVE_END + 1,
    ):

        print(
            "\r검색 중: 국번 {:3d} / {}".format(
                address,
                SLAVE_END,
            ),
            end="",
        )

        response = test_slave_address(
            uart,
            baudrate,
            address,
        )

        if response is not None:

            found_addresses.append(address)

            print()
            print()
            print(
                ">>> 센서 발견!"
            )

            print(
                "    국번      :",
                address,
            )

            print(
                "    Baudrate  :",
                baudrate,
            )

            print(
                "    응답 HEX  :",
                " ".join(
                    "{:02X}".format(byte)
                    for byte in response
                ),
            )

            # Exception Response 여부
            if response[1] & 0x80:

                print(
                    "    응답 종류 : Modbus Exception"
                )

                print(
                    "    Exception :",
                    response[2],
                )

            else:

                print(
                    "    응답 종류 : 정상 응답"
                )

            print()

        # Modbus frame 사이 간격 확보
        time.sleep_ms(5)

    uart.deinit()

    return found_addresses


# ============================================================
# Main
# ============================================================

def main() -> None:

    print()
    print("================================")
    print(" Pico2 Modbus Address Scanner")
    print("================================")

    all_found = []

    for baudrate in BAUD_RATES:

        addresses = scan_modbus_addresses(
            baudrate,
        )

        for address in addresses:

            result = (
                baudrate,
                address,
            )

            if result not in all_found:
                all_found.append(result)

    print()
    print("=" * 60)
    print("검색 완료")
    print("=" * 60)

    if not all_found:

        print()
        print("응답하는 Modbus 센서를 찾지 못했습니다.")

        print()
        print("확인할 항목:")
        print("1. 센서 전원")
        print("2. RS485 A/B 결선")
        print("3. PmodRS485 A-Y / B-Z 연결")
        print("4. Baudrate")
        print("5. Parity / Stop bit")
        print("6. 센서가 실제 Modbus RTU 방식인지")
        print()

    else:

        print()
        print("발견된 장치")
        print("-" * 40)

        for baudrate, address in all_found:

            print(
                "Baudrate = {:6d} / 국번 = {}".format(
                    baudrate,
                    address,
                )
            )

        print("-" * 40)


if __name__ == "__main__":
    main()