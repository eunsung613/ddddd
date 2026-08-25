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
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import paho.mqtt.client as mqtt
import requests
import serial
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request
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

SIMULATION = os.getenv("SMARTFARM_SIMULATION", "0") == "1"
CONTROL_ENABLED = os.getenv("SMARTFARM_CONTROL_ENABLED", "0") == "1"
CHEMICAL_CONTROL_ENABLED = os.getenv("SMARTFARM_CHEMICAL_CONTROL_ENABLED", "0") == "1"
AUTOMATION_ENABLED = os.getenv("SMARTFARM_AUTOMATION_ENABLED", "1") == "1"
LED_SCHEDULE_HARDWARE_ENABLED = (
    os.getenv("SMARTFARM_LED_SCHEDULE_HARDWARE_ENABLED", "0") == "1"
)
SUPPLY_CONTINUOUS_ENABLED = os.getenv("SMARTFARM_SUPPLY_CONTINUOUS_ENABLED", "0") == "1"
SCD40_REQUIRED = os.getenv("SMARTFARM_SCD40_REQUIRED", "1") == "1"
MQTT_PUBLISH_ENABLED = os.getenv("SMARTFARM_MQTT_PUBLISH_ENABLED", "0") == "1"
MQTT_SUBSCRIBE_ENABLED = os.getenv("SMARTFARM_MQTT_SUBSCRIBE_ENABLED", "0") == "1"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-sol")
MQTT_MODE = "subscribe" if MQTT_SUBSCRIBE_ENABLED else "publish" if MQTT_PUBLISH_ENABLED else "off"
SENSOR_STALE_SECONDS = 20
SEOUL = ZoneInfo("Asia/Seoul")
SENSOR_ALERTS_ENABLED = os.getenv("SMARTFARM_SENSOR_ALERTS_ENABLED", "0") == "1"
NUTRIENT_FEEDBACK_ENABLED = os.getenv("SMARTFARM_NUTRIENT_FEEDBACK_ENABLED", "0") == "1"
EC_PULSE_SECONDS = max(1, min(int(os.getenv("SMARTFARM_EC_PULSE_SECONDS", "3")), 10))
PH_PULSE_SECONDS = max(1, min(int(os.getenv("SMARTFARM_PH_PULSE_SECONDS", "1")), 5))
NUTRIENT_MIX_SECONDS = max(15, min(int(os.getenv("SMARTFARM_NUTRIENT_MIX_SECONDS", "30")), 180))
RULE_ALERT_COOLDOWN_SECONDS = max(300, min(int(os.getenv("SMARTFARM_RULE_ALERT_COOLDOWN_SECONDS", "900")), 3600))
DEFAULT_GROWTH_STAGE = os.getenv("SMARTFARM_DEFAULT_GROWTH_STAGE", "육묘기").strip() or "육묘기"

# Profiles are conservative nutrient-solution operating bands.  An AI image
# observation can select a profile, but it never sends a relay command itself.
GROWTH_STAGE_PROFILES = {
    "육묘기": {"ec_low": 1.0, "ec_target": 1.3, "ec_high": 1.5, "ph_low": 5.8, "ph_target": 6.0, "ph_high": 6.2, "temp_low": 15.0, "temp_target": 19.0, "temp_high": 22.0, "humidity_low": 60.0, "humidity_target": 68.0, "humidity_high": 75.0},
    "활착기": {"ec_low": 1.3, "ec_target": 1.5, "ec_high": 1.8, "ph_low": 5.8, "ph_target": 6.0, "ph_high": 6.3, "temp_low": 16.0, "temp_target": 20.0, "temp_high": 24.0, "humidity_low": 60.0, "humidity_target": 68.0, "humidity_high": 75.0},
    "생육기": {"ec_low": 1.8, "ec_target": 2.2, "ec_high": 2.6, "ph_low": 5.9, "ph_target": 6.1, "ph_high": 6.4, "temp_low": 16.0, "temp_target": 20.0, "temp_high": 24.0, "humidity_low": 55.0, "humidity_target": 65.0, "humidity_high": 72.0},
    "수확전": {"ec_low": 2.5, "ec_target": 3.0, "ec_high": 3.5, "ph_low": 6.0, "ph_target": 6.2, "ph_high": 6.6, "temp_low": 14.0, "temp_target": 18.0, "temp_high": 22.0, "humidity_low": 55.0, "humidity_target": 62.0, "humidity_high": 70.0},
}
if DEFAULT_GROWTH_STAGE not in GROWTH_STAGE_PROFILES:
    DEFAULT_GROWTH_STAGE = "육묘기"

ACTUATORS = {
    "led": {"label": "LED", "max_seconds": 57600},
    "raw_water": {"label": "원수", "max_seconds": 60},
    "supply": {"label": "양액 공급 (24시간 순환)", "max_seconds": 86400},
    "mixing": {"label": "교반", "max_seconds": 300},
    "ec": {"label": "A+B 양액펌프", "max_seconds": 10},
    "ph": {"label": "pH 산성액펌프", "max_seconds": 5},
    "fan": {"label": "환풍기", "max_seconds": 1800},
}

store = Store(DB_PATH)
security = HTTPBasic(auto_error=False)
stop_event = threading.Event()
serial_lock = threading.Lock()
state_lock = threading.Lock()
serial_connection: serial.Serial | None = None
mqtt_connection: mqtt.Client | None = None
mqtt_sequence = 0
scheduler: BackgroundScheduler | None = None
telegram_thread: threading.Thread | None = None
recommendation_lock = threading.Lock()
nutrient_session_lock = threading.Lock()
nutrient_session_cancel = threading.Event()
nutrient_session_state: dict[str, Any] = {"actuator": None, "operator": None}
word_chain_lock = threading.Lock()
# This is intentionally an in-memory, non-farm feature.  A dashboard restart
# simply ends a game; it never changes a sensor, recommendation, or relay.
word_chain_games: dict[str, dict[str, Any]] = {}
WORD_CHAIN_WORDS = (
    # Each group deliberately joins a longer loop.  The game only selects
    # words with further continuations, so it never sends a one-shot word.
    "토마토", "토끼", "끼니", "니트", "트럭", "럭비", "비누", "비행기", "기차", "차표",
    "표범", "범고래", "래퍼", "퍼즐", "즐거움", "음악", "악기",
    "사과", "과자", "자전거", "자동차", "거울", "울타리", "울음", "리본", "본드", "드라마", "마차",
    "가방", "방울", "가구", "구두", "두부", "부엌", "억새", "새우", "우리",
    "나비", "나무", "누나", "누룽지", "무지개", "개나리", "지우개",
    "바다", "바나나", "다리", "도서관", "관람차", "소나무", "수박", "박물관",
    "아기", "아침", "우산", "산책", "책상", "상자", "여우", "오리", "유리",
    "카메라", "코끼리", "라디오", "마음", "모자", "파도", "피아노", "노래",
    "하마", "호랑이", "이야기", "이불", "불꽃", "꽃병", "병원", "원숭이",
)
HANGUL_WORD_RE = re.compile(r"^[가-힣]{2,20}$")

runtime_state: dict[str, Any] = {
    "pico_connected": False,
    "port": None,
    "last_error": "Pico USB data waiting",
    "updated_at_epoch": None,
    "actuators": {name: "off" for name in ACTUATORS},
    "last_ack": None,
    "sensor_errors": {},
    "mqtt_connected": False,
    "mqtt_error": None,
    "mqtt_topic": None,
    "led_schedule_error": None,
    "led_schedule_last_run": None,
    "supply_circulation_error": None,
    "supply_circulation_last_run": None,
    "telegram_polling": False,
    "telegram_error": None,
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


class OpenAISettingsRequest(BaseModel):
    api_key: str | None = Field(default=None, max_length=300)
    model: str = Field(min_length=2, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")


class CameraSettingsItem(BaseModel):
    slot: int = Field(ge=1, le=4)
    label: str = Field(default="", max_length=80)
    snapshot_url: str = Field(default="", max_length=500)
    username: str = Field(default="", max_length=100)
    password: str | None = Field(default=None, max_length=200)


class CameraSettingsRequest(BaseModel):
    cameras: list[CameraSettingsItem] = Field(min_length=1, max_length=4)


class LedScheduleRequest(BaseModel):
    enabled: bool
    on_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    off_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class TelegramSettingsRequest(BaseModel):
    bot_token: str | None = Field(default=None, max_length=300)
    chat_id: str | None = Field(default=None, max_length=30)
    approver_user_ids: str | None = Field(default=None, max_length=300)
    daily_enabled: bool = False
    approval_enabled: bool = False
    allow_group_members: bool = False


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


def require_local_settings(request: Request) -> None:
    host = request.client.host if request.client else None
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(403, "Settings can only be changed on the server laptop")


def load_serial_config() -> tuple[str, int]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing {CONFIG_PATH.name}")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    port = config.get("serial_port")
    if not port or port == "COM_PORT_HERE":
        raise ValueError("Set serial_port in config.school.json")
    return str(port), int(config.get("serial_baudrate", 115200))


def load_mqtt_config() -> dict[str, Any]:
    default_path = ROOT / ("config.home.json" if MQTT_SUBSCRIBE_ENABLED else "config.school.json")
    path = Path(os.getenv("SMARTFARM_MQTT_CONFIG", default_path))
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise FileNotFoundError(f"Missing {path.name}")
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    topic = (config.get("topics") or {}).get("telemetry")
    if not config.get("mqtt_broker") or not topic:
        raise ValueError(f"Invalid MQTT broker or telemetry topic in {path.name}")
    return {
        **config,
        "mqtt_port": int(config.get("mqtt_port", 1883)),
        "telemetry_topic": str(topic),
    }


def make_mqtt_client(config: dict[str, Any]) -> mqtt.Client:
    if MQTT_SUBSCRIBE_ENABLED:
        prefix = config.get("mqtt_subscriber_client_id_prefix", "smartfarm_dashboard_subscriber")
        client_id = f"{prefix}_{secrets.token_hex(4)}"
    else:
        client_id = str(config.get("mqtt_client_id", "smartfarm_dashboard_publisher"))
    if hasattr(mqtt, "CallbackAPIVersion"):
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
    else:
        client = mqtt.Client(client_id=client_id)
    client.user_data_set({"topic": config["telemetry_topic"]})
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    return client


def mqtt_sensor_payload(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Return sensor-only telemetry; never expose commands, secrets or camera data."""
    return {
        "type": "telemetry",
        "site_id": config.get("site_id"),
        "zone_id": config.get("zone_id"),
        "device_id": config.get("device_id"),
        "bridge_id": config.get("bridge_id", config.get("mqtt_client_id")),
        "air_temp": payload.get("air_temp"),
        "temp_c": payload.get("air_temp"),
        "humidity": payload.get("humidity"),
        "rh": payload.get("humidity"),
        "co2": payload.get("co2"),
        "co2_ppm": payload.get("co2"),
        "scd40_temp": payload.get("scd40_temp"),
        "scd40_humidity": payload.get("scd40_humidity"),
        "lux": payload.get("lux"),
        "ec": payload.get("ec"),
        "ph": payload.get("ph"),
        "solution_temp": payload.get("solution_temp"),
        "solution_temp_c": payload.get("solution_temp"),
        "sensor_errors": payload.get("sensor_errors") or {},
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def mqtt_to_sensor_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "air_temp": payload.get("air_temp", payload.get("temp_c")),
        "humidity": payload.get("humidity", payload.get("rh")),
        "co2": payload.get("co2", payload.get("co2_ppm")),
        "scd40_temp": payload.get("scd40_temp"),
        "scd40_humidity": payload.get("scd40_humidity"),
        "lux": payload.get("lux"),
        "ec": payload.get("ec"),
        "ph": payload.get("ph"),
        "solution_temp": payload.get("solution_temp", payload.get("solution_temp_c")),
        "sensor_errors": payload.get("sensor_errors") or {},
        "mqtt_ts": payload.get("ts"),
    }


def on_mqtt_connect(
    client: mqtt.Client,
    userdata: Any,
    flags: Any,
    reason_code: Any,
    properties: Any = None,
) -> None:
    del flags, properties
    if reason_code != 0:
        update_runtime(mqtt_connected=False, mqtt_error=f"MQTT connect failed: {reason_code}")
        return
    topic = userdata["topic"]
    update_runtime(mqtt_connected=True, mqtt_error=None, mqtt_topic=topic)
    if MQTT_SUBSCRIBE_ENABLED:
        client.subscribe(topic, qos=0)


def on_mqtt_disconnect(
    client: mqtt.Client,
    userdata: Any,
    disconnect_flags: Any,
    reason_code: Any,
    properties: Any = None,
) -> None:
    del client, userdata, disconnect_flags, properties
    values: dict[str, Any] = {
        "mqtt_connected": False,
        "mqtt_error": f"MQTT disconnected: {reason_code}",
    }
    if MQTT_SUBSCRIBE_ENABLED:
        values.update(pico_connected=False, last_error="MQTT connection lost")
    update_runtime(**values)


def on_mqtt_message(client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
    del client, userdata
    try:
        payload = json.loads(message.payload.decode("utf-8"))
        if payload.get("type") != "telemetry":
            return
        sensor = mqtt_to_sensor_payload(payload)
        store.add_sensor(sensor, "measured:mqtt")
        sensor_errors = sensor["sensor_errors"]
        update_runtime(
            pico_connected=True,
            port="MQTT",
            last_error="; ".join(
                f"{name}: {error}" for name, error in sensor_errors.items()
            ) or None,
            updated_at_epoch=time.time(),
            sensor_errors=sensor_errors,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        update_runtime(mqtt_error=f"Invalid MQTT telemetry: {error}")


def start_mqtt() -> None:
    global mqtt_connection
    if not (MQTT_PUBLISH_ENABLED or MQTT_SUBSCRIBE_ENABLED):
        return
    if MQTT_PUBLISH_ENABLED and MQTT_SUBSCRIBE_ENABLED:
        raise RuntimeError("Enable only one MQTT dashboard mode")
    config = load_mqtt_config()
    client = make_mqtt_client(config)
    client.on_connect = on_mqtt_connect
    client.on_disconnect = on_mqtt_disconnect
    if MQTT_SUBSCRIBE_ENABLED:
        client.on_message = on_mqtt_message
    mqtt_connection = client
    values: dict[str, Any] = {"mqtt_topic": config["telemetry_topic"]}
    if MQTT_SUBSCRIBE_ENABLED:
        values.update(port="MQTT", last_error="Waiting for school MQTT telemetry")
    update_runtime(**values)
    client.connect_async(config["mqtt_broker"], config["mqtt_port"], keepalive=60)
    client.loop_start()


def stop_mqtt() -> None:
    global mqtt_connection
    client = mqtt_connection
    mqtt_connection = None
    if client is None:
        return
    client.disconnect()
    client.loop_stop()
    update_runtime(mqtt_connected=False)


def publish_mqtt_sensor(payload: dict[str, Any]) -> None:
    global mqtt_sequence
    if not MQTT_PUBLISH_ENABLED or mqtt_connection is None:
        return
    try:
        config = load_mqtt_config()
        mqtt_sequence += 1
        message = mqtt_sensor_payload(payload, config)
        message["seq"] = mqtt_sequence
        result = mqtt_connection.publish(
            config["telemetry_topic"],
            json.dumps(message, ensure_ascii=False),
            qos=0,
            retain=False,
        )
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            update_runtime(mqtt_error=f"MQTT publish failed: {result.rc}")
    except (FileNotFoundError, ValueError, OSError) as error:
        update_runtime(mqtt_error=f"MQTT publish failed: {error}")


def update_runtime(**values: Any) -> None:
    with state_lock:
        runtime_state.update(values)


def env_file_value(value: str) -> str:
    if any(character in value for character in " #\t\"'"):
        return json.dumps(value, ensure_ascii=False)
    return value


def update_env_file(values: dict[str, str]) -> None:
    """Persist server-only settings without returning secrets to the browser."""
    env_path = ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    remaining = dict(values)
    updated: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in remaining:
            updated.append(f"{key}={env_file_value(remaining.pop(key))}")
        else:
            updated.append(line)
    if remaining and updated and updated[-1] != "":
        updated.append("")
    updated.extend(f"{key}={env_file_value(value)}" for key, value in remaining.items())
    temporary = env_path.with_name(".env.tmp")
    temporary.write_text("\n".join(updated) + "\n", encoding="utf-8")
    temporary.replace(env_path)
    os.environ.update(values)


def telegram_approver_ids(value: str | None = None) -> set[int]:
    """Return approved Telegram user IDs, failing closed on malformed values."""
    raw = (value if value is not None else os.getenv("TELEGRAM_APPROVER_USER_IDS", "")).strip()
    if not raw:
        return set()
    parts = [part.strip() for part in re.split(r"[\s,]+", raw) if part.strip()]
    if not all(re.fullmatch(r"\d{4,20}", part) for part in parts):
        raise ValueError("Approver user IDs must be comma-separated positive numeric Telegram IDs")
    return {int(part) for part in parts}


def telegram_config() -> dict[str, Any]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    try:
        approvers = telegram_approver_ids()
        config_error = None
    except ValueError as error:
        approvers = set()
        config_error = str(error)
    daily_enabled = os.getenv("SMARTFARM_TELEGRAM_DAILY_ENABLED", "0") == "1"
    approval_enabled = os.getenv("SMARTFARM_TELEGRAM_APPROVAL_ENABLED", "0") == "1"
    allow_group_members = os.getenv("SMARTFARM_TELEGRAM_ALLOW_GROUP_MEMBERS", "0") == "1"
    return {
        "token": token,
        "chat_id": chat_id,
        "approvers": approvers,
        "daily_enabled": daily_enabled,
        "approval_enabled": approval_enabled,
        "allow_group_members": allow_group_members,
        "config_error": config_error,
        "configured": bool(token and chat_id),
        "approvals_ready": bool(token and chat_id and (approvers or allow_group_members) and approval_enabled and not config_error),
    }


def telegram_settings_payload() -> dict[str, Any]:
    config = telegram_config()
    return {
        "configured": config["configured"],
        "bot_token_saved": bool(config["token"]),
        "chat_id_saved": bool(config["chat_id"]),
        "approver_count": len(config["approvers"]),
        "daily_enabled": config["daily_enabled"],
        "approval_enabled": config["approval_enabled"],
        "allow_group_members": config["allow_group_members"],
        "approvals_ready": config["approvals_ready"],
        "config_error": config["config_error"],
        "polling": bool(runtime_state.get("telegram_polling")),
        "last_error": runtime_state.get("telegram_error"),
        "timezone": "Asia/Seoul",
    }


def telegram_bot_api(method: str, *, data: dict[str, Any] | None = None,
                     files: dict[str, Any] | None = None, timeout: int = 35) -> Any:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Telegram bot token is not configured")
    response = requests.post(
        f"https://api.telegram.org/bot{token}/{method}",
        data=data, files=files, timeout=timeout,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if not response.ok or not isinstance(payload, dict) or not payload.get("ok"):
        detail = payload.get("description") if isinstance(payload, dict) else response.text[:160]
        raise RuntimeError(f"Telegram {method} failed: {detail or response.status_code}")
    return payload.get("result")


def telegram_api(method: str, *, data: dict[str, Any] | None = None,
                 files: dict[str, Any] | None = None, timeout: int = 35) -> Any:
    if not telegram_config()["configured"]:
        raise RuntimeError("Telegram bot token and chat ID are not configured")
    return telegram_bot_api(method, data=data, files=files, timeout=timeout)


def telegram_group_member_allowed(chat_id: str, user_id: int) -> bool:
    """Verify live membership for group-wide approval; bot admin access is required by Telegram."""
    result = telegram_bot_api(
        "getChatMember",
        data={"chat_id": chat_id, "user_id": str(user_id)},
        timeout=15,
    )
    if not isinstance(result, dict):
        return False
    status = result.get("status")
    return status in {"creator", "administrator", "member"} or (
        status == "restricted" and bool(result.get("is_member"))
    )


def telegram_send_message(text: str, reply_markup: dict[str, Any] | None = None) -> Any:
    config = telegram_config()
    data: dict[str, Any] = {"chat_id": config["chat_id"], "text": text[:4096]}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    return telegram_api("sendMessage", data=data)


def telegram_send_photo(path: Path, caption: str, reply_markup: dict[str, Any] | None = None) -> Any:
    config = telegram_config()
    data: dict[str, Any] = {"chat_id": config["chat_id"], "caption": caption[:1024]}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    with path.open("rb") as photo:
        return telegram_api("sendPhoto", data=data, files={"photo": photo})


def telegram_command_name(text: str) -> str:
    """Normalize Telegram commands with or without the @bot suffix."""
    first = (text or "").strip().split(maxsplit=1)[0].lower()
    return first.split("@", 1)[0]


def telegram_command_argument(text: str) -> str:
    """Return the optional words after a Telegram command."""
    parts = (text or "").strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else ""


def word_chain_has_path(start_character: str, used: set[str], depth: int) -> bool:
    """Return whether the curated dictionary can continue for ``depth`` more turns."""
    if depth <= 0:
        return True
    for word in WORD_CHAIN_WORDS:
        if word.startswith(start_character) and word not in used:
            if word_chain_has_path(word[-1], used | {word}, depth - 1):
                return True
    return False


def word_chain_next_word(last_character: str, used: set[str]) -> str | None:
    """Choose the trickiest word that still leaves at least two more safe turns."""
    candidates = [
        word for word in WORD_CHAIN_WORDS
        if word.startswith(last_character)
        and word not in used
        and word_chain_has_path(word[-1], used | {word}, 2)
    ]
    if not candidates:
        return None

    def difficulty(word: str) -> tuple[int, int, str]:
        next_turns = sum(
            1 for next_word in WORD_CHAIN_WORDS
            if next_word.startswith(word[-1])
            and next_word not in used | {word}
            and word_chain_has_path(next_word[-1], used | {word, next_word}, 1)
        )
        return (next_turns, -len(word), word)

    return min(candidates, key=difficulty)


def word_chain_start(chat_id: str, opening_word: str = "") -> str:
    """Start a chat-local Korean word-chain game without touching farm state."""
    opening_word = opening_word.strip()
    if opening_word and not HANGUL_WORD_RE.fullmatch(opening_word):
        return "끝말잇기는 한글 단어 2~20글자로 시작해 주세요. 예: /끝말잇기 사과"
    with word_chain_lock:
        used: set[str] = set()
        if opening_word:
            used.add(opening_word)
            bot_word = word_chain_next_word(opening_word[-1], used)
            if not bot_word:
                return f"‘{opening_word[-1]}’로 시작하는 준비 단어가 없어요. 다른 단어로 시작해 주세요."
            used.add(bot_word)
            word_chain_games[chat_id] = {"expected": bot_word[-1], "used": used}
            return f"🎮 끝말잇기 시작!\n나: {opening_word}\n봇: {bot_word}\n\n다음은 ‘{bot_word[-1]}’로 시작하는 단어예요."

        bot_word = "토마토"
        word_chain_games[chat_id] = {"expected": bot_word[-1], "used": {bot_word}}
        return f"🎮 끝말잇기 시작!\n봇이 먼저: {bot_word}\n\n‘{bot_word[-1]}’로 시작하는 단어를 보내 주세요."


def word_chain_play(chat_id: str, word: str) -> str | None:
    """Process one player turn and return a safe text response, if a game exists."""
    word = word.strip()
    with word_chain_lock:
        game = word_chain_games.get(chat_id)
        if not game:
            return None
        expected = str(game["expected"])
        used = set(game["used"])
        if not HANGUL_WORD_RE.fullmatch(word):
            return "한글 단어 2~20글자를 보내 주세요. 그만두려면 /끝말그만"
        if not word.startswith(expected):
            return f"‘{expected}’로 시작하는 단어 차례예요."
        if word in used:
            return f"‘{word}’은(는) 이미 나온 단어예요. 다른 ‘{expected}’ 단어를 골라 주세요."
        bot_word = word_chain_next_word(word[-1], used | {word})
        if not bot_word:
            return (
                f"‘{word}’은(는) 한방단어라 사용할 수 없어요.\n"
                f"상대가 계속 이을 수 있는 다른 ‘{expected}’ 단어를 골라 주세요."
            )
        used.add(word)
        used.add(bot_word)
        word_chain_games[chat_id] = {"expected": bot_word[-1], "used": used}
        return f"봇: {bot_word}\n\n다음은 ‘{bot_word[-1]}’로 시작하는 단어예요."


def word_chain_stop(chat_id: str) -> str:
    with word_chain_lock:
        existed = word_chain_games.pop(chat_id, None) is not None
    return "🎮 끝말잇기를 종료했어요." if existed else "진행 중인 끝말잇기가 없어요."


def telegram_status_text() -> str:
    """A concise, measured status response for an authorized Telegram command."""
    latest = latest_with_health()
    with state_lock:
        actuators = dict(runtime_state["actuators"])
    pending = [item for item in store.recommendations(50) if item.get("status") == "pending"]
    pending_labels = [
        f"#{item['id']} {ACTUATORS.get(str(item.get('actuator')), {}).get('label', item.get('actuator') or '현장 확인')}"
        for item in pending[:4]
    ]
    sensor_note = "정상" if latest.get("pe350_connected") else "PE350 데이터 확인 필요"
    if latest.get("sensor_errors"):
        sensor_note += " · 일부 센서 오류"
    analysis_row = (store.analyses(1) or [{}])[0]
    analysis = dict(analysis_row.get("result") or {})
    stage, profile = growth_stage_profile(analysis)
    return (
        "🥦 브로콜리 현재 상태\n"
        f"🕛 {datetime.now(SEOUL).strftime('%Y-%m-%d %H:%M')} KST\n\n"
        f"🧪 EC {latest.get('ec', '--')} dS/m · pH {latest.get('ph', '--')} · 양액 {latest.get('solution_temp', '--')}°C\n"
        f"🌱 단계: {stage} · 목표 EC {profile['ec_target']:.1f} · pH {profile['ph_target']:.1f}\n"
        f"🌡 공기 {latest.get('air_temp', '--')}°C · 습도 {latest.get('humidity', '--')}%\n"
        f"🔄 공급 펌프: {str(actuators.get('supply', 'unknown')).upper()} (24시간 순환)\n"
        f"⚙️ 교반 {str(actuators.get('mixing', 'unknown')).upper()} · EC {str(actuators.get('ec', 'unknown')).upper()} · pH {str(actuators.get('ph', 'unknown')).upper()}\n"
        f"📡 센서: {sensor_note}\n"
        f"📋 승인 대기: {', '.join(pending_labels) if pending_labels else '없음'}\n\n"
        "pH/EC 제안은 버튼으로 승인해야만 실행됩니다."
    )


def telegram_message_authorized(message: dict[str, Any], config: dict[str, Any]) -> bool:
    chat_id = str((message.get("chat") or {}).get("id", ""))
    user_id = int((message.get("from") or {}).get("id"))
    if chat_id != config["chat_id"]:
        return False
    return user_id in config["approvers"] or (
        config["allow_group_members"] and telegram_group_member_allowed(chat_id, user_id)
    )


def process_telegram_message(message: dict[str, Any]) -> None:
    """Handle Telegram commands and the isolated, non-farm word-chain game."""
    try:
        text = str(message.get("text") or "")
        command = telegram_command_name(text)
        chat_id = str((message.get("chat") or {}).get("id", ""))
        with word_chain_lock:
            game_active = chat_id in word_chain_games
        game_commands = {"/끝말잇기", "/wordchain", "/끝말그만", "/endgame"}
        farm_commands = {"/start", "/status", "/report", "/stop", "/help", "/commands"}
        if command not in farm_commands | game_commands and not game_active:
            return
        config = telegram_config()
        if not config["approvals_ready"] or not telegram_message_authorized(message, config):
            return
        if command in {"/끝말잇기", "/wordchain"}:
            telegram_send_message(word_chain_start(chat_id, telegram_command_argument(text)))
            return
        if command in {"/끝말그만", "/endgame"}:
            telegram_send_message(word_chain_stop(chat_id))
            return
        if command in {"/help", "/commands"}:
            telegram_send_message(
                "🥦 브로콜리봇 명령어\n\n"
                "/start · 봇 연결 및 현재 상태\n"
                "/status · 현재 센서·펌프·승인 대기 상태\n"
                "/report · 최신 촬영, AI 분석, 사진 브리핑, PDF 보고서 생성\n"
                "/stop · 진행 중 EC/pH 반복 보정과 교반 즉시 중지\n"
                "/끝말잇기 [단어] 또는 /wordchain [단어] · 끝말잇기 시작\n"
                "/끝말그만 또는 /endgame · 끝말잇기 종료\n"
                "/help 또는 /commands · 이 명령어 목록\n\n"
                "EC/pH 펌프는 Telegram 승인 버튼을 누른 경우에만 동작합니다."
            )
        elif command == "/start":
            telegram_send_message(
                "🥦 브로콜리봇 연결 완료\n"
                "현재 상태는 아래와 같습니다.\n\n" + telegram_status_text()
            )
        elif command == "/report":
            telegram_send_message("📄 최신 사진·AI 분석·PDF 보고서를 준비합니다. 완료되면 이 채팅에 보냅니다.")
            threading.Thread(
                target=telegram_daily_brief_job,
                kwargs={"force": True}, daemon=True, name="telegram-start-brief",
            ).start()
        elif command == "/stop":
            telegram_send_message("🛑 " + cancel_nutrient_feedback(f"telegram:{(message.get('from') or {}).get('id')}"))
        elif game_active:
            response = word_chain_play(chat_id, text)
            if response:
                telegram_send_message(response)
        else:
            telegram_send_message(telegram_status_text())
    except (TypeError, ValueError, RuntimeError) as error:
        update_runtime(telegram_error=f"status command: {type(error).__name__}: {str(error)[:160]}")


def time_minutes(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def photoperiod_minutes(on_time: str, off_time: str) -> int:
    duration = (time_minutes(off_time) - time_minutes(on_time)) % (24 * 60)
    if duration == 0:
        raise ValueError("LED on and off times must be different")
    if duration > 16 * 60:
        raise ValueError("LED photoperiod cannot exceed 16 hours")
    return duration


def led_should_be_on(on_time: str, off_time: str, now: datetime) -> bool:
    current = now.hour * 60 + now.minute
    on_minute = time_minutes(on_time)
    off_minute = time_minutes(off_time)
    if on_minute < off_minute:
        return on_minute <= current < off_minute
    return current >= on_minute or current < off_minute


def led_seconds_until_off(off_time: str, now: datetime) -> int:
    off_hour, off_minute = (int(part) for part in off_time.split(":"))
    target = now.replace(hour=off_hour, minute=off_minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return max(1, min(16 * 60 * 60, int((target - now).total_seconds())))


def led_schedule_config() -> dict[str, Any]:
    enabled = store.setting("led_schedule_enabled", "0") == "1"
    on_time = store.setting("led_schedule_on_time", "06:00") or "06:00"
    off_time = store.setting("led_schedule_off_time", "22:00") or "22:00"
    now = datetime.now(SEOUL)
    with state_lock:
        current_state = runtime_state["actuators"].get("led", "unknown")
        last_error = runtime_state.get("led_schedule_error")
        last_run = runtime_state.get("led_schedule_last_run")
    return {
        "enabled": enabled,
        "on_time": on_time,
        "off_time": off_time,
        "timezone": "Asia/Seoul",
        "photoperiod_hours": round(photoperiod_minutes(on_time, off_time) / 60, 2),
        "desired_state": "on" if enabled and led_should_be_on(on_time, off_time, now) else "off",
        "current_state": current_state,
        "hardware_enabled": LED_SCHEDULE_HARDWARE_ENABLED,
        "last_error": last_error,
        "last_run": last_run,
    }


def reconcile_led_schedule(force: bool = False) -> dict[str, Any]:
    config = led_schedule_config()
    desired = config["desired_state"]
    now = datetime.now(SEOUL)
    if not LED_SCHEDULE_HARDWARE_ENABLED:
        update_runtime(led_schedule_error="LED schedule hardware output is disabled")
        return {**led_schedule_config(), "result": "blocked"}
    with state_lock:
        connected = bool(runtime_state["pico_connected"])
        current = runtime_state["actuators"].get("led", "unknown")
    if not connected:
        update_runtime(led_schedule_error="Pico USB is offline")
        return {**led_schedule_config(), "result": "offline"}
    if current == desired and not force:
        update_runtime(led_schedule_error=None)
        return {**config, "result": "unchanged"}
    duration = led_seconds_until_off(config["off_time"], now) if desired == "on" else 0
    command_id = secrets.token_hex(8)
    command = {
        "cmd_id": command_id,
        "action": "set",
        "actuator": "led",
        "state": desired,
        "duration_seconds": duration,
    }
    try:
        send_pico_command(command)
        timestamp = now.isoformat(timespec="seconds")
        update_runtime(led_schedule_error=None, led_schedule_last_run=timestamp)
        store.add_event({
            "command_id": command_id,
            "actuator": "led",
            "requested_state": desired,
            "duration_seconds": duration,
            "source": "fixed_led_schedule",
            "result": "sent",
            "note": f"{config['on_time']}-{config['off_time']} Asia/Seoul",
        })
        store.workflow("led_photoperiod", "success", f"LED {desired}; {config['on_time']}-{config['off_time']}")
        return {**led_schedule_config(), "result": "sent"}
    except (RuntimeError, serial.SerialException, OSError) as error:
        message = str(error)
        update_runtime(led_schedule_error=message)
        store.add_event({
            "command_id": command_id,
            "actuator": "led",
            "requested_state": desired,
            "duration_seconds": duration,
            "source": "fixed_led_schedule",
            "result": "failed",
            "note": message,
        })
        store.workflow("led_photoperiod", "failed", message)
        return {**led_schedule_config(), "result": "failed"}


def reconcile_supply_circulation(force: bool = False) -> dict[str, Any]:
    """Keep the nutrient delivery pump running continuously, including after reconnects."""
    with state_lock:
        connected = bool(runtime_state["pico_connected"])
        current = runtime_state["actuators"].get("supply", "unknown")
    status = {
        "enabled": SUPPLY_CONTINUOUS_ENABLED,
        "current_state": current,
        "desired_state": "on" if SUPPLY_CONTINUOUS_ENABLED else "off",
    }
    if not SUPPLY_CONTINUOUS_ENABLED:
        return {**status, "result": "disabled"}
    if not CONTROL_ENABLED or MQTT_SUBSCRIBE_ENABLED:
        message = "Continuous supply requires local hardware control"
        update_runtime(supply_circulation_error=message)
        return {**status, "result": "blocked", "error": message}
    if not connected:
        message = "Pico USB is offline"
        update_runtime(supply_circulation_error=message)
        return {**status, "result": "offline", "error": message}
    if current == "on" and not force:
        update_runtime(supply_circulation_error=None)
        return {**status, "result": "unchanged"}
    command_id = secrets.token_hex(8)
    command = {
        "cmd_id": command_id, "action": "set", "actuator": "supply",
        "state": "on", "duration_seconds": 86400,
    }
    try:
        send_pico_command(command)
        timestamp = datetime.now(SEOUL).isoformat(timespec="seconds")
        update_runtime(supply_circulation_error=None, supply_circulation_last_run=timestamp)
        store.add_event({
            "command_id": command_id, "actuator": "supply",
            "requested_state": "on", "duration_seconds": 86400,
            "source": "continuous_supply", "result": "sent",
            "note": "24시간 양액 순환 유지",
        })
        return {**status, "result": "sent"}
    except (RuntimeError, serial.SerialException, OSError) as error:
        message = str(error)
        update_runtime(supply_circulation_error=message)
        store.add_event({
            "command_id": command_id, "actuator": "supply",
            "requested_state": "on", "duration_seconds": 86400,
            "source": "continuous_supply", "result": "failed", "note": message,
        })
        return {**status, "result": "failed", "error": message}


def start_pico_runtime(pico: serial.Serial) -> None:
    pico.write(b"\r\x03\x03\x02")
    time.sleep(0.5)
    pico.reset_input_buffer()
    pico.write(b"exec(open('smartfarm_runtime.py').read())\r\n")


def process_serial_line(line: str) -> None:
    if line.startswith("TELEMETRY_JSON:"):
        payload = json.loads(line.split(":", 1)[1])
        store.add_sensor(payload, "measured:pico_usb")
        publish_mqtt_sensor(payload)
        sensor_errors = payload.get("sensor_errors") or {}
        update_runtime(
            pico_connected=True,
            last_error="; ".join(
                f"{name}: {message}" for name, message in sensor_errors.items()
            ) or None,
            updated_at_epoch=time.time(),
            actuators=payload.get("actuators", runtime_state["actuators"]),
            sensor_errors=sensor_errors,
        )
    elif line.startswith("ACK_JSON:"):
        ack = json.loads(line.split(":", 1)[1])
        update_runtime(last_ack=ack)
        actuator = ack.get("actuator")
        state = ack.get("state")
        if actuator in ACTUATORS and state in ("on", "off"):
            result = "pico_ack" if ack.get("result") == "ok" else "pico_timeout" if ack.get("result") == "timeout_off" else "pico_error"
            command_id = str(ack.get("cmd_id") or f"pico:{actuator}:{int(time.time())}")
            store.add_event({
                "command_id": command_id,
                "actuator": actuator,
                "requested_state": state,
                "duration_seconds": 0,
                "source": "pico_ack",
                "result": result,
                "note": "Pico 응답: " + str(ack.get("result", "unknown")),
            })
    elif line.startswith("TELEMETRY_ERROR:"):
        payload = json.loads(line.split(":", 1)[1])
        update_runtime(last_error=payload.get("error", "Pico telemetry error"))


def serial_worker() -> None:
    global serial_connection
    while not stop_event.is_set():
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
        except (FileNotFoundError, ValueError, serial.SerialException, OSError) as error:
            update_runtime(pico_connected=False, last_error=str(error))
        finally:
            with serial_lock:
                serial_connection = None
        stop_event.wait(3)


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


def latest_with_health() -> dict[str, Any]:
    latest = store.latest_sensor() or {}
    if latest:
        record_is_simulation = str(latest.get("source", "")).startswith("simulation:")
        if record_is_simulation != SIMULATION:
            latest = {}
    with state_lock:
        runtime = dict(runtime_state)
    epoch = runtime.get("updated_at_epoch")
    age = round(time.time() - epoch, 1) if epoch else None
    connected = bool(runtime["pico_connected"] and age is not None and age <= SENSOR_STALE_SECONDS)
    sensor_errors = dict(runtime.get("sensor_errors") or {})
    if latest.get("raw_json"):
        try:
            raw_payload = json.loads(latest["raw_json"])
            sensor_errors = dict(raw_payload.get("sensor_errors") or sensor_errors)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    aht10_connected = bool(
        connected and latest.get("air_temp") is not None and latest.get("humidity") is not None
    )
    scd40_connected = bool(connected and latest.get("co2") is not None)
    pe350_connected = bool(
        connected
        and latest.get("ec") is not None
        and latest.get("ph") is not None
        and latest.get("solution_temp") is not None
    )
    sensor_control_ready = aht10_connected and pe350_connected and (
        scd40_connected or not SCD40_REQUIRED
    )
    i2c_errors = "; ".join(
        f"{name}: {sensor_errors[name]}"
        for name in ("aht10", "scd40")
        if name in sensor_errors and (name != "scd40" or SCD40_REQUIRED)
    ) or None
    return {
        **latest,
        "pico_connected": connected,
        "port": runtime["port"],
        "age_seconds": age,
        "error": runtime["last_error"],
        "actuators": runtime["actuators"],
        "simulation": SIMULATION,
        "mqtt_mode": MQTT_MODE,
        "sensor_errors": sensor_errors,
        "aht10_connected": aht10_connected,
        "scd40_connected": scd40_connected,
        "scd40_required": SCD40_REQUIRED,
        "pe350_connected": pe350_connected,
        "sensor_control_ready": sensor_control_ready,
        "i2c_connected": aht10_connected or scd40_connected,
        "i2c_age_seconds": age,
        "i2c_error": i2c_errors,
        "pe350_age_seconds": age,
        "pe350_error": sensor_errors.get("pe350"),
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


def add_actuator_recommendation(item: dict[str, Any]) -> int:
    """Create an approval request and its immutable first audit entry together."""
    recommendation_id = store.add_recommendation(item)
    actuator = item.get("actuator")
    if actuator in ACTUATORS:
        store.add_event({
            "command_id": f"request:{recommendation_id}",
            "actuator": actuator,
            "requested_state": str(item.get("requested_state") or "off"),
            "duration_seconds": int(item.get("duration_seconds") or 0),
            "source": f"proposal:{item.get('source', 'unknown')}",
            "result": "requested",
            "note": str(item.get("rationale") or item.get("title") or "제어 요청"),
        })
    return recommendation_id


def record_decision_event(item: dict[str, Any], recommendation_id: int, result: str, operator: str, note: str) -> None:
    actuator = item.get("actuator")
    if actuator not in ACTUATORS:
        return
    store.add_event({
        "command_id": f"request:{recommendation_id}",
        "actuator": actuator,
        "requested_state": str(item.get("requested_state") or "off"),
        "duration_seconds": int(item.get("duration_seconds") or 0),
        "source": f"decision:{operator}",
        "result": result,
        "note": note or "사람 결정 기록",
    })


def growth_stage_profile(analysis: dict[str, Any] | None = None) -> tuple[str, dict[str, float]]:
    """Use a validated AI stage, otherwise retain the safe school-configured stage."""
    stage = str((analysis or {}).get("growth_stage") or DEFAULT_GROWTH_STAGE)
    if stage not in GROWTH_STAGE_PROFILES:
        stage = DEFAULT_GROWTH_STAGE
    return stage, dict(GROWTH_STAGE_PROFILES[stage])


def nutrient_target_reached(actuator: str, latest: dict[str, Any], profile: dict[str, Any] | None = None) -> bool:
    """A+B raises EC; the configured pH pump is acid only and lowers pH."""
    profile = profile or growth_stage_profile()[1]
    if actuator == "ec":
        value = latest.get("ec")
        return value is not None and float(value) >= float(profile["ec_target"])
    if actuator == "ph":
        value = latest.get("ph")
        return value is not None and float(profile["ph_low"]) <= float(value) <= float(profile["ph_target"])
    return False


def nutrient_pulse_seconds(actuator: str) -> int:
    return EC_PULSE_SECONDS if actuator == "ec" else PH_PULSE_SECONDS


def nutrient_feedback_policy(actuator: str) -> dict[str, Any]:
    return {
        "pulse_seconds": nutrient_pulse_seconds(actuator),
        "mix_seconds": NUTRIENT_MIX_SECONDS,
        "repeat_until_target": True,
        "telegram_stop_command": "/stop",
    }


def nutrient_request_matches_policy(item: dict[str, Any]) -> bool:
    if item.get("source") != "nutrient_feedback_rule":
        return True
    actuator = str(item.get("actuator") or "")
    return actuator in ("ec", "ph") and item.get("evidence", {}).get("feedback_policy") == nutrient_feedback_policy(actuator)


def nutrient_value_text(actuator: str, latest: dict[str, Any]) -> str:
    if actuator == "ec":
        value = latest.get("ec")
        return f"EC {value if value is not None else '--'} dS/m"
    value = latest.get("ph")
    return f"pH {value if value is not None else '--'}"


def send_session_command(actuator: str, state: str, duration_seconds: int, operator: str, note: str) -> str:
    command_id = secrets.token_hex(8)
    send_pico_command({
        "cmd_id": command_id, "action": "set", "actuator": actuator,
        "state": state, "duration_seconds": duration_seconds,
    })
    store.add_event({
        "command_id": command_id, "actuator": actuator,
        "requested_state": state, "duration_seconds": duration_seconds,
        "source": f"feedback_session:{operator}", "result": "sent", "note": note,
    })
    return command_id


def telegram_session_notice(message: str) -> None:
    try:
        if telegram_config()["configured"]:
            telegram_send_message(message)
    except Exception as error:
        store.workflow("nutrient_feedback_notice", "failed", f"{type(error).__name__}: {str(error)[:180]}")


def close_nutrient_session(item: dict[str, Any], status: str, operator: str, note: str) -> None:
    recommendation_id = item.get("id")
    if isinstance(recommendation_id, int):
        store.decide_recommendation(recommendation_id, status, operator, note)


def wait_for_nutrient_interval(seconds: int) -> str | None:
    """Wait responsively for shutdown or an authorized Telegram /stop command."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if stop_event.is_set():
            return "server"
        if nutrient_session_cancel.wait(min(0.5, max(0.0, deadline - time.monotonic()))):
            return "operator"
    return None


def cancel_nutrient_feedback(operator: str) -> str:
    """Safe stop: cancel the loop and force only chemical/mixing outputs OFF."""
    nutrient_session_cancel.set()
    stopped = []
    for actuator in ("ec", "ph", "mixing"):
        command_id = secrets.token_hex(8)
        try:
            if CONTROL_ENABLED:
                send_pico_command({
                    "cmd_id": command_id, "action": "set", "actuator": actuator,
                    "state": "off", "duration_seconds": 0,
                })
            store.add_event({
                "command_id": command_id, "actuator": actuator, "requested_state": "off",
                "duration_seconds": 0, "source": f"telegram_stop:{operator}",
                "result": "sent" if CONTROL_ENABLED else "simulated",
                "note": "Telegram /stop: 반복 양액 보정 즉시 중단",
            })
            stopped.append(actuator)
        except (RuntimeError, serial.SerialException, OSError) as error:
            store.add_event({
                "command_id": command_id, "actuator": actuator, "requested_state": "off",
                "duration_seconds": 0, "source": f"telegram_stop:{operator}",
                "result": "failed", "note": str(error),
            })
    return "EC·pH·교반 OFF 명령 전송 · 진행 중 보정 취소" if stopped else "보정 취소 요청 기록"


def run_nutrient_feedback_session(item: dict[str, Any], operator: str) -> None:
    """Repeat a human-approved correction to its stage target, with Telegram /stop."""
    actuator = str(item["actuator"])
    label = ACTUATORS[actuator]["label"]
    started_id = f"session:{secrets.token_hex(8)}"
    try:
        nutrient_session_cancel.clear()
        nutrient_session_state.update({"actuator": actuator, "operator": operator})
        store.add_event({
            "command_id": started_id, "actuator": actuator,
            "requested_state": "on", "duration_seconds": nutrient_pulse_seconds(actuator),
            "source": f"feedback_session:{operator}", "result": "session_started",
            "note": "승인된 폐루프 보정 시작 · 목표 범위까지 반복",
        })
        profile = dict((item.get("evidence") or {}).get("growth_profile") or growth_stage_profile()[1])
        stage = str((item.get("evidence") or {}).get("growth_stage") or growth_stage_profile()[0])
        pulse = 0
        while True:
            latest = latest_with_health()
            if not latest.get("pe350_connected"):
                raise RuntimeError("PE350 데이터가 지연되어 보정을 중단함")
            if actuator == "ec" and latest.get("ec") is not None and float(latest["ec"]) > float(profile["ec_high"]):
                note = f"EC 상한 초과 감지: {nutrient_value_text(actuator, latest)} · A+B 추가 주입 차단"
                close_nutrient_session(item, "safety_stopped", operator, note)
                telegram_session_notice(f"⚠️ {label} 보정 안전 중단\n{note}")
                return
            if actuator == "ph" and latest.get("ph") is not None and float(latest["ph"]) < float(profile["ph_low"]):
                note = f"pH 하한 아래 감지: {nutrient_value_text(actuator, latest)} · 산성액 추가 주입 차단"
                close_nutrient_session(item, "safety_stopped", operator, note)
                telegram_session_notice(f"⚠️ {label} 보정 안전 중단\n{note}")
                return
            if nutrient_target_reached(actuator, latest, profile):
                note = f"{stage} 목표값 도달: {nutrient_value_text(actuator, latest)}"
                close_nutrient_session(item, "completed", operator, note)
                telegram_session_notice(f"🥦 {label} 보정 완료\n{note}\n중단하려면 /stop")
                return
            pulse += 1
            before = nutrient_value_text(actuator, latest)
            send_session_command(actuator, "on", nutrient_pulse_seconds(actuator), operator, f"{stage} {pulse}회 보정 · 주입 전 {before}")
            interrupted = wait_for_nutrient_interval(nutrient_pulse_seconds(actuator) + 1)
            if interrupted:
                note = "Telegram /stop으로 보정 중단" if interrupted == "operator" else "서버 종료로 보정 세션 중단"
                close_nutrient_session(item, "cancelled" if interrupted == "operator" else "interrupted", operator, note)
                return
            send_session_command("mixing", "on", NUTRIENT_MIX_SECONDS, operator, f"{label} 보정 후 교반 {NUTRIENT_MIX_SECONDS}초 · {pulse}회")
            interrupted = wait_for_nutrient_interval(NUTRIENT_MIX_SECONDS + 5)
            if interrupted:
                note = "Telegram /stop으로 보정 중단" if interrupted == "operator" else "서버 종료로 보정 세션 중단"
                close_nutrient_session(item, "cancelled" if interrupted == "operator" else "interrupted", operator, note)
                return

    except Exception as error:
        note = f"보정 세션 중단: {str(error)[:220]}"
        store.add_event({
            "command_id": started_id, "actuator": actuator,
            "requested_state": "off", "duration_seconds": 0,
            "source": f"feedback_session:{operator}", "result": "session_blocked", "note": note,
        })
        store.workflow("nutrient_feedback", "failed", note)
        close_nutrient_session(item, "blocked", operator, note)
        telegram_session_notice(f"⚠️ {label} 보정 세션이 안전상 중단되었습니다.\n현장과 대시보드 기록을 확인해 주세요.")
    finally:
        nutrient_session_state.update({"actuator": None, "operator": None})
        nutrient_session_lock.release()


def start_nutrient_feedback_session(item: dict[str, Any], operator: str) -> tuple[str, str]:
    if not NUTRIENT_FEEDBACK_ENABLED:
        raise HTTPException(409, "Nutrient feedback control is disabled")
    if not nutrient_session_lock.acquire(blocking=False):
        raise HTTPException(409, "Another nutrient correction session is already running")
    worker = threading.Thread(
        target=run_nutrient_feedback_session, args=(item, operator), daemon=True,
        name=f"nutrient-feedback-{item['actuator']}",
    )
    worker.start()
    return "executing", "승인된 보정 세션을 시작했습니다. 주입·교반·PE350 재측정 기록을 확인하세요."


def safe_execute(item: dict[str, Any], operator: str) -> tuple[str, str]:
    actuator = item.get("actuator")
    if not actuator:
        return "reviewed", "No actuator command was attached"
    if actuator == "supply" and SUPPLY_CONTINUOUS_ENABLED:
        raise HTTPException(409, "Supply circulation is fixed to continuous operation")
    if MQTT_SUBSCRIBE_ENABLED:
        raise HTTPException(409, "Remote MQTT dashboard is read-only")
    if actuator not in ACTUATORS:
        raise HTTPException(400, "Unknown actuator")
    if actuator in ("ec", "ph") and not CHEMICAL_CONTROL_ENABLED:
        raise HTTPException(409, "Chemical pump control is disabled")
    state = item.get("requested_state")
    duration = int(item.get("duration_seconds") or 0)
    if state == "on" and not 0 < duration <= ACTUATORS[actuator]["max_seconds"]:
        raise HTTPException(400, "Duration exceeds the safety limit")
    command_id = secrets.token_hex(8)
    if not CONTROL_ENABLED:
        note = "제어 잠금 상태라 실제 Pico 명령은 전송하지 않음"
        store.add_event({
            "command_id": command_id, "actuator": actuator,
            "requested_state": state, "duration_seconds": duration,
            "source": f"approved:{operator}", "result": "simulated", "note": note,
        })
        return "simulated", note
    if item.get("source") == "nutrient_feedback_rule":
        if not nutrient_request_matches_policy(item):
            raise HTTPException(409, "Dosing policy changed; request a fresh Telegram approval")
        latest = latest_with_health()
        if not latest.get("pe350_connected"):
            raise HTTPException(409, "PE350 evidence is incomplete or stale")
        return start_nutrient_feedback_session(item, operator)
    latest = latest_with_health()
    if not latest["sensor_control_ready"]:
        raise HTTPException(409, "Required sensor evidence is incomplete or stale")
    command = {
        "cmd_id": command_id, "action": "set", "actuator": actuator,
        "state": state, "duration_seconds": duration,
    }
    try:
        send_pico_command(command)
        store.add_event({
            "command_id": command["cmd_id"], "actuator": actuator,
            "requested_state": state, "duration_seconds": duration,
            "source": f"approved:{operator}", "result": "sent", "note": item["rationale"],
        })
    except (RuntimeError, serial.SerialException, OSError) as error:
        store.add_event({
            "command_id": command["cmd_id"], "actuator": actuator,
            "requested_state": state, "duration_seconds": duration,
            "source": f"approved:{operator}", "result": "failed", "note": str(error),
        })
        raise HTTPException(409, "Pico command was not sent") from error
    return "executed", f"Sent command {command['cmd_id']}"


def decide_recommendation(recommendation_id: int, decision: str, operator: str, note: str = "") -> dict[str, str]:
    """Atomically apply one human decision before a hardware command can be sent."""
    with recommendation_lock:
        item = store.recommendation(recommendation_id)
        if not item:
            raise HTTPException(404, "Recommendation not found")
        if item["status"] != "pending":
            raise HTTPException(409, "Recommendation was already decided")
        if decision == "reject":
            store.decide_recommendation(recommendation_id, "rejected", operator, note)
            record_decision_event(item, recommendation_id, "rejected", operator, note)
            return {"status": "rejected", "note": note}
        record_decision_event(item, recommendation_id, "approved", operator, note or "사람 승인")
        try:
            status, execution_note = safe_execute(item, operator)
        except HTTPException as error:
            execution_note = str(error.detail)
            if execution_note == "Another nutrient correction session is already running":
                store.decide_recommendation(recommendation_id, "deferred", operator, execution_note)
                record_decision_event(item, recommendation_id, "deferred", operator, execution_note)
                return {"status": "deferred", "note": "현재 보정이 끝난 뒤 새 텔레그램 승인 요청을 보냅니다."}
            store.decide_recommendation(recommendation_id, "blocked", operator, execution_note)
            record_decision_event(item, recommendation_id, "blocked", operator, execution_note)
            return {"status": "blocked", "note": execution_note}
        store.decide_recommendation(recommendation_id, status, operator, execution_note)
        return {"status": status, "note": execution_note}


def camera_configs() -> list[dict[str, str]]:
    cameras = []
    for number in range(1, 5):
        url = os.getenv(f"CAMERA_{number}_SNAPSHOT_URL", "").strip()
        if url:
            cameras.append({
                "id": f"CAM-{number:02d}", "slot": number, "url": url,
                "label": os.getenv(f"CAMERA_{number}_LABEL", "").strip() or f"카메라 {number}",
                "username": os.getenv(f"CAMERA_{number}_USERNAME", ""),
                "password": os.getenv(f"CAMERA_{number}_PASSWORD", ""),
            })
    return cameras


def public_camera_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.hostname:
        return url.split("@")[-1]
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    return parsed._replace(netloc=netloc).geturl()


def camera_settings_payload() -> dict[str, Any]:
    configured = {int(item["slot"]): item for item in camera_configs()}
    slots = []
    for number in range(1, 5):
        item = configured.get(number)
        slots.append({
            "slot": number,
            "id": f"CAM-{number:02d}",
            "label": item["label"] if item else os.getenv(f"CAMERA_{number}_LABEL", "").strip() or f"카메라 {number}",
            "snapshot_url": public_camera_url(item["url"]) if item else "",
            "username": item["username"] if item else os.getenv(f"CAMERA_{number}_USERNAME", ""),
            "password_saved": bool(os.getenv(f"CAMERA_{number}_PASSWORD", "")),
            "configured": item is not None,
        })
    return {
        "configured": [
            {"id": item["id"], "slot": item["slot"], "label": item["label"], "url": public_camera_url(item["url"])}
            for item in configured.values()
        ],
        "slots": slots,
        "captures": store.captures(),
    }


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
            results.append({"id": capture_id, "camera_id": camera["id"], "label": camera["label"], "status": "success"})
        except (requests.RequestException, OSError, ValueError) as error:
            capture_id = store.add_capture(camera["id"], None, "failed", str(error))
            results.append({"id": capture_id, "camera_id": camera["id"], "label": camera["label"], "status": "failed", "error": str(error)})
    successes = sum(item["status"] == "success" for item in results)
    workflow_status = "skipped" if not cameras else "success" if successes == len(cameras) else "partial" if successes else "failed"
    store.workflow(
        "camera_capture", workflow_status,
        json.dumps(results, ensure_ascii=False) if cameras else "No camera is configured",
    )
    return results


def most_recent_capture() -> dict[str, Any] | None:
    for item in store.captures(20):
        if item["status"] == "success" and item.get("path") and Path(item["path"]).exists():
            return item
    return None


def latest_capture_set() -> list[dict[str, Any]]:
    """Return the newest successful image for every configured camera view."""
    selected: dict[str, dict[str, Any]] = {}
    for item in store.captures(100):
        camera_id = str(item.get("camera_id") or "")
        path = Path(str(item.get("path") or ""))
        if camera_id and camera_id not in selected and item.get("status") == "success" and path.exists():
            selected[camera_id] = item
    return [selected[key] for key in sorted(selected)]


def deterministic_analysis(latest: dict[str, Any], captures: list[dict[str, Any]]) -> dict[str, Any]:
    warnings = []
    for label, key, low, high in (
        ("기온", "air_temp", 18.0, 25.0), ("습도", "humidity", 60.0, 80.0),
        ("EC", "ec", 1.0, 1.5), ("pH", "ph", 5.8, 6.2),
    ):
        value = latest.get(key)
        if value is None:
            warnings.append(f"{label} 데이터 누락")
        elif not low <= float(value) <= high:
            warnings.append(f"{label} {value}가 관리 기준 {low}~{high} 밖")
    overall = "주의" if warnings else ("정상" if latest else "판단 불가")
    observations = []
    limitations = []
    if captures:
        observations.append(f"카메라 {len(captures)}대의 최신 이미지는 저장되었으나 규칙 분석에서는 식물 외형을 판독하지 않음")
    else:
        limitations.append("사용 가능한 카메라 이미지 없음")
    return {
        "model": "rule-engine:no-ai", "capture_id": captures[0]["id"] if captures else None,
        "capture_ids": [item["id"] for item in captures],
        "overall_status": overall,
        "summary": "; ".join(warnings) if warnings else "수집된 환경값이 현재 관리 기준 안에 있습니다.",
        "confidence": "중간" if latest else "낮음",
        "growth_stage": DEFAULT_GROWTH_STAGE,
        "growth_stage_confidence": "낮음",
        "nutrition_assessment": "AI 이미지 분석을 사용할 수 없어 학교 기본 단계 기준으로 EC·pH를 비교했습니다.",
        "observations": observations,
        "limitations": limitations + ["OpenAI API를 사용하지 않은 규칙 기반 결과"],
    }


def openai_analysis(latest: dict[str, Any], captures: list[dict[str, Any]]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return deterministic_analysis(latest, captures)
    content: list[dict[str, Any]] = [{
        "type": "input_text",
        "text": (
            "브로콜리 스마트팜 일일 관찰을 수행하라. 센서값 출처와 누락을 구분하고, "
            "사진에서 직접 보이는 사실만 기록하라. 병해충을 확진하지 말고 제어 명령을 내리지 마라. "
            "서로 다른 카메라 3대의 사진을 하나의 농장 상태로 종합하되, 카메라별로 보이는 차이는 구분해 기록하라. "
            "사진과 센서 근거로 생육 단계를 육묘기·활착기·생육기·수확전 중 하나로 분류하되, "
            "확신이 낮으면 학교 기본값인 육묘기를 사용했다고 limitations에 밝혀라. "
            "반드시 JSON 하나만 반환하라: "
            '{"overall_status":"정상|주의|경고|판단 불가","summary":"...",'
            '"confidence":"높음|중간|낮음","growth_stage":"육묘기|활착기|생육기|수확전",'
            '"growth_stage_confidence":"높음|중간|낮음","nutrition_assessment":"...",'
            '"observations":["..."],"limitations":["..."]}. '
            "센서 데이터: " + json.dumps(latest, ensure_ascii=False, default=str)
        ),
    }]
    for capture in captures[:4]:
        path = Path(str(capture.get("path") or ""))
        if not path.exists():
            continue
        image_bytes = path.read_bytes()
        camera_id = str(capture.get("camera_id") or "카메라")
        content.append({"type": "input_text", "text": f"다음 이미지는 {camera_id} 시야다."})
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
                        "growth_stage": {
                            "type": "string",
                            "enum": ["육묘기", "활착기", "생육기", "수확전"],
                        },
                        "growth_stage_confidence": {
                            "type": "string",
                            "enum": ["높음", "중간", "낮음"],
                        },
                        "nutrition_assessment": {"type": "string"},
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
                        "overall_status", "summary", "confidence", "growth_stage",
                        "growth_stage_confidence", "nutrition_assessment",
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
        "capture_id": captures[0]["id"] if captures else None,
        "capture_ids": [item["id"] for item in captures],
    })
    return result


def rule_alert_allowed(title: str) -> bool:
    key = "rule_alert:" + title
    stored = store.setting(key)
    if stored:
        try:
            previous = datetime.fromisoformat(stored)
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=SEOUL)
            if datetime.now(SEOUL) - previous.astimezone(SEOUL) < timedelta(seconds=RULE_ALERT_COOLDOWN_SECONDS):
                return False
        except ValueError:
            pass
    return True


def create_rule_recommendations(latest: dict[str, Any], analysis: dict[str, Any] | None = None) -> list[int]:
    candidates = []
    stage, profile = growth_stage_profile(analysis)
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
    ec, ph = latest.get("ec"), latest.get("ph")
    pe350_ready = bool(latest.get("pe350_connected", ec is not None and ph is not None))
    if NUTRIENT_FEEDBACK_ENABLED and pe350_ready and ec is not None and float(ec) < profile["ec_low"]:
        candidates.append({
            "source": "nutrient_feedback_rule", "severity": "warning",
            "title": f"{stage} EC 낮음: A+B {EC_PULSE_SECONDS}초 보정 승인 요청",
            "rationale": (
                f"AI 판단 단계: {stage}. 현재 EC {float(ec):.3f} dS/m는 목표 {profile['ec_target']:.1f} "
                f"(관리 {profile['ec_low']:.1f}~{profile['ec_high']:.1f})보다 낮음. 승인 시 A+B를 "
                f"{EC_PULSE_SECONDS}초씩 주입하고 {NUTRIENT_MIX_SECONDS}초 교반·재측정을 목표값까지 반복. /stop으로 중단 가능"
            ),
            "actuator": "ec", "requested_state": "on", "duration_seconds": EC_PULSE_SECONDS,
            "evidence": {
                "ec": ec, "lower_limit": profile["ec_low"], "target": f"{profile['ec_low']:.1f}~{profile['ec_high']:.1f}", "pump": "A+B",
                "growth_stage": stage, "growth_profile": profile,
                "analysis_confidence": (analysis or {}).get("growth_stage_confidence", "낮음"),
                "feedback_policy": nutrient_feedback_policy("ec"),
            }, "model": (analysis or {}).get("model"),
        })
    if NUTRIENT_FEEDBACK_ENABLED and pe350_ready and ph is not None and float(ph) > profile["ph_high"]:
        candidates.append({
            "source": "nutrient_feedback_rule", "severity": "warning",
            "title": f"{stage} pH 높음: 산성액 {PH_PULSE_SECONDS}초 보정 승인 요청",
            "rationale": (
                f"AI 판단 단계: {stage}. 현재 pH {float(ph):.2f}는 목표 {profile['ph_target']:.1f} "
                f"(관리 {profile['ph_low']:.1f}~{profile['ph_high']:.1f})보다 높음. 승인 시 산성 pH 조절액을 "
                f"{PH_PULSE_SECONDS}초씩 주입하고 {NUTRIENT_MIX_SECONDS}초 교반·재측정을 목표값까지 반복. /stop으로 중단 가능"
            ),
            "actuator": "ph", "requested_state": "on", "duration_seconds": PH_PULSE_SECONDS,
            "evidence": {
                "ph": ph, "upper_limit": profile["ph_high"], "target": f"{profile['ph_low']:.1f}~{profile['ph_high']:.1f}", "pump": "acid",
                "growth_stage": stage, "growth_profile": profile,
                "analysis_confidence": (analysis or {}).get("growth_stage_confidence", "낮음"),
                "feedback_policy": nutrient_feedback_policy("ph"),
            }, "model": (analysis or {}).get("model"),
        })
    for pending in store.recommendations(200):
        if pending.get("status") != "pending" or pending.get("source") != "nutrient_feedback_rule":
            continue
        if not recommendation_is_fresh(pending):
            note = "승인 유효시간이 지나 새 실측값 기반 요청으로 교체"
            store.decide_recommendation(int(pending["id"]), "superseded", "system", note)
            record_decision_event(pending, int(pending["id"]), "superseded", "system", note)
            continue
        if nutrient_request_matches_policy(pending):
            continue
        note = "보정 시간 정책이 변경되어 새 텔레그램 승인 요청으로 교체"
        store.decide_recommendation(int(pending["id"]), "superseded", "system", note)
        record_decision_event(pending, int(pending["id"]), "superseded", "system", note)
    recommendation_history = store.recommendations(200)
    pending_titles = {item["title"] for item in recommendation_history if item["status"] == "pending"}
    retry_titles = {
        item["title"] for item in recommendation_history
        if item["status"] in {"deferred", "limited"}
    }
    created = []
    for item in candidates:
        if item["title"] in pending_titles:
            continue
        if item["title"] not in retry_titles and not rule_alert_allowed(item["title"]):
            continue
        recommendation_id = add_actuator_recommendation(item)
        store.set_settings({"rule_alert:" + item["title"]: datetime.now(SEOUL).isoformat(timespec="seconds")})
        created.append(recommendation_id)
    return created


def run_analysis() -> dict[str, Any]:
    latest = store.latest_sensor() or {}
    captures = latest_capture_set()
    try:
        degraded_error = None
        try:
            result = openai_analysis(latest, captures)
        except Exception as error:
            # Keep the scheduled safety/status notification alive, but never label a
            # deterministic fallback as an AI observation.
            degraded_error = f"OpenAI unavailable: {type(error).__name__}: {str(error)[:180]}"
            result = deterministic_analysis(latest, captures)
            result["limitations"] = list(result.get("limitations", [])) + [degraded_error]
        analysis_id = store.add_analysis(result)
        recommendation_ids = create_rule_recommendations(latest, result)
        store.workflow("ai_analysis", "degraded" if degraded_error else "success", f"analysis={analysis_id}; {degraded_error or 'OpenAI success'}")
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


def telegram_callback_data(recommendation_id: int, decision: str) -> str:
    return f"farm:{'a' if decision == 'approve' else 'r'}:{recommendation_id}"


def parse_telegram_callback(value: str) -> tuple[str, int]:
    match = re.fullmatch(r"farm:([ar]):(\d{1,12})", value or "")
    if not match:
        raise ValueError("Unknown approval button")
    return ("approve" if match.group(1) == "a" else "reject", int(match.group(2)))


_TELEGRAM_TECHNICAL_TEXT = re.compile(
    r"(?:openai|ratelimit|rate\s*limit|exception|error|traceback|status\s*code|http\s*\d{3}|\b[45]\d\d\b)",
    re.IGNORECASE,
)


def telegram_public_text(value: Any, fallback: str) -> str:
    """Return a short human-facing sentence without implementation error details."""
    text = " ".join(str(value or "").split())
    if not text or _TELEGRAM_TECHNICAL_TEXT.search(text):
        return fallback
    return text[:180]


def telegram_daily_caption(latest: dict[str, Any], analysis: dict[str, Any], capture_available: bool) -> str:
    measured = str(latest.get("source", "")).startswith("measured")
    source = "Pico 센서 실측" if measured else "모의값 · 현장 확인 필요"
    status = str(analysis.get("overall_status") or "판단 불가")
    status_icon = {"정상": "🟢", "주의": "🟠", "경고": "🔴"}.get(status, "⚪")
    summary = telegram_public_text(analysis.get("summary"), "환경·사진 근거를 확인해 주세요.")
    public_notes = [
        telegram_public_text(item, "")
        for item in [*analysis.get("observations", []), *analysis.get("limitations", [])]
    ]
    public_notes = [item for item in public_notes if item]
    field_check = public_notes[0] if public_notes else "잎·배지·양액 상태를 현장에서 함께 확인해 주세요."
    model = str(analysis.get("model") or "")
    analysis_mode = "기본 안전 분석" if model == "rule-engine:no-ai" else "AI 사진·환경 분석"
    stage, profile = growth_stage_profile(analysis)
    nutrition = telegram_public_text(analysis.get("nutrition_assessment"), "센서값과 단계별 EC·pH 목표를 함께 확인합니다.")

    return (
        "🥦 브로콜리 | 오늘의 상태\n"
        f"🕛 {datetime.now(SEOUL).strftime('%Y-%m-%d %H:%M')} KST\n\n"
        f"{status_icon} 상태: {status}\n"
        f"📝 {summary}\n\n"
        f"🌡 환경 ({source})\n"
        f"   {latest.get('air_temp', '--')}°C · 습도 {latest.get('humidity', '--')}%\n"
        f"🧪 양액 ({source})\n"
        f"   EC {latest.get('ec', '--')} dS/m · pH {latest.get('ph', '--')}\n"
        f"🌱 생육 단계: {stage} (판단 {analysis.get('growth_stage_confidence', '낮음')})\n"
        f"   목표 EC {profile['ec_target']:.1f} · pH {profile['ph_target']:.1f}\n"
        f"   영양 판단: {nutrition}\n"
        f"📷 최신 사진: {'첨부됨' if capture_available else '없음'}\n"
        f"🤖 분석 방식: {analysis_mode}\n"
        f"🔎 현장 확인: {field_check}\n\n"
        "제안이 있을 때만 아래 승인 버튼이 표시됩니다."
    )


def telegram_approval_keyboard(recommendation_ids: list[int]) -> dict[str, Any] | None:
    config = telegram_config()
    if not config["approvals_ready"]:
        return None
    rows = []
    for recommendation_id in recommendation_ids:
        item = store.recommendation(recommendation_id)
        if not item or item.get("status") != "pending" or not item.get("actuator"):
            continue
        label = ACTUATORS.get(str(item["actuator"]), {}).get("label", item["actuator"])
        duration = int(item.get("duration_seconds") or 0)
        rows.append([
            {"text": f"✅ {label} {duration}초 승인", "callback_data": telegram_callback_data(recommendation_id, "approve")},
            {"text": "❌ 거절", "callback_data": telegram_callback_data(recommendation_id, "reject")},
        ])
    return {"inline_keyboard": rows} if rows else None


def telegram_send_approval_requests(recommendation_ids: list[int], *, context: str) -> str:
    """Notify the approved chat of pending proposals; never send a Pico command."""
    keyboard = telegram_approval_keyboard(recommendation_ids)
    if not keyboard:
        return "not_ready_or_no_pending_request"
    try:
        details = []
        for recommendation_id in recommendation_ids:
            item = store.recommendation(recommendation_id)
            if not item or item.get("status") != "pending":
                continue
            evidence = item.get("evidence") or {}
            if item.get("source") == "nutrient_feedback_rule":
                stage = evidence.get("growth_stage", DEFAULT_GROWTH_STAGE)
                target = evidence.get("target", "관리 기준")
                value = evidence.get("ec") if item.get("actuator") == "ec" else evidence.get("ph")
                label = "EC" if item.get("actuator") == "ec" else "pH"
                unit = " dS/m" if label == "EC" else ""
                details.append(
                    f"🌱 AI 판단: {stage} (신뢰도 {evidence.get('analysis_confidence', '낮음')})\n"
                    f"🧪 현재 {label} {value}{unit} · 적정 범위 {target}\n"
                    f"💡 {item.get('rationale')}"
                )
            else:
                details.append(f"💡 {item.get('rationale') or item.get('title')}")
        telegram_send_message(
            f"🥦 새 제어 제안 ({context})\n"
            + "\n\n".join(details)
            + "\n\n승인하면 해당 생육 단계의 목표값까지 반복 보정합니다. 언제든 /stop 으로 즉시 중단할 수 있습니다.",
            keyboard,
        )
        store.workflow("telegram_approval_request", "success", f"context={context}; ids={recommendation_ids}")
        return "sent"
    except Exception as error:
        store.workflow("telegram_approval_request", "failed", f"{type(error).__name__}: {str(error)[:300]}")
        update_runtime(telegram_error=f"approval notification: {type(error).__name__}: {str(error)[:160]}")
        return "failed"


def telegram_daily_brief_job(force: bool = False) -> dict[str, Any]:
    """Capture, observe, and send a noon status. It never executes a command itself."""
    config = telegram_config()
    if not force and not config["daily_enabled"]:
        return {"status": "disabled"}
    if not config["configured"]:
        store.workflow("telegram_daily_brief", "skipped", "Telegram token or chat ID is not configured")
        return {"status": "not_configured"}
    try:
        captures = capture_cameras()
        analysis = run_analysis()
        capture = most_recent_capture()
        capture_path = Path(capture["path"]) if capture and capture.get("path") else None
        latest = latest_with_health()
        keyboard = telegram_approval_keyboard(analysis.get("recommendation_ids", []))
        caption = telegram_daily_caption(latest, analysis, bool(capture_path and capture_path.exists()))
        if capture_path and capture_path.exists():
            telegram_send_photo(capture_path, caption, keyboard)
        else:
            telegram_send_message(caption, keyboard)
        report = create_report(send_telegram=True)
        store.workflow(
            "telegram_on_demand_brief" if force else "telegram_daily_brief", "success",
            f"captures={sum(row['status'] == 'success' for row in captures)}; analysis={analysis['id']}; report={report['id']}",
        )
        return {"status": "sent", "analysis": analysis, "captures": captures, "report": report}
    except Exception as error:
        store.workflow("telegram_daily_brief", "failed", f"{type(error).__name__}: {str(error)[:300]}")
        raise


def recommendation_is_fresh(item: dict[str, Any]) -> bool:
    try:
        created_at = datetime.fromisoformat(str(item["created_at"]))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=SEOUL)
        ttl = int(os.getenv("SMARTFARM_TELEGRAM_APPROVAL_TTL_SECONDS", "600"))
        return datetime.now(SEOUL) - created_at.astimezone(SEOUL) <= timedelta(seconds=max(30, min(ttl, 3600)))
    except (KeyError, TypeError, ValueError):
        return False


def process_telegram_callback(callback: dict[str, Any]) -> None:
    config = telegram_config()
    callback_id = str(callback.get("id", ""))

    def answer(message: str, alert: bool = False) -> None:
        if callback_id:
            telegram_api("answerCallbackQuery", data={"callback_query_id": callback_id, "text": message[:200], "show_alert": alert})

    try:
        chat_id = str(((callback.get("message") or {}).get("chat") or {}).get("id", ""))
        user_id = int((callback.get("from") or {}).get("id"))
        if not config["approvals_ready"]:
            raise PermissionError("Telegram approval is not configured")
        if chat_id != config["chat_id"]:
            raise PermissionError("This chat is not permitted")
        explicitly_allowed = user_id in config["approvers"]
        group_member_allowed = config["allow_group_members"] and telegram_group_member_allowed(chat_id, user_id)
        if not explicitly_allowed and not group_member_allowed:
            raise PermissionError("You are not an approved operator")
        decision, recommendation_id = parse_telegram_callback(str(callback.get("data", "")))
        item = store.recommendation(recommendation_id)
        if not item or item.get("status") != "pending":
            raise ValueError("This request was already processed")
        if not recommendation_is_fresh(item):
            raise ValueError("This approval request has expired; create a new request")
        result = decide_recommendation(recommendation_id, decision, f"telegram:{user_id}", "Telegram inline approval")
        answer(f"{result['status']}: #{recommendation_id}")
        telegram_send_message(f"#{recommendation_id} {result['status']} · {result['note']}")
    except (HTTPException, PermissionError, TypeError, ValueError) as error:
        answer(str(getattr(error, "detail", error)), alert=True)
    except Exception as error:
        update_runtime(telegram_error=f"callback failed: {type(error).__name__}: {str(error)[:160]}")
        try:
            answer("처리 중 오류가 발생했습니다. 대시보드에서 상태를 확인하세요.", alert=True)
        except Exception:
            pass


def telegram_poll_worker() -> None:
    """Long-poll approval buttons without exposing a webhook or dashboard port."""
    bootstrap = True
    while not stop_event.is_set():
        config = telegram_config()
        if not config["approvals_ready"]:
            update_runtime(telegram_polling=False)
            stop_event.wait(3)
            continue
        try:
            saved_offset = store.setting("telegram_update_offset")
            offset = int(saved_offset) if saved_offset and saved_offset.isdigit() else None
            data: dict[str, Any] = {"timeout": 20, "allowed_updates": json.dumps(["callback_query", "message"])}
            if offset is not None:
                data["offset"] = offset
            elif bootstrap:
                data["offset"] = -1
            updates = telegram_api("getUpdates", data=data, timeout=30) or []
            update_runtime(telegram_polling=True, telegram_error=None)
            if bootstrap:
                for update in updates:
                    if isinstance(update, dict) and isinstance(update.get("update_id"), int):
                        store.set_settings({"telegram_update_offset": str(update["update_id"] + 1)})
                bootstrap = False
                continue
            for update in updates:
                if not isinstance(update, dict) or not isinstance(update.get("update_id"), int):
                    continue
                store.set_settings({"telegram_update_offset": str(update["update_id"] + 1)})
                callback = update.get("callback_query")
                if isinstance(callback, dict):
                    process_telegram_callback(callback)
                message = update.get("message")
                if isinstance(message, dict):
                    process_telegram_message(message)
        except Exception as error:
            update_runtime(telegram_polling=False, telegram_error=f"Telegram polling: {type(error).__name__}: {str(error)[:180]}")
            stop_event.wait(10)


def create_report(report_date: str | None = None, send_telegram: bool = False) -> dict[str, Any]:
    report_date = report_date or date.today().isoformat()
    stats = store.day_stats(report_date)
    data_source = store.day_source_label(report_date)
    analyses = store.analyses(1)
    analysis = analyses[0] if analyses else None
    analysis_result = dict((analysis or {}).get("result") or {})
    growth_stage, management_profile = growth_stage_profile(analysis_result)
    captures = latest_capture_set()
    model = analysis["model"] if analysis else "분석 기록 없음"
    actuator_events = store.day_events(report_date)
    output = REPORT_DIR / f"broccoli_daily_{report_date}.pdf"
    generate_daily_pdf(
        output, report_date, stats, analysis, captures, model, data_source, BASE_DIR,
        actuator_events=actuator_events, growth_stage=growth_stage, management_profile=management_profile,
    )
    telegram_status = telegram_send_report(output, f"{report_date} 브로콜리 AI 일일 생육관찰 보고서") if send_telegram else "not_requested"
    report_id = store.add_report({
        "report_date": report_date, "path": str(output), "model": model,
        "status": "created", "telegram_status": telegram_status,
    })
    store.workflow("daily_report", "success", f"report={report_id}; actuator_events={len(actuator_events)}")
    return {
        "id": report_id, "report_date": report_date, "model": model,
        "telegram_status": telegram_status, "actuator_event_count": len(actuator_events),
    }


def capture_and_analyze_job() -> None:
    capture_cameras()
    analysis = run_analysis()
    telegram_send_approval_requests(analysis.get("recommendation_ids", []), context="정기 분석")


def sensor_alert_job() -> None:
    """Create only bounded rule proposals; Telegram approval remains mandatory."""
    if not SENSOR_ALERTS_ENABLED:
        return
    latest = latest_with_health()
    if not latest.get("pico_connected"):
        return
    previous_row = (store.analyses(1) or [{}])[0]
    previous = dict(previous_row.get("result") or {})
    recommendation_ids = create_rule_recommendations(latest, previous)
    if recommendation_ids:
        telegram_send_approval_requests(recommendation_ids, context="실시간 센서 경보")


def daily_report_job() -> None:
    create_report(send_telegram=True)


def led_schedule_job() -> None:
    reconcile_led_schedule()


def supply_circulation_job() -> None:
    reconcile_supply_circulation()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global scheduler, telegram_thread
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    store.initialize()
    stop_event.clear()
    start_mqtt()
    worker = None
    if not MQTT_SUBSCRIBE_ENABLED:
        worker = threading.Thread(target=simulation_worker if SIMULATION else serial_worker, daemon=True)
        worker.start()
    telegram_thread = threading.Thread(target=telegram_poll_worker, daemon=True, name="telegram-approval-poll")
    telegram_thread.start()
    scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        led_schedule_job,
        "interval",
        seconds=15,
        id="led_photoperiod",
        max_instances=1,
        coalesce=True,
    )
    if AUTOMATION_ENABLED:
        scheduler.add_job(capture_and_analyze_job, "cron", hour="0,6,18", minute=0, id="capture_analysis", max_instances=1)
    scheduler.add_job(
        telegram_daily_brief_job,
        "cron",
        hour=12,
        minute=0,
        id="telegram_daily_brief",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        supply_circulation_job,
        "interval",
        seconds=15,
        id="continuous_supply",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        sensor_alert_job,
        "interval",
        seconds=60,
        id="sensor_alerts",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    yield
    stop_event.set()
    if scheduler:
        scheduler.shutdown(wait=False)
    if worker:
        worker.join(timeout=2)
    if telegram_thread:
        telegram_thread.join(timeout=2)
    stop_mqtt()


app = FastAPI(title="Broccoli Smart Farm Control Center", version="2.0", lifespan=lifespan)


@app.get("/api/health", dependencies=[Depends(require_auth)])
def health() -> dict[str, Any]:
    latest = latest_with_health()
    with state_lock:
        mqtt_status = {
            "publish_enabled": MQTT_PUBLISH_ENABLED,
            "subscribe_enabled": MQTT_SUBSCRIBE_ENABLED,
            "connected": bool(runtime_state["mqtt_connected"]),
            "topic": runtime_state["mqtt_topic"],
            "error": runtime_state["mqtt_error"],
        }
    return {
        "server": "online", "database": "online", "pico": "online" if latest["pico_connected"] else "offline",
        "simulation": SIMULATION,
        "control_enabled": CONTROL_ENABLED and not MQTT_SUBSCRIBE_ENABLED,
        "mqtt_mode": MQTT_MODE,
        "mqtt_connected": bool(runtime_state["mqtt_connected"]),
        "mqtt_error": runtime_state["mqtt_error"],
        "chemical_control_enabled": CHEMICAL_CONTROL_ENABLED and not MQTT_SUBSCRIBE_ENABLED,
        "automation_enabled": AUTOMATION_ENABLED, "configured_model": OPENAI_MODEL,
        "sensor_alerts_enabled": SENSOR_ALERTS_ENABLED,
        "nutrient_feedback_enabled": NUTRIENT_FEEDBACK_ENABLED,
        "supply_continuous_enabled": SUPPLY_CONTINUOUS_ENABLED,
        "nutrient_session_active": nutrient_session_lock.locked(),
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "led_schedule_hardware_enabled": LED_SCHEDULE_HARDWARE_ENABLED,
        "telegram_configured": telegram_config()["configured"],
        "telegram_approvals_ready": telegram_config()["approvals_ready"],
        "telegram_polling": bool(runtime_state.get("telegram_polling")),
        "telegram_error": runtime_state.get("telegram_error"),
        "dashboard_auth_configured": bool(os.getenv("DASHBOARD_USERNAME") and os.getenv("DASHBOARD_PASSWORD")),
        "camera_count": len(camera_configs()), "database_path": str(DB_PATH),
        "pico_error": latest.get("error"),
        "mqtt": mqtt_status,
    }


@app.get("/api/settings/openai", dependencies=[Depends(require_auth)])
def openai_settings() -> dict[str, Any]:
    return {
        "configured": bool(os.getenv("OPENAI_API_KEY")),
        "model": OPENAI_MODEL,
    }


@app.get("/api/settings/telegram", dependencies=[Depends(require_auth)])
def get_telegram_settings() -> dict[str, Any]:
    return telegram_settings_payload()


@app.post(
    "/api/settings/telegram/discover-chats",
    dependencies=[Depends(require_auth), Depends(require_local_settings)],
)
def discover_telegram_chats() -> dict[str, Any]:
    """List group IDs from recent bot updates without returning message text or tokens."""
    if not os.getenv("TELEGRAM_BOT_TOKEN", "").strip():
        raise HTTPException(409, "Save a Telegram bot token first")
    if telegram_config()["approvals_ready"]:
        raise HTTPException(409, "Telegram approval polling is already active; do not run group discovery")
    try:
        updates = telegram_bot_api(
            "getUpdates",
            data={"timeout": 0, "allowed_updates": json.dumps(["message", "my_chat_member"])},
            timeout=15,
        ) or []
        chats: dict[str, dict[str, str]] = {}
        approvers: dict[str, dict[str, str]] = {}
        for update in updates:
            if not isinstance(update, dict):
                continue
            message = update.get("message")
            if not isinstance(message, dict):
                member = update.get("my_chat_member")
                message = member if isinstance(member, dict) else None
            chat = message.get("chat") if isinstance(message, dict) else None
            if not isinstance(chat, dict) or chat.get("type") not in {"group", "supergroup"}:
                continue
            chat_id = str(chat.get("id", ""))
            if re.fullmatch(r"-?\d{5,20}", chat_id):
                chats[chat_id] = {
                    "id": chat_id,
                    "title": str(chat.get("title") or "제목 없는 그룹")[:120],
                    "type": str(chat["type"]),
                }
            sender = message.get("from") if isinstance(message, dict) else None
            sender_id = str(sender.get("id", "")) if isinstance(sender, dict) else ""
            if re.fullmatch(r"\d{4,20}", sender_id):
                label = str(sender.get("username") or sender.get("first_name") or "이름 없는 사용자")[:80]
                approvers[sender_id] = {"id": sender_id, "label": label, "chat_title": chats[chat_id]["title"]}
        return {"chats": list(chats.values()), "approvers": list(approvers.values())}
    except Exception as error:
        raise HTTPException(400, f"Telegram group search failed: {type(error).__name__}: {str(error)[:180]}") from error


@app.put(
    "/api/settings/telegram",
    dependencies=[Depends(require_auth), Depends(require_local_settings)],
)
def save_telegram_settings(request: TelegramSettingsRequest) -> dict[str, Any]:
    token = (request.bot_token or "").strip()
    chat_id = (request.chat_id or "").strip()
    approvers_raw = (request.approver_user_ids or "").strip()
    if token and ("\n" in token or "\r" in token or not re.fullmatch(r"\d{5,20}:[A-Za-z0-9_-]{15,250}", token)):
        raise HTTPException(400, "Invalid Telegram bot token format")
    if chat_id and not re.fullmatch(r"-?\d{5,20}", chat_id):
        raise HTTPException(400, "Telegram chat ID must be numeric")
    try:
        approvers = telegram_approver_ids(approvers_raw)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    effective_token = token or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    effective_chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "").strip()
    effective_approvers_raw = approvers_raw if request.approver_user_ids is not None else os.getenv("TELEGRAM_APPROVER_USER_IDS", "")
    if request.approver_user_ids is None:
        try:
            approvers = telegram_approver_ids(effective_approvers_raw)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
    if request.approval_enabled and not (effective_token and effective_chat_id and (approvers or request.allow_group_members)):
        raise HTTPException(400, "Approval requires a bot token, chat ID, and an approved user ID or group-member approval")
    values = {
        "SMARTFARM_TELEGRAM_DAILY_ENABLED": "1" if request.daily_enabled else "0",
        "SMARTFARM_TELEGRAM_APPROVAL_ENABLED": "1" if request.approval_enabled else "0",
        "SMARTFARM_TELEGRAM_ALLOW_GROUP_MEMBERS": "1" if request.allow_group_members else "0",
    }
    if token:
        values["TELEGRAM_BOT_TOKEN"] = token
    if request.chat_id is not None:
        values["TELEGRAM_CHAT_ID"] = chat_id
    if request.approver_user_ids is not None:
        values["TELEGRAM_APPROVER_USER_IDS"] = approvers_raw
    update_env_file(values)
    return {**telegram_settings_payload(), "message": "Telegram settings saved on the server"}


@app.post(
    "/api/settings/telegram/test",
    dependencies=[Depends(require_auth), Depends(require_local_settings)],
)
def test_telegram_settings() -> dict[str, Any]:
    if not telegram_config()["configured"]:
        raise HTTPException(409, "Save a Telegram bot token and chat ID first")
    try:
        bot = telegram_api("getMe", timeout=15)
        webhook = telegram_api("getWebhookInfo", timeout=15)
        return {
            "ok": True,
            "bot_username": bot.get("username") if isinstance(bot, dict) else None,
            "webhook_active": bool(isinstance(webhook, dict) and webhook.get("url")),
        }
    except Exception as error:
        raise HTTPException(400, f"Telegram connection failed: {type(error).__name__}: {str(error)[:180]}") from error


@app.put(
    "/api/settings/openai",
    dependencies=[Depends(require_auth), Depends(require_local_settings)],
)
def save_openai_settings(request: OpenAISettingsRequest) -> dict[str, Any]:
    global OPENAI_MODEL
    values = {"OPENAI_MODEL": request.model.strip()}
    api_key = (request.api_key or "").strip()
    if api_key:
        if "\n" in api_key or "\r" in api_key or len(api_key) < 20:
            raise HTTPException(400, "Invalid API key format")
        values["OPENAI_API_KEY"] = api_key
    update_env_file(values)
    OPENAI_MODEL = values["OPENAI_MODEL"]
    return {
        "configured": bool(os.getenv("OPENAI_API_KEY")),
        "model": OPENAI_MODEL,
        "message": "OpenAI settings saved on the server",
    }


@app.post(
    "/api/settings/openai/test",
    dependencies=[Depends(require_auth), Depends(require_local_settings)],
)
def test_openai_settings() -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(409, "Save an OpenAI API key first")
    try:
        model = OpenAI(api_key=api_key).models.retrieve(OPENAI_MODEL)
        return {"ok": True, "model": getattr(model, "id", OPENAI_MODEL)}
    except Exception as error:
        raise HTTPException(
            400,
            f"OpenAI connection failed: {type(error).__name__}: {str(error)[:180]}",
        ) from error


@app.get("/api/led-schedule", dependencies=[Depends(require_auth)])
def get_led_schedule() -> dict[str, Any]:
    return led_schedule_config()


@app.put(
    "/api/led-schedule",
    dependencies=[Depends(require_auth), Depends(require_local_settings)],
)
def save_led_schedule(request: LedScheduleRequest) -> dict[str, Any]:
    try:
        photoperiod_minutes(request.on_time, request.off_time)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    store.set_settings({
        "led_schedule_enabled": "1" if request.enabled else "0",
        "led_schedule_on_time": request.on_time,
        "led_schedule_off_time": request.off_time,
    })
    result = reconcile_led_schedule(force=True)
    return {**result, "saved": True}


@app.get("/api/sensors/latest", dependencies=[Depends(require_auth)])
def latest_sensors() -> dict[str, Any]:
    return latest_with_health()


@app.get("/api/sensors/history", dependencies=[Depends(require_auth)])
def sensor_history(
    hours: int | None = Query(None, ge=1, le=2160),
    start: str | None = None,
    end: str | None = None,
    max_points: int = Query(1600, ge=200, le=2500),
) -> list[dict[str, Any]]:
    """Read a preset or explicit Seoul-time range as one-hour sensor averages."""
    if bool(start) != bool(end):
        raise HTTPException(400, "Provide both start and end timestamps")
    if start and end:
        try:
            range_start = datetime.fromisoformat(start.replace("Z", "+00:00"))
            range_end = datetime.fromisoformat(end.replace("Z", "+00:00"))
        except ValueError as error:
            raise HTTPException(400, "Use ISO-8601 start and end timestamps") from error
        if range_start.tzinfo is None:
            range_start = range_start.replace(tzinfo=SEOUL)
        if range_end.tzinfo is None:
            range_end = range_end.replace(tzinfo=SEOUL)
        range_start, range_end = range_start.astimezone(SEOUL), range_end.astimezone(SEOUL)
        if range_end <= range_start or range_end - range_start > timedelta(days=90):
            raise HTTPException(400, "Select a range from 1 minute to 90 days")
        return store.sensor_history(limit=max_points, start=range_start, end=range_end)
    return store.sensor_history(hours=hours or 24, limit=max_points)


@app.get("/api/actuators", dependencies=[Depends(require_auth)])
def actuators() -> dict[str, Any]:
    with state_lock:
        states = dict(runtime_state["actuators"])
    return {"control_enabled": CONTROL_ENABLED and not MQTT_SUBSCRIBE_ENABLED,
            "chemical_control_enabled": CHEMICAL_CONTROL_ENABLED and not MQTT_SUBSCRIBE_ENABLED,
            "supply_continuous_enabled": SUPPLY_CONTINUOUS_ENABLED,
            "items": [{"id": key, "state": states.get(key, "unknown"), **value} for key, value in ACTUATORS.items()]}


@app.post("/api/actuators/{actuator}/request", dependencies=[Depends(require_auth)])
def request_actuator(actuator: str, request: ManualRequest) -> dict[str, Any]:
    if MQTT_SUBSCRIBE_ENABLED:
        raise HTTPException(409, "Remote MQTT dashboard is read-only")
    if actuator not in ACTUATORS:
        raise HTTPException(404, "Unknown actuator")
    if actuator == "supply" and SUPPLY_CONTINUOUS_ENABLED:
        raise HTTPException(409, "Supply circulation is fixed to continuous operation")
    if request.state == "on" and not 0 < request.duration_seconds <= ACTUATORS[actuator]["max_seconds"]:
        raise HTTPException(400, "Duration exceeds the safety limit")
    recommendation_id = add_actuator_recommendation({
        "source": "manual_dashboard", "severity": "manual", "title": f"{ACTUATORS[actuator]['label']} 수동 제어 요청",
        "rationale": f"{request.operator}: {request.reason}", "actuator": actuator,
        "requested_state": request.state, "duration_seconds": request.duration_seconds,
        "evidence": {"operator": request.operator}, "model": None,
    })
    telegram_status = telegram_send_approval_requests([recommendation_id], context="수동 제어 요청")
    return {
        "id": recommendation_id,
        "status": "pending",
        "telegram_status": telegram_status,
        "message": "승인 대기열에 추가했습니다.",
    }


@app.get("/api/recommendations", dependencies=[Depends(require_auth)])
def recommendations() -> list[dict[str, Any]]:
    return store.recommendations()


@app.get("/api/actuator-events", dependencies=[Depends(require_auth)])
def actuator_events(limit: int = Query(100, ge=1, le=500)) -> list[dict[str, Any]]:
    return store.events(limit)


@app.post("/api/recommendations/{recommendation_id}/decision", dependencies=[Depends(require_auth)])
def decide(recommendation_id: int, request: DecisionRequest) -> dict[str, Any]:
    if telegram_config()["approval_enabled"]:
        raise HTTPException(409, "Final approvals are enabled only through Telegram")
    return decide_recommendation(recommendation_id, request.decision, request.operator, request.note)


@app.get("/api/cameras", dependencies=[Depends(require_auth)])
def cameras() -> dict[str, Any]:
    return camera_settings_payload()


@app.put(
    "/api/settings/cameras",
    dependencies=[Depends(require_auth), Depends(require_local_settings)],
)
def save_camera_settings(request: CameraSettingsRequest) -> dict[str, Any]:
    slots = [item.slot for item in request.cameras]
    if len(slots) != len(set(slots)):
        raise HTTPException(400, "Camera slots must be unique")
    values: dict[str, str] = {}
    for item in request.cameras:
        label = item.label.strip() or f"카메라 {item.slot}"
        url = item.snapshot_url.strip()
        username = item.username.strip()
        for value in (label, url, username, item.password or ""):
            if "\n" in value or "\r" in value:
                raise HTTPException(400, "Camera settings cannot contain line breaks")
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise HTTPException(400, f"CAM-{item.slot:02d} snapshot URL must use http or https")
            if parsed.username or parsed.password:
                raise HTTPException(400, f"CAM-{item.slot:02d} credentials must use the separate account fields")
        prefix = f"CAMERA_{item.slot}"
        values[f"{prefix}_LABEL"] = label
        values[f"{prefix}_SNAPSHOT_URL"] = url
        values[f"{prefix}_USERNAME"] = username
        password = item.password or ""
        if password or not url:
            values[f"{prefix}_PASSWORD"] = password
    update_env_file(values)
    return camera_settings_payload()


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


@app.post(
    "/api/workflows/telegram-daily-brief",
    dependencies=[Depends(require_auth), Depends(require_local_settings)],
)
def workflow_telegram_daily_brief() -> dict[str, Any]:
    """An explicit local test action; this sends a real Telegram message."""
    return telegram_daily_brief_job()


@app.get("/")
def dashboard(_auth: None = Depends(require_auth)) -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


app.mount("/fonts", StaticFiles(directory=BASE_DIR / "fonts"), name="fonts")
app.mount("/assets", StaticFiles(directory=BASE_DIR / "assets"), name="assets")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8765)
