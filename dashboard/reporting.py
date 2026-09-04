"""Generate a restrained two-page daily broccoli PDF report."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


DISCLAIMER = (
    "본 보고서는 영상 및 센서 데이터에 기반한 생육 의사결정 지원 자료이며, "
    "병해충과 생리장해의 확정 진단을 대체하지 않는다."
)

# These names are retained in a few historical database/MQTT compatibility
# columns, but they are not part of the installed sensor system any more.
# Never let a model echo those empty compatibility fields into a human report.
_LEGACY_SENSOR_TEXT = re.compile(r"(?:i2c|aht\d*|scd\d*|bh1750|null|none)", re.IGNORECASE)
RS485_SENSOR_SYSTEM = "RS485 Modbus RTU · SHTC3 온습도 · KCD-HP100 CO₂ · SenseCube PE350 EC/pH·양액온도"


def report_text(value: Any, fallback: str = "") -> str:
    """Keep report prose human-readable and limited to the installed sensors."""
    text = " ".join(str(value or "").split())
    if not text or _LEGACY_SENSOR_TEXT.search(text):
        return fallback
    return text


def register_korean_font(base_dir: Path) -> str:
    candidates = (
        ("Gulim", Path("C:/Windows/Fonts/gulim.ttc")),
        ("DashboardKorean", base_dir / "fonts" / "a2z-regular.ttf"),
    )
    for name, path in candidates:
        if not path.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont(name, str(path)))
            return name
        except Exception:
            continue
    return "Helvetica"


def metric_text(stats: dict[str, Any] | None, digits: int, unit: str) -> str:
    if not stats:
        return "미수집"
    return (
        f"{stats['mean']:.{digits}f} "
        f"({stats['minimum']:.{digits}f}~{stats['maximum']:.{digits}f}) {unit}"
    )


def status_for(value: float | None, low: float, high: float) -> str:
    if value is None:
        return "판단 불가"
    return "정상" if low <= value <= high else "주의"


def effect_metric(snapshot: dict[str, Any] | None, key: str, digits: int, unit: str) -> str:
    if not snapshot or snapshot.get(key) is None:
        return "미수집"
    return f"{float(snapshot[key]):.{digits}f}{unit}"


def effect_time_and_source(snapshot: dict[str, Any] | None) -> str:
    if not snapshot:
        return "미수집"
    recorded_at = str(snapshot.get("recorded_at") or "")[:19].replace("T", " ")
    source = str(snapshot.get("source") or "출처 확인 필요")
    if source.startswith("measured"):
        source = "실측"
    elif source.startswith("simulation"):
        source = "모의"
    return f"{recorded_at} · {source}"


def signed_change(value: float | None, digits: int, unit: str) -> str:
    if value is None:
        return "산출 불가"
    return f"{value:+.{digits}f}{unit} (계산)"


def generate_daily_pdf(
    output_path: Path,
    report_date: str,
    stats: dict[str, dict[str, Any] | None],
    analysis: dict[str, Any] | None,
    captures: list[dict[str, Any]] | None,
    model: str,
    data_source: str,
    base_dir: Path,
    actuator_events: list[dict[str, Any]] | None = None,
    intervention_effects: list[dict[str, Any]] | None = None,
    growth_stage: str = "육묘기",
    management_profile: dict[str, float] | None = None,
    growth_score: dict[str, Any] | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    font = register_korean_font(base_dir)
    styles = getSampleStyleSheet()
    normal = ParagraphStyle(
        "KoreanNormal", parent=styles["Normal"], fontName=font,
        fontSize=9.5, leading=15, textColor=colors.black,
    )
    title = ParagraphStyle(
        "KoreanTitle", parent=normal, fontSize=21, leading=28,
        alignment=TA_CENTER, spaceAfter=10 * mm,
    )
    section = ParagraphStyle(
        "KoreanSection", parent=normal, fontSize=12, leading=18,
        spaceBefore=5 * mm, spaceAfter=2 * mm,
    )
    small = ParagraphStyle("KoreanSmall", parent=normal, fontSize=8, leading=12)

    doc = SimpleDocTemplate(
        str(output_path), pagesize=A4,
        rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"브로콜리 AI 일일 생육관찰 보고서 {report_date}",
    )
    story = [Paragraph("브로콜리 AI 일일 생육관찰 보고서", title)]

    metadata = [
        ["보고 기준일", report_date, "작물", "브로콜리"],
        ["담당", "이은성 · 김태현", "확인", "유혜진 (인)"],
        ["분석 모델", model, "데이터 구분", f"{data_source} · AI 관찰"],
        ["센서 통신", "RS485 Modbus RTU", "실측 장치", "SHTC3 · KCD-HP100 · PE350"],
        ["생성 시각", datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"), "승인 상태", "사람 검토 대기"],
    ]
    meta_table = Table(metadata, colWidths=[28 * mm, 60 * mm, 28 * mm, 60 * mm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.7, colors.black),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eeeeee")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#eeeeee")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (2, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([meta_table, Paragraph("1. 금일 종합 판정", section)])

    if analysis:
        overall = analysis.get("result", analysis).get("overall_status", "판단 불가")
        summary = report_text(
            analysis.get("result", analysis).get("summary"),
            "당일 카메라 영상과 RS485 실측값을 기준으로 생육 상태를 검토했습니다.",
        )
        confidence = analysis.get("result", analysis).get("confidence", "낮음")
    else:
        overall, summary, confidence = "판단 불가", "당일 AI 분석 기록이 없습니다.", "낮음"
    profile = management_profile or {
        "ec_low": 1.0, "ec_target": 1.3, "ec_high": 1.5,
        "ph_low": 5.8, "ph_target": 6.0, "ph_high": 6.2,
        "temp_low": 15.0, "temp_target": 19.0, "temp_high": 22.0,
        "humidity_low": 60.0, "humidity_target": 68.0, "humidity_high": 75.0,
    }
    score = growth_score or {}
    score_value = score.get("score")
    score_text = f"{score_value}/100 · {score.get('status', '판단 불가')}" if score_value is not None else "산출 불가 · 실측 근거 확인 필요"
    score_reasons = " / ".join(str(item) for item in score.get("reasons", [])[:2]) or "근거 미입력"
    story.append(Table(
        [
            ["관리 환경 점수", score_text], ["점수 근거", Paragraph(score_reasons, normal)],
            ["종합 상태", overall], ["생육 단계", growth_stage], ["분석 요약", Paragraph(summary, normal)], ["확신도", confidence],
        ],
        colWidths=[30 * mm, 146 * mm],
        style=TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.7, colors.black),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eeeeee")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]),
    ))

    story.append(Paragraph("2. RS485 실측 환경 데이터 자동 판정", section))
    sensor_rows = [["항목", f"일평균 (최소~최대) · {data_source}", f"{growth_stage} 관리 기준", "판정"]]
    definitions = (
        ("EC", "ec", 2, "dS/m", profile["ec_low"], profile["ec_target"], profile["ec_high"]),
        ("pH", "ph", 2, "pH", profile["ph_low"], profile["ph_target"], profile["ph_high"]),
        ("기온", "air_temp", 1, "℃", profile["temp_low"], profile["temp_target"], profile["temp_high"]),
        ("습도", "humidity", 1, "%", profile["humidity_low"], profile["humidity_target"], profile["humidity_high"]),
        ("CO₂", "co2", 0, "ppm", 350.0, 800.0, 1500.0),
    )
    for label, key, digits, unit, low, target, high in definitions:
        item = stats.get(key)
        mean = float(item["mean"]) if item else None
        sensor_rows.append([
            label, metric_text(item, digits, unit), f"{low:g}~{high:g} (목표 {target:g}) {unit}",
            status_for(mean, low, high),
        ])
    sensor_table = Table(sensor_rows, colWidths=[23 * mm, 70 * mm, 48 * mm, 35 * mm])
    sensor_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.7, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([sensor_table, Spacer(1, 5 * mm), Paragraph(DISCLAIMER, small), PageBreak()])

    story.extend([Paragraph("3. 3대 카메라 영상 근거 및 AI 종합 관찰", section)])
    image_cells = []
    for capture in captures or []:
        path = Path(str(capture.get("path") or ""))
        if not path.exists():
            continue
        try:
            image = Image(str(path))
            # A compact evidence strip keeps the daily report to two readable pages
            # when actuator-effect cards are present below.
            max_width, max_height = 52 * mm, 30 * mm
            scale = min(max_width / image.imageWidth, max_height / image.imageHeight)
            image.drawWidth = image.imageWidth * scale
            image.drawHeight = image.imageHeight * scale
            label = str(capture.get("camera_id") or "카메라")
            captured_at = str(capture.get("captured_at") or "")[:19].replace("T", " ")
            image_cells.append([Paragraph(f"{label}<br/>{captured_at}", small), Spacer(1, 1 * mm), image])
        except Exception:
            continue
    if image_cells:
        while len(image_cells) < 3:
            image_cells.append(Paragraph("해당 카메라 영상 없음", small))
        image_table = Table([image_cells[:3]], colWidths=[58 * mm, 58 * mm, 58 * mm])
        image_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#bbbbbb")),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.extend([image_table, Spacer(1, 3 * mm)])
    else:
        story.append(Paragraph("당일 사용 가능한 카메라 이미지가 없어 영상 판정은 수행하지 않았습니다.", normal))

    observations = []
    limitations = []
    if analysis:
        result = analysis.get("result", analysis)
        observations = [report_text(value) for value in result.get("observations", [])]
        limitations = [report_text(value) for value in result.get("limitations", [])]
        observations = [value for value in observations if value]
        limitations = [value for value in limitations if value]
    evidence_rows = [["구분", "기록"]]
    evidence_rows.extend([["AI 관찰", Paragraph(str(value), normal)] for value in observations[:2]])
    evidence_rows.extend([["분석 한계", Paragraph(str(value), normal)] for value in limitations[:2]])
    if len(evidence_rows) == 1:
        evidence_rows.append(["판단 불가", "영상 분석 기록 없음"])
    evidence_table = Table(evidence_rows, colWidths=[30 * mm, 146 * mm])
    evidence_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.7, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(evidence_table)

    story.append(Paragraph("4. 조치 효과 카드 - 전후 센서 실측", section))
    actuator_labels = {
        "led": "LED", "raw_water": "원수", "supply": "양액 공급",
        "mixing": "교반", "ec": "A+B 양액펌프", "ph": "pH 산성액펌프", "fan": "환풍기",
    }
    result_labels = {
        "requested": "요청", "approved": "승인", "rejected": "거절", "blocked": "안전 차단",
        "sent": "Pico 전송", "pico_ack": "Pico 확인", "pico_timeout": "시간 종료", "pico_error": "Pico 오류",
        "failed": "전송 실패", "simulated": "잠금·모의", "session_started": "보정 시작",
        "target_reached": "목표 도달", "session_limit": "횟수 제한", "session_blocked": "세션 중단",
        "safety_stop": "안전 중단", "superseded": "정책 교체", "safety_stopped": "안전 중단",
        "deferred": "보정 대기",
    }
    events = actuator_events or []
    effects = intervention_effects or []
    if effects:
        story.append(Paragraph(
            "조치 전후의 가장 가까운 센서 실측값을 비교한 기록입니다. 변화의 원인을 단정하지 않으며, "
            "센서 지연 또는 동시 조치가 있으면 현장 검토가 필요합니다.", small,
        ))
        # Keep the established two-page daily report readable. The complete
        # actuator audit trail remains in SQLite; the PDF carries recent evidence.
        # The latest complete intervention is printed as a full evidence card.
        # Older cards stay in the audit database so that the daily report remains
        # a practical two-page handout.
        for effect in effects[-1:]:
            actuator = str(effect.get("actuator") or "")
            label = actuator_labels.get(actuator, actuator or "조치")
            started = str(effect.get("started_at") or "")[:19].replace("T", " ")
            pulses = int(effect.get("pulse_count") or 0)
            seconds = int(effect.get("total_seconds") or 0)
            action_detail = f"{label} · {started} · {pulses}회 / 총 {seconds}초"
            before = effect.get("before")
            after = effect.get("after")
            card_rows = [
                [Paragraph(f"<b>{action_detail}</b>", normal), "", "", ""],
                ["구분", "pH", "EC", "시각 · 데이터 출처"],
                ["조치 전 (실측)", effect_metric(before, "ph", 2, ""), effect_metric(before, "ec", 3, " dS/m"), effect_time_and_source(before)],
                ["조치 후 (실측)", effect_metric(after, "ph", 2, ""), effect_metric(after, "ec", 3, " dS/m"), effect_time_and_source(after)],
                ["변화", signed_change(effect.get("ph_change"), 2, ""), signed_change(effect.get("ec_change"), 3, " dS/m"), Paragraph(str(effect.get("observation_note") or "판단 불가"), small)],
            ]
            card = Table(card_rows, colWidths=[34 * mm, 30 * mm, 36 * mm, 76 * mm])
            card.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("SPAN", (0, 0), (-1, 0)),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf2fb")),
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#dddddd")),
                ("BACKGROUND", (0, 4), (-1, 4), colors.HexColor("#f7f7f7")),
                ("GRID", (0, 1), (-1, -1), 0.55, colors.HexColor("#999999")),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#777777")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 1), (2, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.extend([card, Spacer(1, 3 * mm)])
    else:
        story.append(Paragraph("당일 조치와 연결할 전후 실측 센서 기록이 없습니다.", normal))
    if events:
        result_counts: dict[str, int] = {}
        for event in events:
            result = result_labels.get(str(event.get("result")), str(event.get("result") or "기록"))
            result_counts[result] = result_counts.get(result, 0) + 1
        summary = " · ".join(f"{label} {count}건" for label, count in sorted(result_counts.items()))
        story.append(Paragraph(f"금일 제어 감사 기록 {len(events)}건은 서버 DB에 전체 보존되었습니다. 요약: {summary}", small))
    else:
        story.append(Paragraph("당일 기록된 액추에이터 요청·승인·전송·응답 이력이 없습니다.", normal))

    story.extend([
        Paragraph("5. 현장 확인 및 승인", section),
        Paragraph("□ 잎 뒷면 및 생장점 육안 점검　□ 뿌리·양액 순환 점검　□ AI 제안 승인/거절 기록", normal),
        Spacer(1, 8 * mm),
        Table(
            [["사람 판단", "□ 일치　□ 일부 일치　□ 불일치", "확인자", "유혜진 (인)"]],
            colWidths=[28 * mm, 70 * mm, 28 * mm, 50 * mm],
            style=TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.7, colors.black),
                ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#eeeeee")),
                ("BACKGROUND", (2, 0), (2, 0), colors.HexColor("#eeeeee")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]),
        ),
        Spacer(1, 8 * mm),
        Paragraph(DISCLAIMER, small),
    ])

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.drawCentredString(A4[0] / 2, 9 * mm, f"- {document.page} -")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
