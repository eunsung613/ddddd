"""Generate a restrained two-page daily broccoli PDF report."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
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


def generate_daily_pdf(
    output_path: Path,
    report_date: str,
    stats: dict[str, dict[str, Any] | None],
    analysis: dict[str, Any] | None,
    capture_path: Path | None,
    model: str,
    data_source: str,
    base_dir: Path,
    actuator_events: list[dict[str, Any]] | None = None,
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
        summary = analysis.get("result", analysis).get("summary", "AI 분석 내용 없음")
        confidence = analysis.get("result", analysis).get("confidence", "낮음")
    else:
        overall, summary, confidence = "판단 불가", "당일 AI 분석 기록이 없습니다.", "낮음"
    story.append(Table(
        [["종합 상태", overall], ["분석 요약", Paragraph(summary, normal)], ["확신도", confidence]],
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

    story.append(Paragraph("2. 환경 데이터 자동 판정", section))
    sensor_rows = [["항목", f"일평균 (최소~최대) · {data_source}", "관리 기준", "판정"]]
    definitions = (
        ("EC", "ec", 2, "dS/m", 1.5, 2.0),
        ("pH", "ph", 2, "pH", 5.5, 6.5),
        ("기온", "air_temp", 1, "℃", 18.0, 25.0),
        ("습도", "humidity", 1, "%", 60.0, 80.0),
        ("CO₂", "co2", 0, "ppm", 350.0, 1500.0),
    )
    for label, key, digits, unit, low, high in definitions:
        item = stats.get(key)
        mean = float(item["mean"]) if item else None
        sensor_rows.append([
            label, metric_text(item, digits, unit), f"{low:g}~{high:g} {unit}",
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

    story.extend([Paragraph("3. 카메라 영상 근거 및 AI 관찰", section)])
    if capture_path and capture_path.exists():
        image = Image(str(capture_path))
        max_width, max_height = 170 * mm, 95 * mm
        scale = min(max_width / image.imageWidth, max_height / image.imageHeight)
        image.drawWidth = image.imageWidth * scale
        image.drawHeight = image.imageHeight * scale
        story.extend([image, Spacer(1, 3 * mm)])
    else:
        story.append(Paragraph("당일 사용 가능한 카메라 이미지가 없어 영상 판정은 수행하지 않았습니다.", normal))

    observations = []
    limitations = []
    if analysis:
        result = analysis.get("result", analysis)
        observations = result.get("observations", [])
        limitations = result.get("limitations", [])
    evidence_rows = [["구분", "기록"]]
    evidence_rows.extend([["AI 관찰", Paragraph(str(value), normal)] for value in observations])
    evidence_rows.extend([["분석 한계", Paragraph(str(value), normal)] for value in limitations])
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

    story.append(Paragraph("4. 액추에이터 제어 감사 기록", section))
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
    if events:
        event_rows = [["시각", "장치·명령", "결과", "기록 근거"]]
        for event in events:
            state = "ON" if event.get("requested_state") == "on" else "OFF"
            duration = int(event.get("duration_seconds") or 0)
            action = f"{actuator_labels.get(str(event.get('actuator')), event.get('actuator', '-'))} · {state}"
            if duration:
                action += f" · {duration}초"
            result = result_labels.get(str(event.get("result")), str(event.get("result") or "기록"))
            source = str(event.get("source") or "-")
            note = str(event.get("note") or "-")
            event_rows.append([
                str(event.get("created_at") or "-")[:19].replace("T", " "),
                Paragraph(action, small),
                Paragraph(result, small),
                Paragraph(f"{source}<br/>{note}", small),
            ])
        event_table = Table(event_rows, colWidths=[31 * mm, 42 * mm, 27 * mm, 76 * mm], repeatRows=1)
        event_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(event_table)
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
