import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dashboard.server import camera_configs, camera_settings_payload, env_file_value, public_camera_url


def main():
    keys = [
        f"CAMERA_{slot}_{suffix}"
        for slot in range(1, 5)
        for suffix in ("LABEL", "SNAPSHOT_URL", "USERNAME", "PASSWORD")
    ]
    original = {key: os.environ.get(key) for key in keys}
    try:
        for key in keys:
            os.environ.pop(key, None)
        os.environ.update({
            "CAMERA_1_LABEL": "좌측",
            "CAMERA_1_SNAPSHOT_URL": "http://192.168.1.60/picture",
            "CAMERA_1_USERNAME": "admin",
            "CAMERA_1_PASSWORD": "a secret#1",
            "CAMERA_3_SNAPSHOT_URL": "https://192.168.1.62/picture",
        })
        cameras = camera_configs()
        assert [camera["id"] for camera in cameras] == ["CAM-01", "CAM-03"]
        assert cameras[0]["label"] == "좌측"
        payload = camera_settings_payload()
        assert len(payload["slots"]) == 4
        assert payload["slots"][0]["password_saved"] is True
        assert payload["slots"][1]["configured"] is False
        assert "secret" not in str(payload)
        assert env_file_value("a secret#1") == '"a secret#1"'
        assert public_camera_url("http://admin:hidden@192.168.1.60/picture") == "http://192.168.1.60/picture"
        print("Camera configuration tests passed")
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    main()
