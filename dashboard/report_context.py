"""Auditable 24-hour context for the noon broccoli report."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import fmean, pstdev
from typing import Any
from zoneinfo import ZoneInfo


SEOUL = ZoneInfo("Asia/Seoul")
PROMPT_VERSION = "bone-daily-integrated-v2.0"

METRICS = {
    "ec": {"label": "EC", "unit": "dS/m", "digits": 3, "plausible": (0.1, 10.0)},
    "ph": {"label": "pH", "unit": "", "digits": 2, "plausible": (2.0, 12.0)},
    "air_temp": {"label": "기온", "unit": "℃", "digits": 1, "plausible": (-20.0, 60.0)},
    "humidity": {"label": "습도", "unit": "%", "digits": 1, "plausible": (0.1, 100.0)},
    "co2": {"label": "CO₂", "unit": "ppm", "digits": 0, "plausible": (100.0, 10000.0)},
    "solution_temp": {"label": "양액온도", "unit": "℃", "digits": 1, "plausible": (0.0, 60.0)},
}


def report_window(report_date: str) -> tuple[datetime, datetime]:
    end = datetime.fromisoformat(report_date).replace(hour=12, tzinfo=SEOUL)
    return end - timedelta(hours=24), end


def previous_window(report_date: str) -> tuple[datetime, datetime]:
    start, _ = report_window(report_date)
    return start - timedelta(hours=24), start


def iso_seconds(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _valid_values(rows: list[dict[str, Any]], key: str) -> tuple[list[float], int]:
    low, high = METRICS[key]["plausible"]
    values: list[float] = []
    excluded = 0
    for row in rows:
        raw = row.get(key)
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            excluded += 1
            continue
        if low <= value <= high:
            values.append(value)
        else:
            excluded += 1
    return values, excluded


def summarize_window(
    rows: list[dict[str, Any]], profile: dict[str, float],
) -> dict[str, Any]:
    targets = {
        "ec": (profile["ec_low"], profile["ec_target"], profile["ec_high"]),
        "ph": (profile["ph_low"], profile["ph_target"], profile["ph_high"]),
        "air_temp": (profile["temp_low"], profile["temp_target"], profile["temp_high"]),
        "humidity": (profile["humidity_low"], profile["humidity_target"], profile["humidity_high"]),
        "co2": (350.0, 800.0, 1500.0),
        "solution_temp": (16.0, 20.0, 24.0),
    }
    metrics: dict[str, Any] = {}
    for key, spec in METRICS.items():
        values, excluded = _valid_values(rows, key)
        if not values:
            metrics[key] = None
            continue
        low, target, high = targets[key]
        in_range = sum(low <= value <= high for value in values)
        ratio = in_range / len(values) * 100.0
        mean = fmean(values)
        if ratio >= 95:
            status = "안정"
        elif ratio >= 75:
            status = "관찰"
        else:
            status = "조정 검토"
        metrics[key] = {
            "label": spec["label"], "unit": spec["unit"], "digits": spec["digits"],
            "count": len(values), "excluded": excluded,
            "mean": mean, "minimum": min(values), "maximum": max(values),
            "stddev": pstdev(values) if len(values) > 1 else 0.0,
            "first": values[0], "last": values[-1], "change": values[-1] - values[0],
            "low": low, "target": target, "high": high,
            "in_range_count": in_range, "in_range_pct": ratio,
            "status": status,
        }

    hourly: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        stamp = str(row.get("recorded_at") or "")[:13] + ":00"
        if len(stamp) < 13:
            continue
        for key in METRICS:
            raw = row.get(key)
            if raw is None:
                continue
            low, high = METRICS[key]["plausible"]
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if low <= value <= high:
                hourly[stamp][key].append(value)
    series = []
    for stamp in sorted(hourly):
        point: dict[str, Any] = {"recorded_at": stamp}
        for key, values in hourly[stamp].items():
            point[key] = fmean(values)
        series.append(point)

    source_counts: dict[str, int] = {}
    for row in rows:
        source = str(row.get("source") or "미입력")
        source_counts[source] = source_counts.get(source, 0) + 1
    return {
        "row_count": len(rows),
        "first_at": rows[0].get("recorded_at") if rows else None,
        "last_at": rows[-1].get("recorded_at") if rows else None,
        "source_counts": source_counts,
        "metrics": metrics,
        "hourly": series,
    }


def add_previous_comparison(current: dict[str, Any], previous: dict[str, Any]) -> None:
    previous_metrics = previous.get("metrics") or {}
    for key, item in (current.get("metrics") or {}).items():
        before = previous_metrics.get(key)
        if item and before:
            item["previous_mean"] = before["mean"]
            item["mean_change"] = item["mean"] - before["mean"]
        elif item:
            item["previous_mean"] = None
            item["mean_change"] = None


def _fit(value: float, low: float, target: float, high: float) -> float:
    if low <= value <= high:
        edge = low if value <= target else high
        span = max(abs(target - edge), 1e-9)
        return 75.0 + 25.0 * (1.0 - abs(value - target) / span)
    span = max(high - low, 1e-9)
    distance = low - value if value < low else value - high
    return max(0.0, 75.0 * (1.0 - distance / span))


def report_management_score(
    window: dict[str, Any], growth_stage: str, profile: dict[str, float],
    *, analysis_available: bool, camera_count: int,
) -> dict[str, Any]:
    specs = (
        ("ec", 20.0), ("ph", 15.0), ("air_temp", 12.0),
        ("humidity", 10.0), ("co2", 8.0),
    )
    components = []
    total = 0.0
    missing = []
    for key, weight in specs:
        item = (window.get("metrics") or {}).get(key)
        if not item:
            missing.append(METRICS[key]["label"])
            components.append({"key": key, "label": METRICS[key]["label"], "points": 0.0, "out_of": weight, "detail": "실측값 없음"})
            continue
        points = weight * _fit(item["last"], item["low"], item["target"], item["high"]) / 100.0
        total += points
        components.append({
            "key": key, "label": item["label"], "points": round(points, 1), "out_of": weight,
            "detail": f"최근 {item['last']:.{item['digits']}f}{item['unit']} · 24시간 범위내 {item['in_range_pct']:.1f}%",
        })

    stability_specs = {"ec": 0.25, "ph": 0.20, "air_temp": 3.0, "humidity": 10.0, "co2": 350.0}
    stability = 0.0
    stability_detail = []
    for key, allowed_range in stability_specs.items():
        item = (window.get("metrics") or {}).get(key)
        if not item:
            continue
        observed = item["maximum"] - item["minimum"]
        metric_score = max(0.0, 1.0 - observed / max(allowed_range * 2.0, 1e-9))
        stability += 4.0 * metric_score
        stability_detail.append(f"{item['label']} 변동폭 {observed:.{item['digits']}f}{item['unit']}")
    total += stability
    components.append({
        "key": "stability", "label": "24시간 변동 안정성", "points": round(stability, 1), "out_of": 20.0,
        "detail": " · ".join(stability_detail),
    })

    valid_metrics = sum(bool((window.get("metrics") or {}).get(key)) for key, _ in specs)
    evidence = (5.0 if valid_metrics == 5 and window.get("row_count", 0) >= 100 else 0.0)
    evidence += 4.0 if window.get("first_at") and window.get("last_at") else 0.0
    evidence += 3.0 if camera_count >= 3 else float(camera_count)
    evidence += 3.0 if analysis_available else 0.0
    total += evidence
    components.append({
        "key": "evidence", "label": "근거 품질", "points": round(evidence, 1), "out_of": 15.0,
        "detail": f"실측 {window.get('row_count', 0):,}행 · 카메라 {camera_count}대 · AI 통합분석 {'있음' if analysis_available else '없음'}",
    })
    score = None if missing else int(round(total))
    if score is None:
        status = "판단 불가"
    elif score >= 90:
        status = "매우 좋음"
    elif score >= 80:
        status = "좋음"
    elif score >= 70:
        status = "보통"
    elif score >= 60:
        status = "관찰 필요"
    elif score >= 50:
        status = "주의"
    else:
        status = "위험"
    return {
        "name": "관리 환경 점수", "score": score, "status": status, "stage": growth_stage,
        "components": components, "missing": missing, "source": "24시간 RS485 실측·카메라·AI 통합 근거",
    }


def report_context_for_ai(
    report_date: str,
    window: dict[str, Any],
    previous: dict[str, Any],
    growth_stage: str,
    profile: dict[str, float],
    recommendations: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    metric_context = {}
    for key, item in (window.get("metrics") or {}).items():
        if not item:
            metric_context[key] = None
            continue
        metric_context[key] = {
            name: item.get(name) for name in (
                "mean", "minimum", "maximum", "stddev", "change", "count", "excluded",
                "low", "target", "high", "in_range_pct", "previous_mean", "mean_change", "status",
            )
        }
    return {
        "report_date": report_date,
        "analysis_window": {"start": window.get("window_start"), "end": window.get("window_end")},
        "growth_stage_used": growth_stage,
        "management_profile": profile,
        "sensor_rows": window.get("row_count"),
        "sensor_first_at": window.get("first_at"),
        "sensor_last_at": window.get("last_at"),
        "sensor_sources": window.get("source_counts"),
        "metrics": metric_context,
        "previous_window_rows": previous.get("row_count"),
        "recommendations": [
            {
                "title": item.get("title"), "severity": item.get("severity"),
                "status": item.get("status"), "rationale": item.get("rationale"),
                "actuator": item.get("actuator"), "duration_seconds": item.get("duration_seconds"),
            }
            for item in recommendations[-12:]
        ],
        "actuator_events": [
            {
                "created_at": item.get("created_at"), "actuator": item.get("actuator"),
                "duration_seconds": item.get("duration_seconds"), "source": item.get("source"),
                "result": item.get("result"), "note": item.get("note"),
            }
            for item in events[-30:]
        ],
    }
