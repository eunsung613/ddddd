# 목적: Pico2 W가 가짜 센서값을 USB Serial로 보내고,
#      USB Serial 명령을 받아 내장 LED/릴레이 핀을 제어한다.
#
# 환경:
# - Raspberry Pi Pico2 W
# - MicroPython
#
# 필요 라이브러리:
# - machine
# - time
# - sys
# - select
# - ujson
#
# USB 명령 예:
# - RELAY1_ON
# - RELAY1_OFF
# - RELAY1_TOGGLE
# - RELAY1_ON:5
# - STATUS
#
# 주의:
# - 현재는 릴레이 대신 내장 LED와 GP16을 같이 제어한다.
# - 실제 릴레이 연결 전에는 내장 LED 동작만 먼저 확인한다.

import sys
import time
import select
from machine import Pin

try:
    import ujson as json
except ImportError:
    import json


DEVICE_ID = "pico2w_001"

LED = Pin("LED", Pin.OUT)
RELAY_1 = Pin(16, Pin.OUT)

LED.off()
RELAY_1.off()

count = 0
last_telemetry_time = 0
telemetry_interval_sec = 2

poll = select.poll()
poll.register(sys.stdin, select.POLLIN)


def send_line(message):
    """USB Serial로 한 줄 메시지를 보낸다."""
    print(message)


def make_fake_telemetry(sequence):
    """테스트용 가짜 센서값을 만든다."""
    temp_c = 24.0 + (sequence % 10) * 0.1
    rh = 60.0 + (sequence % 20) * 0.2
    co2_ppm = 500 + (sequence % 30) * 3
    lux = 12000 + (sequence % 50) * 10
    ec = 0.80 + (sequence % 5) * 0.01
    ph = 5.80 + (sequence % 6) * 0.01

    return {
        "type": "telemetry",
        "device_id": DEVICE_ID,
        "seq": sequence,
        "temp_c": round(temp_c, 2),
        "rh": round(rh, 2),
        "co2_ppm": co2_ppm,
        "lux": lux,
        "ec": round(ec, 2),
        "ph": round(ph, 2),
        "relay_1": RELAY_1.value()
    }


def publish_telemetry():
    """가짜 센서값을 USB Serial로 출력한다."""
    global count

    count += 1
    payload = make_fake_telemetry(count)
    send_line(json.dumps(payload))


def relay_on(duration_sec=None):
    """릴레이 1번을 켠다. duration_sec가 있으면 해당 시간 뒤 자동 OFF."""
    RELAY_1.on()
    LED.on()

    if duration_sec is None:
        send_line("ACK:RELAY1_ON")
        return

    send_line("ACK:RELAY1_ON:{}SEC".format(duration_sec))
    time.sleep(duration_sec)

    RELAY_1.off()
    LED.off()
    send_line("ACK:RELAY1_AUTO_OFF")


def relay_off():
    """릴레이 1번을 끈다."""
    RELAY_1.off()
    LED.off()
    send_line("ACK:RELAY1_OFF")


def relay_toggle():
    """릴레이 1번 상태를 반전한다."""
    RELAY_1.toggle()
    LED.toggle()
    send_line("ACK:RELAY1_TOGGLE:{}".format(RELAY_1.value()))


def send_status():
    """현재 상태를 보낸다."""
    status = {
        "type": "status",
        "device_id": DEVICE_ID,
        "relay_1": RELAY_1.value(),
        "led": LED.value()
    }
    send_line(json.dumps(status))


def handle_command(command):
    """USB Serial 명령을 처리한다."""
    command = command.strip()

    if not command:
        return

    if command.startswith("RELAY1_ON:"):
        try:
            duration_text = command.split(":", 1)[1]
            duration_sec = int(duration_text)
        except ValueError:
            send_line("ERR:INVALID_DURATION")
            return

        if duration_sec <= 0 or duration_sec > 60:
            send_line("ERR:DURATION_OUT_OF_RANGE")
            return

        relay_on(duration_sec)
        return

    if command == "RELAY1_ON":
        relay_on()
    elif command == "RELAY1_OFF":
        relay_off()
    elif command == "RELAY1_TOGGLE":
        relay_toggle()
    elif command == "STATUS":
        send_status()
    else:
        send_line("ERR:UNKNOWN_COMMAND:{}".format(command))


def check_serial_command():
    """USB Serial로 들어온 명령이 있으면 읽어서 처리한다."""
    events = poll.poll(0)

    if not events:
        return

    command = sys.stdin.readline()
    handle_command(command)


send_line("PICO_CONTROL_READY")

while True:
    check_serial_command()

    now = time.time()
    if now - last_telemetry_time >= telemetry_interval_sec:
        last_telemetry_time = now
        publish_telemetry()

    time.sleep(0.02)
