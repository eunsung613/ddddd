"""School-laptop dashboard server for the Pico 2 W I2C sensor test."""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import serial
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


BASE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = BASE_DIR.parent
DEFAULT_CONFIG_PATH = REPOSITORY_ROOT / "config.school.json"
CONFIG_PATH = Path(os.getenv("SMARTFARM_SCHOOL_CONFIG", DEFAULT_CONFIG_PATH))
STALE_AFTER_SECONDS = 15

state_lock = threading.Lock()
stop_event = threading.Event()
sensor_state: dict[str, Any] = {
    "i2c_connected": False,
    "port": None,
    "air_temp": None,
    "humidity": None,
    "co2": None,
    "scd40_temp": None,
    "scd40_humidity": None,
    "i2c_updated_at": None,
    "i2c_error": "Pico I2C data waiting",
    "pe350_connected": False,
    "pe350_error": "PE350 is not included in this independent I2C test",
}


def update_state(**values: Any) -> None:
    with state_lock:
        sensor_state.update(values)


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing configuration file: {CONFIG_PATH}. "
            "Copy config.school.example.json to config.school.json first."
        )
    with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        return json.load(config_file)


def start_pico_i2c_test(pico: serial.Serial) -> None:
    pico.write(b"\r\x03\x03\x02")
    time.sleep(0.5)
    pico.reset_input_buffer()
    pico.write(b"exec(open('i2c_sensor_test.py').read())\r\n")


def serial_worker() -> None:
    try:
        config = load_config()
        serial_port = config["serial_port"]
        serial_baudrate = config.get("serial_baudrate", 115200)

        if serial_port == "COM_PORT_HERE":
            raise ValueError("Set the real Pico COM port in config.school.json")

        with serial.Serial(serial_port, serial_baudrate, timeout=1) as pico:
            update_state(port=serial_port, i2c_error="Starting Pico I2C test")
            start_pico_i2c_test(pico)

            while not stop_event.is_set():
                line = pico.readline().decode("utf-8", errors="replace").strip()
                if not line.startswith("I2C_JSON:"):
                    lowered = line.lower()
                    if "not found" in lowered or "error" in lowered:
                        update_state(i2c_connected=False, i2c_error=line)
                    continue

                try:
                    payload = json.loads(line.split(":", 1)[1])
                    update_state(
                        i2c_connected=True,
                        air_temp=float(payload["air_temp_c"]),
                        humidity=float(payload["humidity_pct"]),
                        co2=int(payload["co2_ppm"]),
                        scd40_temp=float(payload["scd40_temp_c"]),
                        scd40_humidity=float(payload["scd40_humidity_pct"]),
                        i2c_updated_at=time.time(),
                        i2c_error=None,
                    )
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                    update_state(i2c_connected=False, i2c_error=f"Invalid I2C data: {error}")
    except (FileNotFoundError, KeyError, ValueError, serial.SerialException) as error:
        update_state(i2c_connected=False, i2c_error=str(error))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop_event.clear()
    thread = threading.Thread(target=serial_worker, daemon=True)
    thread.start()
    yield
    stop_event.set()
    thread.join(timeout=2)


app = FastAPI(title="Broccoli I2C Sensor Dashboard", lifespan=lifespan)


@app.get("/api/sensors/latest")
def latest_sensors() -> dict[str, Any]:
    with state_lock:
        result = dict(sensor_state)

    updated_at = result["i2c_updated_at"]
    if updated_at is None:
        result["i2c_age_seconds"] = None
        return result

    age = time.time() - updated_at
    result["i2c_age_seconds"] = round(age, 1)
    if age > STALE_AFTER_SECONDS:
        result["i2c_connected"] = False
        result["i2c_error"] = "I2C sensor data has not updated for 15 seconds"
    return result


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


app.mount("/fonts", StaticFiles(directory=BASE_DIR / "fonts"), name="fonts")
app.mount("/assets", StaticFiles(directory=BASE_DIR / "assets"), name="assets")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8765)
