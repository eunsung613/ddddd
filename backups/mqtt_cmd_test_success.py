# 목적: 개인 게이밍 노트북에서 MQTT cmd를 publish해서
#      학교 서버용 노트북을 거쳐 Pico2 W 내장 LED/릴레이 핀을 제어한다.
#
# 환경:
# - Windows
# - Python 3.10 이상 권장
#
# 필요 라이브러리:
#   pip install paho-mqtt
#
# 명령 흐름:
#   개인 노트북 → MQTT cmd → 학교 서버 노트북 → USB Serial → Pico2 W
#
# 주의:
# - 현재 broker.hivemq.com은 공개 테스트 broker입니다.
# - 실제 펌프/220V 부하 제어에는 사용하지 마세요.
# - 처음에는 Pico2 W 내장 LED만 확인하세요.

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import paho.mqtt.client as mqtt


MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_CLIENT_ID = f"home_cmd_client_{uuid.uuid4().hex[:8]}"

TOPIC_CMD = "farm/school/room1/pico2w_001/cmd"
TOPIC_ACK = "farm/school/room1/pico2w_001/ack"
TOPIC_STATUS = "farm/school/room1/pico2w_001/status"


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


def on_connect(
    client: mqtt.Client,
    userdata: Any,
    flags: Any,
    reason_code: Any,
    properties: Any = None,
) -> None:
    """MQTT broker 연결 후 ack/status topic을 구독한다."""
    print("MQTT 연결됨:", reason_code)
    print("Client ID:", MQTT_CLIENT_ID)
    print("CMD topic:", TOPIC_CMD)

    client.subscribe(TOPIC_ACK)
    client.subscribe(TOPIC_STATUS)


def on_message(
    client: mqtt.Client,
    userdata: Any,
    msg: mqtt.MQTTMessage,
) -> None:
    """ACK/STATUS 메시지를 출력한다."""
    payload_text = msg.payload.decode("utf-8", errors="replace")

    print("\n" + "=" * 60)
    print("수신 TOPIC:", msg.topic)

    try:
        data = json.loads(payload_text)
        print(json.dumps(data, ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print(payload_text)

    print("=" * 60)


def publish_cmd(
    client: mqtt.Client,
    action: str,
    duration_sec: int | None = None,
) -> None:
    """relay_1 제어 명령을 publish한다."""
    cmd_id = f"cmd_{int(time.time())}_{uuid.uuid4().hex[:4]}"

    payload: dict[str, Any] = {
        "type": "cmd",
        "cmd_id": cmd_id,
        "target": "relay_1",
        "action": action,
    }

    if duration_sec is not None:
        payload["duration_sec"] = duration_sec

    print("\n명령 전송:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    # 제어 명령은 retain=False가 중요합니다.
    client.publish(
        TOPIC_CMD,
        json.dumps(payload, ensure_ascii=False),
        qos=0,
        retain=False,
    )


def main() -> None:
    """사용자 입력을 받아 MQTT 제어 명령을 보낸다."""
    client = make_mqtt_client()
    client.on_connect = on_connect
    client.on_message = on_message

    print("개인 게이밍 노트북 MQTT 제어 테스트 시작")
    print(f"Broker: {MQTT_BROKER}:{MQTT_PORT}")

    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()

    time.sleep(1)

    try:
        while True:
            print("\n명령을 선택하세요.")
            print("1 = LED/RELAY ON")
            print("2 = LED/RELAY OFF")
            print("3 = LED/RELAY TOGGLE")
            print("4 = STATUS")
            print("5 = 5초 ON 후 자동 OFF")
            print("q = 종료")

            choice = input("입력: ").strip().lower()

            if choice == "1":
                publish_cmd(client, "on")
            elif choice == "2":
                publish_cmd(client, "off")
            elif choice == "3":
                publish_cmd(client, "toggle")
            elif choice == "4":
                publish_cmd(client, "status")
            elif choice == "5":
                publish_cmd(client, "on", duration_sec=5)
            elif choice == "q":
                break
            else:
                print("알 수 없는 입력입니다.")

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n사용자 종료")
    finally:
        client.loop_stop()
        client.disconnect()
        print("MQTT 제어 테스트 종료")


if __name__ == "__main__":
    main()