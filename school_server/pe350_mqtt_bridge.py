"""Read PE350 values from a Pico 2 W over USB serial and publish them to MQTT.

Run this file only on the school server laptop connected to the Pico by USB.
This bridge publishes read-only sensor telemetry; it does not control actuators.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
import serial


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.school.json"


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"설정 파일이 없습니다: {path}\n"
            "config.school.example.json을 config.school.json으로 복사한 뒤 "
            "serial_port를 서버 노트북의 실제 COM 포트로 바꾸세요."
        )
    with path.open("r", encoding="utf-8") as config_file:
        return json.load(config_file)


def make_mqtt_client(client_id: str) -> mqtt.Client:
    if hasattr(mqtt, "CallbackAPIVersion"):
        return mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
    return mqtt.Client(client_id=client_id)


def parse_sensor_line(line: str, pending: dict[str, float]) -> dict[str, float] | None:
    if line.startswith("SENSOR_JSON:"):
        data = json.loads(line.split(":", 1)[1])
        return {
            "ec": float(data["ec"]),
            "ph": float(data["ph"]),
            "solution_temp_c": float(data["solution_temp"]),
        }

    if line.startswith("EC         :"):
        pending["ec"] = float(line.split(":", 1)[1].split()[0])
    elif line.startswith("pH         :"):
        pending["ph"] = float(line.split(":", 1)[1].strip())
    elif line.startswith("Temperature:"):
        pending["solution_temp_c"] = float(line.split(":", 1)[1].split()[0])

    if {"ec", "ph", "solution_temp_c"} <= pending.keys():
        result = dict(pending)
        pending.clear()
        return result
    return None


def start_pico_test(pico: serial.Serial) -> None:
    pico.write(b"\r\x03\x03")
    time.sleep(0.3)
    pico.reset_input_buffer()
    pico.write(b"import pe350_read_only_test; pe350_read_only_test.main()\r\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--port", help="설정 파일 대신 사용할 서버 노트북 COM 포트")
    args = parser.parse_args()

    config = load_config(args.config)
    serial_port = args.port or config["serial_port"]
    if serial_port == "COM_PORT_HERE":
        raise ValueError("config.school.json의 serial_port에 실제 COM 포트를 입력하세요.")

    topic = config["topics"]["telemetry"]
    client = make_mqtt_client(config["mqtt_client_id"])
    client.connect(config["mqtt_broker"], config["mqtt_port"], keepalive=60)
    client.loop_start()

    print("학교 서버용 PE350 -> MQTT 브리지")
    print(f"Pico USB : {serial_port} / {config['serial_baudrate']}bps")
    print(f"MQTT     : {config['mqtt_broker']}:{config['mqtt_port']}")
    print(f"Topic    : {topic}")
    print("읽기 전용입니다. 종료: Ctrl+C")

    seq = 0
    pending: dict[str, float] = {}
    last_values: tuple[float, float, float] | None = None
    last_publish_time = 0.0

    try:
        with serial.Serial(
            serial_port,
            config["serial_baudrate"],
            timeout=1,
        ) as pico:
            start_pico_test(pico)

            while True:
                line = pico.readline().decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                try:
                    sensor = parse_sensor_line(line, pending)
                except (ValueError, KeyError, json.JSONDecodeError) as error:
                    print("센서 출력 해석 실패:", error, "|", line)
                    continue

                if sensor is None:
                    continue

                values = (
                    sensor["ec"],
                    sensor["ph"],
                    sensor["solution_temp_c"],
                )
                now = time.monotonic()
                if values == last_values and now - last_publish_time < 0.5:
                    continue
                last_values = values
                last_publish_time = now

                seq += 1
                payload = {
                    "type": "telemetry",
                    "site_id": config["site_id"],
                    "zone_id": config["zone_id"],
                    "device_id": config["device_id"],
                    "bridge_id": config["bridge_id"],
                    "seq": seq,
                    **sensor,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
                result = client.publish(
                    topic,
                    json.dumps(payload, ensure_ascii=False),
                    qos=0,
                    retain=False,
                )
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    print("MQTT 발행 실패:", result.rc)
                    continue

                print(
                    f"발행 #{seq}: EC {sensor['ec']:.3f} dS/m | "
                    f"pH {sensor['ph']:.2f} | "
                    f"양액 온도 {sensor['solution_temp_c']:.1f} °C"
                )
    except KeyboardInterrupt:
        print("\n브리지를 종료합니다.")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
