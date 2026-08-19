"""School-laptop smart-farm control center.

The laptop owns USB serial, SQLite, camera capture, AI analysis, reports and
Telegram notifications. AI only creates recommendations. A named human must
approve an actuator request before the safety gate can send it to the Pico.
"""

from __future__ import annotations

import base64
import hmac
import json
import math
import os
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests
import serial
import paho.mqtt.client as mqtt
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel, Field
from requests.auth import HTTPDigestAuth

from .reporting import generate_daily_pdf
from .storage import Store


BASE_DIR = Path(__file__).resolve().parent
ROOT = BASE_DIR.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("SMARTFARM_DATA_DIR", ROOT / "data"))
CAPTURE_DIR = DATA_DIR / "captures"
REPORT_DIR = DATA_DIR / "reports"
DB_PATH = Path(os.getenv("SMARTFARM_DB_PATH", DATA_DIR / "smartfarm.db"))
CONFIG_PATH = Path(os.getenv("SMARTFARM_SCHOOL_CONFIG", ROOT / "config.school.json"))
HOME_CONFIG_PATH = Path(os.getenv("SMARTFARM_HOME_CONFIG", ROOT / "config.home.json"))

SIMULATION = os.getenv("SMARTFARM_SIMULATION", "0") == "1"
CONTROL_ENABLED = os.getenv("SMARTFARM_CONTROL_ENABLED", "0") == "1"
CHEMICAL_CONTROL_ENABLED = os.getenv("SMARTFARM_CHEMICAL_CONTROL_ENABLED", "0") == "1"
AUTOMATION_ENABLED = os.getenv("SMARTFARM_AUTOMATION_ENABLED", "1") == "1"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-sol")
MQTT_MODE = os.getenv("SMARTFARM_MQTT_MODE", "off").strip().lower()
SENSOR_STALE_SECONDS = 20

if MQTT_MODE not in ("off", "publish", "subscribe"):
    raise ValueError("SMARTFARM_MQTT_MODE must be off, publish or subscribe")

ACTUATORS = {
    "led": {"label": "LED", "max_seconds": 57600},
    "raw_water": {"label": "원수", "max_seconds": 60},
    "supply": {"label": "양액 공급", "max_seconds": 120},
    "mixing": {"label": "교반", "max_seconds": 300},
    "ec": {"label": "EC 정량펌프", "max_seconds": 5},
    "ph": {"label": "pH 정량펌프", "max_seconds": 5},
    "fan": {"label": "환풍기", "max_seconds": 1800},
}

store = Store(DB_PATH)
security = HTTPBasic(auto_error=False)
stop_event = threading.Event()
serial_lock = threading.Lock()
state_lock = threading.Lock()
serial_connection: serial.Serial | None = None
scheduler: BackgroundScheduler | None = None
mqtt_client: mqtt.Client | None = None
mqtt_config: dict[str, Any] | None = None
mqtt_sequence = 0

runtime_state: dict[str, Any] = {
    "pico_connected": False,
    "port": None,
    "last_error": "Pico USB data waiting",
    "updated_at_epoch": None,
    "actuators": {name: "off" for name in ACTUATORS},
    "last_ack": None,
    "mqtt_connected": False,
    "mqtt_error": None,
}


class ManualRequest(BaseModel):
    state: str = Field(pattern="^(on|off)$")
    duration_seconds: int = Field(default=0, ge=0)
    reason: str = Field(min_length=2, max_length=300)
    operator: str = Field(min_length=2, max_length=50)


class DecisionRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    operator: str = Field(min_length=2, max_length=50)
    note: str = Field(default="", max_length=300)


def require_auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
    username = os.getenv("DASHBOARD_USERNAME")
    password = os.getenv("DASHBOARD_PASSWORD")
    if not username or not password:
        return
    if credentials is None:
        raise HTTPException(401, "Login required", headers={"WWW-Authenticate": "Basic"})
    valid = hmac.compare_digest(credentials.username, username) and hmac.compare_digest(
        credentials.password, password
    )
    if not valid:
        raise HTTPException(401, "Invalid login", headers={"WWW-Authenticate": "Basic"})


def load_serial_config() -> tuple[str, int]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing {CONFIG_PATH.name}")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    port = config.get("serial_port")
    if not port or port == "COM_PORT_HERE":
        raise ValueError("Set serial_port in config.school.json")
    return str(port), int(config.get("serial_baudrate", 115200))


def load_mqtt_config() -> dict[str, Any]:
    path = CONFIG_PATH if MQTT_MODE == "publish" else HOME_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Missing {path.name}")
    config = json.loads(path.read_text(encoding="utf-8"))
    if not config.get("mqtt_broker") or not config.get("topics", {}).get("telemetry"):
        raise ValueError(f"Set mqtt_broker and topics.telemetry in {path.name}")
    return config


def make_mqtt_client(config: dict[str, Any]) -> mqtt.Client:
    if MQTT_MODE == "publish":
        client_id = str(config.get("mqtt_client_id", "school_dashboard_publisher"))
    else:
        prefix = str(config.get("mqtt_subscriber_client_id_prefix", "home_dashboard"))
        client_id = f"{prefix}_{uuid.uuid4().hex[:8]}"
    if hasattr(mqtt, "CallbackAPIVersion"):
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
    else:
        client = mqtt.Client(client_id=client_id)
    username = config.get("mqtt_username")
    if username:
        client.username_pw_set(str(username), str(config.get("mqtt_password", "")))
    if config.get("mqtt_tls"):
        client.tls_set()
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    return client


def normalize_mqtt_telemetry(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "air_temp": data.get("air_temp", data.get("temp_c")),
        "humidity": data.get("humidity", data.get("rh")),
        "co2": data.get("co2", data.get("co2_ppm")),
        "scd40_temp": data.get("scd40_temp"),
        "scd40_humidity": data.get("scd40_humidity"),
        "ec": data.get("ec"),
        "ph": data.get("ph"),
        "solution_temp": data.get("solution_temp", data.get("solution_temp_c")),
        "actuators": data.get("actuators", {}),
        "mqtt_ts": data.get("ts"),
        "mqtt_seq": data.get("seq"),
    }


def ingest_mqtt_telemetry(data: dict[str, Any]) -> None:
    if data.get("type") != "telemetry":
        raise ValueError("MQTT payload type is not telemetry")
    payload = normalize_mqtt_telemetry(data)
    if not any(payload.get(key) is not None for key in ("air_temp", "humidity", "co2", "ec", "ph")):
        raise ValueError("MQTT telemetry has no supported sensor value")
    store.add_sensor(payload, "measured:mqtt_school")
    update_runtime(
        pico_connected=True,
        port="MQTT",
        last_error=None,
        updated_at_epoch=time.time(),
        actuators=payload.get("actuators") or runtime_state["actuators"],
    )


def mqtt_on_connect(
    client: mqtt.Client,
    _userdata: Any,
    _flags: Any,
    reason_code: Any,
    _properties: Any = None,
) -> None:
    failed = bool(getattr(reason_code, "is_failure", False))
    update_runtime(
        mqtt_connected=not failed,
        mqtt_error=str(reason_code) if failed else None,
    )
    if not failed and MQTT_MODE == "subscribe" and mqtt_config:
        client.subscribe(mqtt_config["topics"]["telemetry"], qos=0)


def mqtt_on_disconnect(
    _client: mqtt.Client,
    _userdata: Any,
    _disconnect_flags: Any,
    reason_code: Any,
    _properties: Any = None,
) -> None:
    values: dict[str, Any] = {
        "mqtt_connected": False,
        "mqtt_error": f"MQTT disconnected: {reason_code}",
    }
    if MQTT_MODE == "subscribe":
        values.update(pico_connected=False, last_error="MQTT connection lost")
    update_runtime(**values)


def mqtt_on_message(
    _client: mqtt.Client,
    _userdata: Any,
    message: mqtt.MQTTMessage,
) -> None:
    try:
        data = json.loads(message.payload.decode("utf-8"))
        ingest_mqtt_telemetry(data)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        update_runtime(last_error=f"Invalid MQTT telemetry: {error}")


def start_mqtt_transport() -> None:
    global mqtt_client, mqtt_config
    if SIMULATION or MQTT_MODE == "off":
        return
    mqtt_config = load_mqtt_config()
    mqtt_client = make_mqtt_client(mqtt_config)
    mqtt_client.on_connect = mqtt_on_connect
    mqtt_client.on_disconnect = mqtt_on_disconnect
    if MQTT_MODE == "subscribe":
        mqtt_client.on_message = mqtt_on_message
    mqtt_client.connect_async(
        str(mqtt_config["mqtt_broker"]),
        int(mqtt_config.get("mqtt_port", 1883)),
        keepalive=60,
    )
    mqtt_client.loop_start()


def stop_mqtt_transport() -> None:
    global mqtt_client
    if mqtt_client is None:
        return
    mqtt_client.disconnect()
    mqtt_client.loop_stop()
    mqtt_client = None


def publish_mqtt_telemetry(payload: dict[str, Any]) -> None:
    global mqtt_sequence
    if MQTT_MODE != "publish" or mqtt_client is None or mqtt_config is None:
        return
    mqtt_sequence += 1
    message = {
        "type": "telemetry",
        "site_id": mqtt_config.get("site_id", "school"),
        "zone_id": mqtt_config.get("zone_id", "room1"),
        "device_id": mqtt_config.get("device_id", "pico2w_001"),
        "bridge_id": mqtt_config.get("bridge_id", "school_dashboard"),
        "seq": mqtt_sequence,
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        **payload,
    }
    result = mqtt_client.publish(
        mqtt_config["topics"]["telemetry"],
        json.dumps(message, ensure_ascii=False),
        qos=0,
        retain=False,
    )
    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        update_runtime(mqtt_error=f"MQTT publish failed: {result.rc}")


def update_runtime(**values: Any) -> None:
    with state_lock:
        runtime_state.update(values)


def start_pico_runtime(pico: serial.Serial) -> None:
    pico.write(b"\r\x03\x03\x02")
    time.sleep(0.5)
    pico.reset_input_buffer()
    pico.write(b"exec(open('smartfarm_runtime.py').read())\r\n")


def process_serial_line(line: str) -> None:
    if line.startswith("TELEMETRY_JSON:"):
        payload = json.loads(line.split(":", 1)[1])
        store.add_sensor(payload, "measured:pico_usb")
        publish_mqtt_telemetry(payload)
        update_runtime(
            pico_connected=True,
            last_error=None,
            updated_at_epoch=time.time(),
            actuators=payload.get("actuators", runtime_state["actuators"]),
        )
    elif line.startswith("ACK_JSON:"):
        update_runtime(last_ack=json.loads(line.split(":", 1)[1]))
    elif line.startswith("TELEMETRY_ERROR:"):
        payload = json.loads(line.split(":", 1)[1])
        update_runtime(last_error=payload.get("error", "Pico telemetry error"))


def serial_worker() -> None:
    global serial_connection
    try:
        port, baudrate = load_serial_config()
        with serial.Serial(port, baudrate, timeout=1) as pico:
            with serial_lock:
                serial_connection = pico
            update_runtime(port=port, last_error="Starting Pico runtime")
            start_pico_runtime(pico)
            while not stop_event.is_set():
                line = pico.readline().decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    process_serial_line(line)
                except (json.JSONDecodeError, TypeError, ValueError) as error:
                    update_runtime(last_error=f"Invalid Pico line: {error}")
    except (FileNotFoundError, ValueError, serial.SerialException) as error:
        update_runtime(pico_connected=False, last_error=str(error))
    finally:
        with serial_lock:
            serial_connection = None


def simulation_worker() -> None:
    update_runtime(pico_connected=True, port="SIMULATION", last_error=None)
    started = time.time()
    while not stop_event.wait(5):
        phase = (time.time() - started) / 120
        payload = {
            "air_temp": round(22.3 + math.sin(phase) * 1.4, 2),
            "humidity": round(67.0 + math.sin(phase * 0.7) * 5.0, 2),
            "co2": int(610 + math.sin(phase * 1.3) * 45),
            "scd40_temp": round(22.5 + math.sin(phase) * 1.2, 2),
            "scd40_humidity": round(66.5 + math.sin(phase * 0.7) * 4.5, 2),
            "ec": round(1.72 + math.sin(phase * 0.5) * 0.04, 3),
            "ph": round(6.14 + math.sin(phase * 0.4) * 0.08, 2),
            "solution_temp": round(21.7 + math.sin(phase * 0.6) * 0.5, 1),
            "actuators": runtime_state["actuators"],
        }
        store.add_sensor(payload, "simulation:not_measured")
        update_runtime(updated_at_epoch=time.time())


def mqtt_wait_worker() -> None:
    update_runtime(port="MQTT", last_error="Waiting for school MQTT telemetry")
    stop_event.wait()


def latest_with_health() -> dict[str, Any]:
    latest = store.latest_sensor() or {}
    with state_lock:
        runtime = dict(runtime_state)
    epoch = runtime.get("updated_at_epoch")
    age = round(time.time() - epoch, 1) if epoch else None
    connected = bool(runtime["pico_connected"] and age is not None and age <= SENSOR_STALE_SECONDS)
    return {
        **latest,
        "pico_connected": connected,
        "port": runtime["port"],
        "age_seconds": age,
        "error": runtime["last_error"] if not connected else None,
        "actuators": runtime["actuators"],
        "simulation": SIMULATION,
        "mqtt_mode": MQTT_MODE,
    }


def send_pico_command(command: dict[str, Any]) -> None:
    if SIMULATION:
        with state_lock:
            runtime_state["actuators"][command["actuator"]] = command["state"]
            runtime_state["last_ack"] = {**command, "result": "simulation"}
        return
    with serial_lock:
        if serial_connection is None:
            raise RuntimeError("Pico USB is not connected")
        serial_connection.write(("CMD_JSON:" + json.dumps(command) + "\r\n").encode("utf-8"))


def safe_execute(item: dict[str, Any], operator: str) -> tuple[str, str]:
    actuator = item.get("actuator")
    if not actuator:
        return "reviewed", "No actuator command was attached"
    if MQTT_MODE == "subscribe":
        raise HTTPException(409, "Remote MQTT dashboard is read-only")
    if actuator not in ACTUATORS:
        raise HTTPException(400, "Unknown actuator")
    if actuator in ("ec", "ph") and not CHEMICAL_CONTROL_ENABLED:
        raise HTTPException(409, "Chemical pump control is disabled")
    state = item.get("requested_state")
    duration = int(item.get("duration_seconds") or 0)
    if state == "on" and not 0 < duration <= ACTUATORS[actuator]["max_seconds"]:
        raise HTTPException(400, "Duration exceeds the safety limit")
    if not CONTROL_ENABLED:
        return "simulated", "CONTROL_ENABLED=0; approval logged without hardware output"
    latest = latest_with_health()
    if not latest["pico_connected"]:
        raise HTTPException(409, "Pico data is offline or stale")
    command = {
        "cmd_id": secrets.token_hex(8), "action": "set", "actuator": actuator,
        "state": state, "duration_seconds": duration,
    }
    send_pico_command(command)
    store.add_event({
        "command_id": command["cmd_id"], "actuator": actuator,
        "requested_state": state, "duration_seconds": duration,
        "source": f"approved:{operator}", "result": "sent", "note": item["rationale"],
    })
    return "executed", f"Sent command {command['cmd_id']}"


def camera_configs() -> list[dict[str, str]]:
    cameras = []
    for number in range(1, 5):
        url = os.getenv(f"CAMERA_{number}_SNAPSHOT_URL", "").strip()
        if url:
            cameras.append({
                "id": f"CAM-{number:02d}", "url": url,
                "username": os.getenv(f"CAMERA_{number}_USERNAME", ""),
                "password": os.getenv(f"CAMERA_{number}_PASSWORD", ""),
            })
    return cameras


def capture_cameras() -> list[dict[str, Any]]:
    results = []
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    cameras = camera_configs()
    for camera in cameras:
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        path = CAPTURE_DIR / f"{camera['id']}_{timestamp}.jpg"
        try:
            response = requests.get(
                camera["url"], auth=HTTPDigestAuth(camera["username"], camera["password"]),
                timeout=15,
            )
            response.raise_for_status()
            if not response.content.startswith(b"\xff\xd8"):
                raise ValueError("Camera response is not JPEG")
            path.write_bytes(response.content)
            capture_id = store.add_capture(camera["id"], str(path), "success", None)
            results.append({"id": capture_id, "camera_id": camera["id"], "status": "success"})
        except (requests.RequestException, OSError, ValueError) as error:
            capture_id = store.add_capture(camera["id"], None, "failed", str(error))
            results.append({"id": capture_id, "camera_id": camera["id"], "status": "failed", "error": str(error)})
    store.workflow(
        "camera_capture", "success" if cameras else "skipped",
        json.dumps(results, ensure_ascii=False) if cameras else "No camera is configured",
    )
    return results


def most_recent_capture() -> dict[str, Any] | None:
    for item in store.captures(20):
        if item["status"] == "success" and item.get("path") and Path(item["path"]).exists():
            return item
    return None


def deterministic_analysis(latest: dict[str, Any], capture: dict[str, Any] | None) -> dict[str, Any]:
    warnings = []
    for label, key, low, high in (
        ("기온", "air_temp", 18.0, 25.0), ("습도", "humidity", 60.0, 80.0),
        ("EC", "ec", 1.5, 2.0), ("pH", "ph", 5.5, 6.5),
    ):
        value = latest.get(key)
        if value is None:
            warnings.append(f"{label} 데이터 누락")
        elif not low <= float(value) <= high:
            warnings.append(f"{label} {value}가 관리 기준 {low}~{high} 밖")
    overall = "주의" if warnings else ("정상" if latest else "판단 불가")
    observations = []
    limitations = []
    if capture:
        observations.append("카메라 이미지는 저장되었으나 규칙 분석에서는 식물 외형을 판독하지 않음")
    else:
        limitations.append("사용 가능한 카메라 이미지 없음")
    return {
        "model": "rule-engine:no-ai", "capture_id": capture["id"] if capture else None,
        "overall_status": overall,
        "summary": "; ".join(warnings) if warnings else "수집된 환경값이 현재 관리 기준 안에 있습니다.",
        "confidence": "중간" if latest else "낮음",
        "observations": observations,
        "limitations": limitations + ["OpenAI API를 사용하지 않은 규칙 기반 결과"],
    }


def openai_analysis(latest: dict[str, Any], capture: dict[str, Any] | None) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return deterministic_analysis(latest, capture)
    content: list[dict[str, Any]] = [{
        "type": "input_text",
        "text": (
            "브로콜리 스마트팜 일일 관찰을 수행하라. 센서값 출처와 누락을 구분하고, "
            "사진에서 직접 보이는 사실만 기록하라. 병해충을 확진하지 말고 제어 명령을 내리지 마라. "
            "반드시 JSON 하나만 반환하라: "
            '{"overall_status":"정상|주의|경고|판단 불가","summary":"...",'
            '"confidence":"높음|중간|낮음","observations":["..."],"limitations":["..."]}. '
            "센서 데이터: " + json.dumps(latest, ensure_ascii=False, default=str)
        ),
    }]
    if capture and capture.get("path"):
        image_bytes = Path(capture["path"]).read_bytes()
        content.append({
            "type": "input_image",
            "image_url": "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii"),
        })
    response = OpenAI(api_key=api_key).responses.create(
        model=OPENAI_MODEL,
        reasoning={"effort": "medium"},
        input=[{"role": "user", "content": content}],
        text={
            "format": {
                "type": "json_schema",
                "name": "broccoli_daily_observation",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "overall_status": {
                            "type": "string",
                            "enum": ["정상", "주의", "경고", "판단 불가"],
                        },
                        "summary": {"type": "string"},
                        "confidence": {
                            "type": "string",
                            "enum": ["높음", "중간", "낮음"],
                        },
                        "observations": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "limitations": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": [
                        "overall_status", "summary", "confidence",
                        "observations", "limitations",
                    ],
                    "additionalProperties": False,
                },
            }
        },
    )
    raw = response.output_text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    result = json.loads(raw)
    result.update({
        "model": getattr(response, "model", OPENAI_MODEL),
        "capture_id": capture["id"] if capture else None,
    })
    return result


def create_rule_recommendations(latest: dict[str, Any]) -> list[int]:
    candidates = []
    temp, humidity = latest.get("air_temp"), latest.get("humidity")
    if temp is not None and float(temp) > 25.0:
        candidates.append({
            "source": "deterministic_rule", "severity": "warning",
            "title": "고온으로 환풍기 작동 검토", "rationale": f"기온 {temp}℃가 기준 상한 25.0℃ 초과",
            "actuator": "fan", "requested_state": "on", "duration_seconds": 300,
            "evidence": {"air_temp": temp, "threshold": 25.0}, "model": None,
        })
    if humidity is not None and float(humidity) > 80.0:
        candidates.append({
            "source": "deterministic_rule", "severity": "warning",
            "title": "고습으로 환풍기 작동 검토", "rationale": f"습도 {humidity}%가 기준 상한 80.0% 초과",
            "actuator": "fan", "requested_state": "on", "duration_seconds": 300,
            "evidence": {"humidity": humidity, "threshold": 80.0}, "model": None,
        })
    pending_titles = {item["title"] for item in store.recommendations() if item["status"] == "pending"}
    return [store.add_recommendation(item) for item in candidates if item["title"] not in pending_titles]


def run_analysis() -> dict[str, Any]:
    latest = store.latest_sensor() or {}
    capture = most_recent_capture()
    try:
        result = openai_analysis(latest, capture)
        analysis_id = store.add_analysis(result)
        recommendation_ids = create_rule_recommendations(latest)
        store.workflow("ai_analysis", "success", f"analysis={analysis_id}")
        return {"id": analysis_id, "recommendation_ids": recommendation_ids, **result}
    except Exception as error:
        store.workflow("ai_analysis", "failed", str(error))
        raise


def telegram_send_report(path: Path, caption: str) -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return "not_configured"
    with path.open("rb") as document:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendDocument",
            data={"chat_id": chat_id, "caption": caption}, files={"document": document}, timeout=30,
        )
    response.raise_for_status()
    return "sent"


def create_report(report_date: str | None = None, send_telegram: bool = False) -> dict[str, Any]:
    report_date = report_date or date.today().isoformat()
    stats = store.day_stats(report_date)
    data_source = store.day_source_label(report_date)
    analyses = store.analyses(1)
    analysis = analyses[0] if analyses else None
    capture = most_recent_capture()
    capture_path = Path(capture["path"]) if capture and capture.get("path") else None
    model = analysis["model"] if analysis else "분석 기록 없음"
    output = REPORT_DIR / f"broccoli_daily_{report_date}.pdf"
    generate_daily_pdf(output, report_date, stats, analysis, capture_path, model, data_source, BASE_DIR)
    telegram_status = telegram_send_report(output, f"{report_date} 브로콜리 AI 일일 생육관찰 보고서") if send_telegram else "not_requested"
    report_id = store.add_report({
        "report_date": report_date, "path": str(output), "model": model,
        "status": "created", "telegram_status": telegram_status,
    })
    store.workflow("daily_report", "success", f"report={report_id}")
    return {"id": report_id, "report_date": report_date, "model": model, "telegram_status": telegram_status}


def capture_and_analyze_job() -> None:
    capture_cameras()
    run_analysis()


def daily_report_job() -> None:
    create_report(send_telegram=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global scheduler
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    store.initialize()
    stop_event.clear()
    start_mqtt_transport()
    if SIMULATION:
        worker_target = simulation_worker
    elif MQTT_MODE == "subscribe":
        worker_target = mqtt_wait_worker
    else:
        worker_target = serial_worker
    worker = threading.Thread(target=worker_target, daemon=True)
    worker.start()
    if AUTOMATION_ENABLED:
        scheduler = BackgroundScheduler(timezone="Asia/Seoul")
        scheduler.add_job(capture_and_analyze_job, "cron", hour="0,6,12,18", minute=0, id="capture_analysis", max_instances=1)
        scheduler.add_job(daily_report_job, "cron", hour=20, minute=0, id="daily_report", max_instances=1)
        scheduler.start()
    yield
    stop_event.set()
    if scheduler:
        scheduler.shutdown(wait=False)
    stop_mqtt_transport()
    worker.join(timeout=2)


app = FastAPI(title="Broccoli Smart Farm Control Center", version="2.0", lifespan=lifespan)


@app.get("/api/health", dependencies=[Depends(require_auth)])
def health() -> dict[str, Any]:
    latest = latest_with_health()
    return {
        "server": "online", "database": "online", "pico": "online" if latest["pico_connected"] else "offline",
        "simulation": SIMULATION,
        "control_enabled": CONTROL_ENABLED and MQTT_MODE != "subscribe",
        "mqtt_mode": MQTT_MODE,
        "mqtt_connected": bool(runtime_state["mqtt_connected"]),
        "mqtt_error": runtime_state["mqtt_error"],
        "chemical_control_enabled": CHEMICAL_CONTROL_ENABLED and MQTT_MODE != "subscribe",
        "automation_enabled": AUTOMATION_ENABLED, "configured_model": OPENAI_MODEL,
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "telegram_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
        "camera_count": len(camera_configs()), "database_path": str(DB_PATH),
        "pico_error": latest.get("error"),
    }


@app.get("/api/sensors/latest", dependencies=[Depends(require_auth)])
def latest_sensors() -> dict[str, Any]:
    return latest_with_health()


@app.get("/api/sensors/history", dependencies=[Depends(require_auth)])
def sensor_history(hours: int = Query(24, ge=1, le=720)) -> list[dict[str, Any]]:
    return store.sensor_history(hours)


@app.get("/api/actuators", dependencies=[Depends(require_auth)])
def actuators() -> dict[str, Any]:
    with state_lock:
        states = dict(runtime_state["actuators"])
    return {"control_enabled": CONTROL_ENABLED and MQTT_MODE != "subscribe",
            "chemical_control_enabled": CHEMICAL_CONTROL_ENABLED and MQTT_MODE != "subscribe",
            "items": [{"id": key, "state": states.get(key, "unknown"), **value} for key, value in ACTUATORS.items()]}


@app.post("/api/actuators/{actuator}/request", dependencies=[Depends(require_auth)])
def request_actuator(actuator: str, request: ManualRequest) -> dict[str, Any]:
    if actuator not in ACTUATORS:
        raise HTTPException(404, "Unknown actuator")
    if request.state == "on" and not 0 < request.duration_seconds <= ACTUATORS[actuator]["max_seconds"]:
        raise HTTPException(400, "Duration exceeds the safety limit")
    recommendation_id = store.add_recommendation({
        "source": "manual_dashboard", "severity": "manual", "title": f"{ACTUATORS[actuator]['label']} 수동 제어 요청",
        "rationale": f"{request.operator}: {request.reason}", "actuator": actuator,
        "requested_state": request.state, "duration_seconds": request.duration_seconds,
        "evidence": {"operator": request.operator}, "model": None,
    })
    return {"id": recommendation_id, "status": "pending", "message": "승인 대기열에 추가했습니다."}


@app.get("/api/recommendations", dependencies=[Depends(require_auth)])
def recommendations() -> list[dict[str, Any]]:
    return store.recommendations()


@app.post("/api/recommendations/{recommendation_id}/decision", dependencies=[Depends(require_auth)])
def decide(recommendation_id: int, request: DecisionRequest) -> dict[str, Any]:
    item = store.recommendation(recommendation_id)
    if not item:
        raise HTTPException(404, "Recommendation not found")
    if item["status"] != "pending":
        raise HTTPException(409, "Recommendation was already decided")
    if request.decision == "reject":
        store.decide_recommendation(recommendation_id, "rejected", request.operator, request.note)
        return {"status": "rejected"}
    status, note = safe_execute(item, request.operator)
    store.decide_recommendation(recommendation_id, status, request.operator, note)
    return {"status": status, "note": note}


@app.get("/api/cameras", dependencies=[Depends(require_auth)])
def cameras() -> dict[str, Any]:
    return {"configured": [{"id": item["id"], "url": item["url"].split("@")[-1]} for item in camera_configs()],
            "captures": store.captures()}


@app.post("/api/cameras/capture", dependencies=[Depends(require_auth)])
def capture_now() -> list[dict[str, Any]]:
    return capture_cameras()


@app.get("/api/captures/{capture_id}", dependencies=[Depends(require_auth)])
def capture_file(capture_id: int) -> FileResponse:
    item = next((row for row in store.captures(200) if row["id"] == capture_id), None)
    if not item or not item.get("path") or not Path(item["path"]).exists():
        raise HTTPException(404, "Capture not found")
    return FileResponse(item["path"], media_type="image/jpeg")


@app.post("/api/analysis/run", dependencies=[Depends(require_auth)])
def analysis_now() -> dict[str, Any]:
    return run_analysis()


@app.get("/api/analyses", dependencies=[Depends(require_auth)])
def analyses() -> list[dict[str, Any]]:
    return store.analyses()


@app.post("/api/reports/generate", dependencies=[Depends(require_auth)])
def report_now(send_telegram: bool = False) -> dict[str, Any]:
    return create_report(send_telegram=send_telegram)


@app.get("/api/reports", dependencies=[Depends(require_auth)])
def reports() -> list[dict[str, Any]]:
    return store.reports()


@app.get("/api/reports/{report_id}/download", dependencies=[Depends(require_auth)])
def report_file(report_id: int) -> FileResponse:
    item = next((row for row in store.reports(200) if row["id"] == report_id), None)
    if not item or not Path(item["path"]).exists():
        raise HTTPException(404, "Report not found")
    return FileResponse(item["path"], media_type="application/pdf", filename=Path(item["path"]).name)


@app.get("/api/workflows", dependencies=[Depends(require_auth)])
def workflows() -> list[dict[str, Any]]:
    return store.workflows()


@app.post("/api/workflows/capture-analysis", dependencies=[Depends(require_auth)])
def workflow_capture_analysis() -> dict[str, Any]:
    captures = capture_cameras()
    analysis = run_analysis()
    return {"captures": captures, "analysis": analysis}


@app.get("/")
def dashboard(_auth: None = Depends(require_auth)) -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


app.mount("/fonts", StaticFiles(directory=BASE_DIR / "fonts"), name="fonts")
app.mount("/assets", StaticFiles(directory=BASE_DIR / "assets"), name="assets")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8765)
