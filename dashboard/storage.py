"""Small SQLite store used by the school-laptop dashboard."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sensor_readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at TEXT NOT NULL,
                    air_temp REAL,
                    humidity REAL,
                    co2 INTEGER,
                    scd40_temp REAL,
                    scd40_humidity REAL,
                    ec REAL,
                    ph REAL,
                    solution_temp REAL,
                    source TEXT NOT NULL,
                    raw_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sensor_recorded_at
                    ON sensor_readings(recorded_at);

                CREATE TABLE IF NOT EXISTS recommendations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    actuator TEXT,
                    requested_state TEXT,
                    duration_seconds INTEGER,
                    evidence_json TEXT NOT NULL,
                    model TEXT,
                    status TEXT NOT NULL,
                    decided_by TEXT,
                    decided_at TEXT,
                    execution_note TEXT
                );

                CREATE TABLE IF NOT EXISTS actuator_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    command_id TEXT NOT NULL,
                    actuator TEXT NOT NULL,
                    requested_state TEXT NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    result TEXT NOT NULL,
                    note TEXT
                );

                CREATE TABLE IF NOT EXISTS captures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    camera_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    path TEXT,
                    status TEXT NOT NULL,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    model TEXT NOT NULL,
                    capture_id INTEGER,
                    overall_status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS historical_operation_analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    title TEXT NOT NULL,
                    prompt_text TEXT NOT NULL,
                    input_text TEXT NOT NULL,
                    model TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_date TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    path TEXT NOT NULL,
                    model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    telegram_status TEXT
                );

                CREATE TABLE IF NOT EXISTS workflow_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT
                );

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            try:
                db.execute("ALTER TABLE historical_operation_analyses ADD COLUMN prompt_text TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError:
                pass

    @staticmethod
    def now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def add_sensor(self, payload: dict[str, Any], source: str) -> int:
        fields = (
            payload.get("air_temp"), payload.get("humidity"), payload.get("co2"),
            payload.get("scd40_temp"), payload.get("scd40_humidity"),
            payload.get("ec"), payload.get("ph"), payload.get("solution_temp"),
        )
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO sensor_readings (
                    recorded_at, air_temp, humidity, co2, scd40_temp,
                    scd40_humidity, ec, ph, solution_temp, source, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (self.now(), *fields, source, json.dumps(payload, ensure_ascii=False)),
            )
            return int(cursor.lastrowid)

    def add_imported_sensor(self, recorded_at: str, payload: dict[str, Any]) -> bool:
        """Store an Excel archive row without allowing it to affect live control."""
        source = "imported:excel"
        with self.connect() as db:
            existing = db.execute(
                "SELECT 1 FROM sensor_readings WHERE recorded_at = ? LIMIT 1",
                (recorded_at,),
            ).fetchone()
            if existing:
                return False
            fields = (
                payload.get("air_temp"), payload.get("humidity"), payload.get("co2"),
                payload.get("scd40_temp"), payload.get("scd40_humidity"),
                payload.get("ec"), payload.get("ph"), payload.get("solution_temp"),
            )
            db.execute(
                """INSERT INTO sensor_readings (
                    recorded_at, air_temp, humidity, co2, scd40_temp,
                    scd40_humidity, ec, ph, solution_temp, source, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (recorded_at, *fields, source, json.dumps(payload, ensure_ascii=False)),
            )
            return True

    def add_historical_operation_analysis(
        self, title: str, prompt_text: str, input_text: str, model: str, result: dict[str, Any],
    ) -> int:
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO historical_operation_analyses
                   (created_at, title, prompt_text, input_text, model, result_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (self.now(), title, prompt_text, input_text, model, json.dumps(result, ensure_ascii=False)),
            )
            return int(cursor.lastrowid)

    def historical_operation_analyses(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT id, created_at, title, model, result_json
                   FROM historical_operation_analyses
                   ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["result"] = json.loads(item.pop("result_json"))
            except (TypeError, ValueError, json.JSONDecodeError):
                item["result"] = {"headline": "저장된 분석 결과를 읽을 수 없습니다."}
            result.append(item)
        return result

    def latest_sensor(self) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM sensor_readings WHERE source != 'imported:excel' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def sensor_history(
        self, hours: int = 24, limit: int = 1600,
        start: datetime | None = None, end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return a chronological, display-sized sensor series for a time range."""
        end = end or datetime.now().astimezone()
        start = start or (end - timedelta(hours=hours))
        start_text = start.isoformat(timespec="seconds")
        end_text = end.isoformat(timespec="seconds")
        with self.connect() as db:
            rows = db.execute(
                """SELECT MIN(recorded_at) AS recorded_at,
                          AVG(air_temp) AS air_temp, AVG(humidity) AS humidity,
                          AVG(co2) AS co2, AVG(ec) AS ec, AVG(ph) AS ph,
                          AVG(solution_temp) AS solution_temp, MAX(source) AS source
                   FROM sensor_readings
                   WHERE recorded_at >= ? AND recorded_at <= ?
                   GROUP BY CAST(strftime('%s', recorded_at) / 3600 AS INTEGER)
                   ORDER BY recorded_at ASC""",
                (start_text, end_text),
            ).fetchall()
        return [dict(row) for row in rows]

    def day_stats(self, report_date: str) -> dict[str, dict[str, float | int] | None]:
        result: dict[str, dict[str, float | int] | None] = {}
        with self.connect() as db:
            for field in ("air_temp", "humidity", "co2", "ec", "ph", "solution_temp"):
                row = db.execute(
                    f"""SELECT COUNT({field}) AS count, AVG({field}) AS mean,
                               MIN({field}) AS minimum, MAX({field}) AS maximum,
                               MIN(recorded_at) AS first_at, MAX(recorded_at) AS last_at
                        FROM sensor_readings
                        WHERE substr(recorded_at, 1, 10) = ? AND {field} IS NOT NULL""",
                    (report_date,),
                ).fetchone()
                result[field] = dict(row) if row and row["count"] else None
        return result

    def day_source_label(self, report_date: str) -> str:
        with self.connect() as db:
            rows = db.execute(
                """SELECT DISTINCT source FROM sensor_readings
                   WHERE substr(recorded_at, 1, 10) = ?""",
                (report_date,),
            ).fetchall()
        sources = {str(row["source"]) for row in rows}
        if not sources:
            return "미수집"
        has_simulation = any(source.startswith("simulation") for source in sources)
        has_measured = any(source.startswith("measured") for source in sources)
        if has_simulation and has_measured:
            return "실측·모의 혼합"
        if has_simulation:
            return "모의 데이터(비실측)"
        if has_measured:
            return "RS485 실측 (Pico 2 W)"
        return "출처 확인 필요"

    def add_recommendation(self, item: dict[str, Any]) -> int:
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO recommendations (
                    created_at, source, severity, title, rationale, actuator,
                    requested_state, duration_seconds, evidence_json, model, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.now(), item.get("source", "rule"), item["severity"],
                    item["title"], item["rationale"], item.get("actuator"),
                    item.get("requested_state"), item.get("duration_seconds"),
                    json.dumps(item.get("evidence", {}), ensure_ascii=False),
                    item.get("model"), item.get("status", "pending"),
                ),
            )
            return int(cursor.lastrowid)

    def recommendations(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM recommendations ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            result.append(item)
        return result

    def recommendation(self, recommendation_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM recommendations WHERE id = ?", (recommendation_id,)
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["evidence"] = json.loads(item.pop("evidence_json"))
        return item

    def decide_recommendation(
        self, recommendation_id: int, status: str, operator: str, note: str
    ) -> None:
        with self.connect() as db:
            db.execute(
                """UPDATE recommendations
                   SET status = ?, decided_by = ?, decided_at = ?, execution_note = ?
                   WHERE id = ?""",
                (status, operator, self.now(), note, recommendation_id),
            )

    def add_event(self, event: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO actuator_events (
                    created_at, command_id, actuator, requested_state,
                    duration_seconds, source, result, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.now(), event["command_id"], event["actuator"],
                    event["requested_state"], event["duration_seconds"],
                    event["source"], event["result"], event.get("note"),
                ),
            )

    def events(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM actuator_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def day_events(self, report_date: str) -> list[dict[str, Any]]:
        """Return the complete local-day actuator audit trail for a report."""
        with self.connect() as db:
            rows = db.execute(
                """SELECT * FROM actuator_events
                   WHERE substr(created_at, 1, 10) = ?
                   ORDER BY id ASC""",
                (report_date,),
            ).fetchall()
        return [dict(row) for row in rows]

    def nearest_sensor_reading(
        self, target: datetime, *, direction: str, maximum_offset_seconds: int = 180,
    ) -> dict[str, Any] | None:
        """Return the closest non-imported measured row immediately before or after target."""
        if direction not in {"before", "after"}:
            raise ValueError("direction must be before or after")
        target_text = target.isoformat(timespec="seconds")
        boundary = (target - timedelta(seconds=maximum_offset_seconds) if direction == "before"
                    else target + timedelta(seconds=maximum_offset_seconds)).isoformat(timespec="seconds")
        comparator, order = (">= ? AND recorded_at <= ?", "DESC") if direction == "before" else (">= ? AND recorded_at <= ?", "ASC")
        values = (boundary, target_text) if direction == "before" else (target_text, boundary)
        with self.connect() as db:
            row = db.execute(
                f"""SELECT recorded_at, air_temp, humidity, co2, ec, ph, solution_temp, source
                    FROM sensor_readings
                    WHERE source != 'imported:excel' AND recorded_at {comparator}
                    ORDER BY recorded_at {order} LIMIT 1""",
                values,
            ).fetchone()
        return dict(row) if row else None

    def add_capture(self, camera_id: str, path: str | None, status: str, error: str | None) -> int:
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO captures (camera_id, captured_at, path, status, error) VALUES (?, ?, ?, ?, ?)",
                (camera_id, self.now(), path, status, error),
            )
            return int(cursor.lastrowid)

    def captures(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM captures ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def add_analysis(self, item: dict[str, Any]) -> int:
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO analyses (
                    created_at, model, capture_id, overall_status, summary,
                    confidence, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.now(), item["model"], item.get("capture_id"),
                    item["overall_status"], item["summary"], item["confidence"],
                    json.dumps(item, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def analyses(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM analyses ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["result"] = json.loads(item.pop("result_json"))
            result.append(item)
        return result

    def add_report(self, item: dict[str, Any]) -> int:
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO reports (
                    report_date, created_at, path, model, status, telegram_status
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    item["report_date"], self.now(), item["path"], item["model"],
                    item.get("status", "created"), item.get("telegram_status"),
                ),
            )
            return int(cursor.lastrowid)

    def reports(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM reports ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def workflow(self, name: str, status: str, detail: str = "") -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO workflow_runs (created_at, workflow, status, detail) VALUES (?, ?, ?, ?)",
                (self.now(), name, status, detail),
            )

    def workflows(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM workflow_runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def setting(self, key: str, default: str | None = None) -> str | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT value FROM app_settings WHERE key = ?",
                (key,),
            ).fetchone()
        return str(row["value"]) if row else default

    def set_settings(self, values: dict[str, str]) -> None:
        updated_at = self.now()
        with self.connect() as db:
            db.executemany(
                """INSERT INTO app_settings (key, value, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                       value = excluded.value,
                       updated_at = excluded.updated_at""",
                [(key, value, updated_at) for key, value in values.items()],
            )
