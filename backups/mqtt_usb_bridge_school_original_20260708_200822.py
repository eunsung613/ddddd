# 환경: Windows 서버용 노트북 + Python 3.10 이상 권장
# 필요 라이브러리:
#   pip install pyserial paho-mqtt
#
# 데이터 흐름:
#   Pico2 W → USB Serial → 서버용 노트북 → MQTT Broker
#
# 주의:
# - HiveMQ Public Broker는 테스트용입니다.
# - 실제 운영에서는 인증 있는 MQTT Broker를 사용해야 합니다.
# - Thonny가 Pico2 W COM 포트를 잡고 있으면 이 프로그램은 실행되지 않습니다.

from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import serial
import paho.mqtt.client as mqtt


# 1. 여기를 실제 Pico2 W COM 포트로 바꾸세요.
SERIAL_PORT = "COM5"

SERIAL_BAUDRATE = 115200

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_CLIENT_ID = "school_server_bridge_001"

TOPIC_TELEMETRY = "farm/school/room1/pico2w_001/telemetry"
TOPIC_STATUS = "farm/school/room1/pico2w_001/status"

KST = timezone(timedelta(hours=9))


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


def add_server_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Pico2 W 데이터에 서버용 정보를 추가한다."""
    data["site_id"] = "school"
    data["zone_id"] = "room1"
    data["bridge_id"] = MQTT_CLIENT_ID
    data["ts"] = now_kst_iso()
    return data


def main() -> None:
    """USB Serial 데이터를 읽어서 MQTT로 Publish한다."""
    print("MQTT-USB Bridge 시작")
    print(f"Serial port: {SERIAL_PORT}")
    print(f"MQTT broker: {MQTT_BROKER}:{MQTT_PORT}")
    print(f"Telemetry topic: {TOPIC_TELEMETRY}")

    mqtt_client = make_mqtt_client()
    mqtt_started = False

    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        mqtt_client.loop_start()
        mqtt_started = True

        mqtt_client.publish(
            TOPIC_STATUS,
            json.dumps(
                {
                    "type": "status",
                    "bridge_id": MQTT_CLIENT_ID,
                    "status": "bridge_online",
                    "ts": now_kst_iso(),
                },
                ensure_ascii=False,
            ),
        )

        with serial.Serial(
            port=SERIAL_PORT,
            baudrate=SERIAL_BAUDRATE,
            timeout=1,
        ) as ser:
            print("Serial 연결 성공")
            print("Pico2 W 데이터 대기 중... (Ctrl+C로 종료)")

            while True:
                raw_line = ser.readline()

                if not raw_line:
                    continue

                line = raw_line.decode("utf-8", errors="replace").strip()

                if not line:
                    continue

                print("USB RX:", line)

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    print("JSON 아님. 무시:", line)
                    continue

                if not isinstance(data, dict):
                    print("JSON 객체가 아님. 무시:", line)
                    continue

                data = add_server_fields(data)

                mqtt_payload = json.dumps(data, ensure_ascii=False)
                result = mqtt_client.publish(TOPIC_TELEMETRY, mqtt_payload)

                print("MQTT TX:", mqtt_payload)
                print("Publish result:", result.rc)

                time.sleep(0.01)
    except KeyboardInterrupt:
        print("\n사용자가 Bridge를 종료했습니다.")
    except serial.SerialException as exc:
        print(f"\nSerial 오류: {exc}")
        print(f"{SERIAL_PORT} 포트를 Thonny 등 다른 프로그램이 사용 중인지 확인하세요.")
    except OSError as exc:
        print(f"\nMQTT 연결 오류: {exc}")
        print("인터넷 연결과 MQTT Broker 주소를 확인하세요.")
    finally:
        if mqtt_started:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()


if __name__ == "__main__":
    main()

