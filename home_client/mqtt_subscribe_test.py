# 목적: 개인 게이밍 노트북에서 학교 서버용 노트북이 MQTT로 올리는 센서값을 수신하되,
#      터미널 출력은 일정 시간 간격으로 제한한다.
#
# 환경:
# - Windows
# - Python 3.10 이상 권장
#
# 필요 라이브러리:
#   pip install paho-mqtt
#
# 데이터 흐름:
#   학교 Pico2 W
#   → 학교 서버용 노트북
#   → MQTT Broker
#   → 개인 게이밍 노트북
#
# 주의:
# - 학교 서버용 노트북에서 mqtt_usb_bridge.py가 계속 실행 중이어야 합니다.
# - broker.hivemq.com은 공개 테스트 broker입니다.
# - 실제 릴레이/펌프 제어에는 인증 있는 broker를 사용해야 합니다.

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.home.json"

with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
    CONFIG = json.load(config_file)

MQTT_BROKER = CONFIG["mqtt_broker"]
MQTT_PORT = CONFIG["mqtt_port"]

MQTT_CLIENT_ID = (
    f"{CONFIG['mqtt_subscriber_client_id_prefix']}_{uuid.uuid4().hex[:8]}"
)

TOPIC_SUBSCRIBE = CONFIG["topics"]["telemetry"]

# 터미널 출력 간격입니다.
# 너무 길면 답답하고, 너무 짧으면 터미널이 계속 밀립니다.
PRINT_INTERVAL_SEC = CONFIG["print_interval_sec"]

latest_payload: dict[str, Any] | None = None
latest_topic: str | None = None
latest_received_time: float = 0.0
payload_lock = threading.Lock()


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
    """MQTT broker 연결 후 topic을 구독한다."""
    print("MQTT 연결됨:", reason_code)
    print("Client ID:", MQTT_CLIENT_ID)
    print("구독 topic:", TOPIC_SUBSCRIBE)
    print(f"터미널 출력 간격: {PRINT_INTERVAL_SEC}초")
    print("-" * 60)

    client.subscribe(TOPIC_SUBSCRIBE)


def on_message(
    client: mqtt.Client,
    userdata: Any,
    msg: mqtt.MQTTMessage,
) -> None:
    """MQTT 메시지를 받으면 최신 payload만 저장한다."""
    global latest_payload
    global latest_topic
    global latest_received_time

    payload_text = msg.payload.decode("utf-8", errors="replace")

    try:
        data = json.loads(payload_text)
    except json.JSONDecodeError:
        data = {
            "type": "raw",
            "raw_payload": payload_text,
        }

    with payload_lock:
        latest_payload = data
        latest_topic = msg.topic
        latest_received_time = time.time()


def on_disconnect(
    client: mqtt.Client,
    userdata: Any,
    disconnect_flags: Any,
    reason_code: Any,
    properties: Any = None,
) -> None:
    """MQTT 연결이 끊겼을 때 출력한다."""
    print("MQTT 연결 끊김:", reason_code)


def clear_console() -> None:
    """터미널 화면을 정리한다."""
    os.system("cls" if os.name == "nt" else "clear")


def print_latest_payload() -> None:
    """가장 최근 payload를 보기 좋게 출력한다."""
    with payload_lock:
        data = latest_payload.copy() if latest_payload is not None else None
        topic = latest_topic
        received_time = latest_received_time

    clear_console()

    print("개인 게이밍 노트북 MQTT 실시간 수신 화면")
    print("=" * 60)
    print(f"Broker       : {MQTT_BROKER}:{MQTT_PORT}")
    print(f"Subscribe    : {TOPIC_SUBSCRIBE}")
    print(f"Client ID    : {MQTT_CLIENT_ID}")
    print(f"출력 간격    : {PRINT_INTERVAL_SEC}초")
    print("=" * 60)

    if data is None:
        print("아직 수신된 payload가 없습니다.")
        return

    print("TOPIC:", topic)
    print("수신 후 경과:", round(time.time() - received_time, 1), "초")
    print("-" * 60)

    if data.get("type") == "telemetry":
        print(f"장비 ID      : {data.get('device_id')}")
        print(f"순번 seq     : {data.get('seq')}")
        print(f"온도         : {data.get('air_temp', data.get('temp_c'))}")
        print(f"습도         : {data.get('humidity', data.get('rh'))}")
        print(f"CO2 ppm      : {data.get('co2', data.get('co2_ppm'))}")
        print(f"조도 lux     : {data.get('lux')}")
        print(f"EC           : {data.get('ec')}")
        print(f"pH           : {data.get('ph')}")
        print(f"양액 온도    : {data.get('solution_temp', data.get('solution_temp_c'))}")
        print(f"릴레이 상태  : {data.get('relay_1')}")
        print(f"site_id      : {data.get('site_id')}")
        print(f"zone_id      : {data.get('zone_id')}")
        print(f"bridge_id    : {data.get('bridge_id')}")
        print(f"시간 ts      : {data.get('ts')}")
    else:
        print("PAYLOAD JSON:")
        print(json.dumps(data, ensure_ascii=False, indent=2))

    print("-" * 60)
    print("종료하려면 Ctrl + C")


def main() -> None:
    """MQTT broker에 접속하고 최신 payload를 일정 간격으로 출력한다."""
    client = make_mqtt_client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    print("개인 게이밍 노트북 MQTT 수신 테스트 시작")
    print(f"Broker: {MQTT_BROKER}:{MQTT_PORT}")

    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)

    # MQTT 수신은 background thread에서 계속 처리
    client.loop_start()

    try:
        while True:
            print_latest_payload()
            time.sleep(PRINT_INTERVAL_SEC)

    except KeyboardInterrupt:
        print("\n사용자 종료 요청")
    finally:
        client.loop_stop()
        client.disconnect()
        print("MQTT 수신 종료")


if __name__ == "__main__":
    main()
