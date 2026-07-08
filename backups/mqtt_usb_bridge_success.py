# 목적: Pico2 W와 USB Serial로 통신하면서 MQTT Broker와 양방향 중계한다.
#
# 환경:
# - Windows 서버용 노트북
# - Python 3.10 이상 권장
#
# 필요 라이브러리:
#   pip install pyserial paho-mqtt
#
# 데이터 흐름:
#   상행: Pico2 W → USB Serial → 서버 노트북 → MQTT telemetry publish
#   하행: MQTT cmd subscribe → 서버 노트북 → USB Serial → Pico2 W 제어
#
# 주의:
# - broker.hivemq.com은 공개 테스트 broker입니다.
# - 실제 릴레이/펌프 제어에는 인증 있는 broker를 사용해야 합니다.
# - cmd topic에는 retained message를 사용하지 않습니다.
# - Thonny가 Pico2 W COM 포트를 잡고 있으면 실행되지 않습니다.

from __future__ import annotations

import json
import queue
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import serial
import paho.mqtt.client as mqtt


SERIAL_PORT = "COM5"  # 실제 Pico2 W COM 포트로 수정하세요.
SERIAL_BAUDRATE = 115200

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_CLIENT_ID = "school_server_bridge_001"

TOPIC_TELEMETRY = "farm/school/room1/pico2w_001/telemetry"
TOPIC_STATUS = "farm/school/room1/pico2w_001/status"
TOPIC_CMD = "farm/school/room1/pico2w_001/cmd"
TOPIC_ACK = "farm/school/room1/pico2w_001/ack"

LOG_INTERVAL_SEC = 10

KST = timezone(timedelta(hours=9))

serial_tx_queue: "queue.Queue[dict[str, Any]]" = queue.Queue()
mqtt_client: mqtt.Client | None = None
last_cmd_id: str | None = None
last_cmd_payload: dict[str, Any] | None = None


def now_kst_iso() -> str:
    """현재 한국 시간을 ISO 문자열로 만든다."""
    return datetime.now(KST).isoformat(timespec="seconds")


def make_mqtt_client() -> mqtt.Client:
    """paho-mqtt 버전에 맞춰 MQTT client를 만든다."""
    if hasattr(mqtt, "CallbackAPIVersion"):
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=MQTT_CLIENT_ID,
        )
    else:
        client = mqtt.Client(client_id=MQTT_CLIENT_ID)

    return client


def publish_json(topic: str, payload: dict[str, Any], retain: bool = False) -> None:
    """MQTT topic으로 JSON payload를 publish한다."""
    if mqtt_client is None:
        print("MQTT client is not ready")
        return

    mqtt_client.publish(
        topic,
        json.dumps(payload, ensure_ascii=False),
        qos=0,
        retain=retain,
    )


def add_server_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Pico2 W 데이터에 서버용 정보를 추가한다."""
    data["site_id"] = "school"
    data["zone_id"] = "room1"
    data["bridge_id"] = MQTT_CLIENT_ID
    data["ts"] = now_kst_iso()
    return data


def convert_mqtt_cmd_to_serial(data: dict[str, Any]) -> str | None:
    """MQTT cmd payload를 Pico2 W serial 명령으로 변환한다."""
    target = data.get("target")
    action = data.get("action")
    duration_sec = data.get("duration_sec")

    if target != "relay_1":
        return None

    if action == "on":
        if duration_sec is not None:
            return f"RELAY1_ON:{int(duration_sec)}\n"
        return "RELAY1_ON\n"

    if action == "off":
        return "RELAY1_OFF\n"

    if action == "toggle":
        return "RELAY1_TOGGLE\n"

    if action == "status":
        return "STATUS\n"

    return None


def on_connect(
    client: mqtt.Client,
    userdata: Any,
    flags: Any,
    reason_code: Any,
    properties: Any = None,
) -> None:
    """MQTT broker 연결 후 cmd topic을 구독한다."""
    print("MQTT 연결됨:", reason_code)
    print("구독 cmd topic:", TOPIC_CMD)

    client.subscribe(TOPIC_CMD)

    publish_json(
        TOPIC_STATUS,
        {
            "type": "status",
            "bridge_id": MQTT_CLIENT_ID,
            "status": "bridge_online",
            "ts": now_kst_iso(),
        },
    )


def on_message(
    client: mqtt.Client,
    userdata: Any,
    msg: mqtt.MQTTMessage,
) -> None:
    """MQTT cmd 메시지를 받으면 Serial 명령 queue에 넣는다."""
    try:
        data = json.loads(msg.payload.decode("utf-8"))
    except json.JSONDecodeError:
        publish_json(
            TOPIC_ACK,
            {
                "type": "ack",
                "result": "error",
                "message": "invalid json command",
                "ts": now_kst_iso(),
            },
        )
        return

    serial_command = convert_mqtt_cmd_to_serial(data)

    if serial_command is None:
        publish_json(
            TOPIC_ACK,
            {
                "type": "ack",
                "cmd_id": data.get("cmd_id"),
                "result": "error",
                "message": "unsupported command",
                "received": data,
                "ts": now_kst_iso(),
            },
        )
        return

    serial_tx_queue.put(
        {
            "cmd_id": data.get("cmd_id", "unknown"),
            "serial_command": serial_command,
            "original": data,
        }
    )

    publish_json(
        TOPIC_ACK,
        {
            "type": "ack",
            "cmd_id": data.get("cmd_id", "unknown"),
            "result": "queued",
            "serial_command": serial_command.strip(),
            "ts": now_kst_iso(),
        },
    )


def handle_serial_line(line: str) -> None:
    """Pico2 W에서 받은 한 줄을 처리한다."""
    global last_cmd_id
    global last_cmd_payload

    # JSON이면 telemetry/status로 판단
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, dict):
        data = add_server_fields(data)

        if data.get("type") == "telemetry":
            publish_json(TOPIC_TELEMETRY, data)
            return

        if data.get("type") == "status":
            publish_json(TOPIC_STATUS, data)
            return

    # JSON이 아니면 ACK/ERR 같은 문자열 응답으로 처리
    if line.startswith("ACK:") or line.startswith("ERR:"):
        publish_json(
            TOPIC_ACK,
            {
                "type": "ack",
                "cmd_id": last_cmd_id,
                "result": "ok" if line.startswith("ACK:") else "error",
                "serial_response": line,
                "original_cmd": last_cmd_payload,
                "ts": now_kst_iso(),
            },
        )

        if line.startswith("ACK:") or line.startswith("ERR:"):
            last_cmd_id = None
            last_cmd_payload = None

        return

    # 기타 문자열은 status로 올림
    publish_json(
        TOPIC_STATUS,
        {
            "type": "status",
            "bridge_id": MQTT_CLIENT_ID,
            "message": line,
            "ts": now_kst_iso(),
        },
    )


def main() -> None:
    """MQTT와 USB Serial을 연결한다."""
    global mqtt_client
    global last_cmd_id
    global last_cmd_payload

    print("MQTT-USB 양방향 Bridge 시작")
    print(f"Serial port: {SERIAL_PORT}")
    print(f"MQTT broker: {MQTT_BROKER}:{MQTT_PORT}")
    print(f"Telemetry topic: {TOPIC_TELEMETRY}")
    print(f"Cmd topic: {TOPIC_CMD}")
    print(f"Ack topic: {TOPIC_ACK}")

    mqtt_client = make_mqtt_client()
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    mqtt_client.loop_start()

    last_log_time = 0.0

    with serial.Serial(
        port=SERIAL_PORT,
        baudrate=SERIAL_BAUDRATE,
        timeout=0.1,
    ) as ser:
        time.sleep(2)
        print("Serial 연결 성공")
        print("Pico2 W 데이터 대기 중...")

        publish_json(
            TOPIC_STATUS,
            {
                "type": "status",
                "bridge_id": MQTT_CLIENT_ID,
                "status": "serial_connected",
                "serial_port": SERIAL_PORT,
                "ts": now_kst_iso(),
            },
        )

        while True:
            # 1. MQTT로 받은 명령을 Pico2 W로 전송
            try:
                item = serial_tx_queue.get_nowait()
                serial_command = item["serial_command"]

                last_cmd_id = item["cmd_id"]
                last_cmd_payload = item["original"]

                print("SERIAL TX:", serial_command.strip())
                ser.write(serial_command.encode("utf-8"))

            except queue.Empty:
                pass

            # 2. Pico2 W에서 올라오는 데이터 읽기
            raw_line = ser.readline()

            if raw_line:
                line = raw_line.decode("utf-8", errors="replace").strip()

                if line:
                    handle_serial_line(line)

                    now = time.time()
                    if now - last_log_time >= LOG_INTERVAL_SEC:
                        print("SERIAL RX:", line)
                        print("last publish/check at:", now_kst_iso())
                        last_log_time = now

            time.sleep(0.01)


if __name__ == "__main__":
    main()
