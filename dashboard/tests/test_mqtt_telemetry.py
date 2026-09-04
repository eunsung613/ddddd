"""MQTT telemetry must remain sensor-only and accept legacy field names."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dashboard.server import mqtt_sensor_payload, mqtt_to_sensor_payload


def test_sensor_payload_does_not_expose_control_or_camera_data() -> None:
    source = {
        "air_temp": 22.4,
        "humidity": 68.1,
        "co2": 620,
        "ec": 0.948,
        "ph": 7.5,
        "solution_temp": 21.9,
        "actuators": {"pump": "on"},
        "camera_password": "never-publish-this",
        "sensor_errors": {"scd40": "EIO"},
    }
    config = {
        "site_id": "school",
        "zone_id": "room1",
        "device_id": "pico2w_001",
        "bridge_id": "school_server_bridge_001",
    }

    result = mqtt_sensor_payload(source, config)

    assert result["temp_c"] == 22.4
    assert result["solution_temp_c"] == 21.9
    assert result["sensor_errors"] == {"scd40": "EIO"}
    assert "actuators" not in result
    assert "camera_password" not in result


def test_legacy_mqtt_names_are_normalized_for_dashboard() -> None:
    result = mqtt_to_sensor_payload({
        "temp_c": 23.1,
        "rh": 70.2,
        "co2_ppm": 640,
        "ec": 1.1,
        "ph": 6.4,
        "solution_temp_c": 22.0,
    })

    assert result["air_temp"] == 23.1
    assert result["humidity"] == 70.2
    assert result["co2"] == 640
    assert result["solution_temp"] == 22.0


def main() -> None:
    test_sensor_payload_does_not_expose_control_or_camera_data()
    test_legacy_mqtt_names_are_normalized_for_dashboard()
    print("MQTT telemetry tests passed")


if __name__ == "__main__":
    main()
