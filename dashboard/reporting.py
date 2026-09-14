"""Create a polished, evidence-linked BONE broccoli daily report."""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from PIL import Image as PILImage, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


DISCLAIMER = (
    "본 보고서는 영상 및 센서 데이터에 기반한 생육 의사결정 지원 자료이며, "
    "병해충과 생리장해의 확정 진단을 대체하지 않는다."
)
NAVY = colors.HexColor("#12385B")
BLUE = colors.HexColor("#1769E0")
PALE_BLUE = colors.HexColor("#EEF5FF")
PALE_GREEN = colors.HexColor("#ECF8F3")
PALE_GRAY = colors.HexColor("#F5F7FA")
LINE = colors.HexColor("#D6E0EA")
TEXT = colors.HexColor("#20364A")
MUTED = colors.HexColor("#637588")

SENSOR_META = (
    ("SHTC3 온·습도", "국번 1", "9600 bps", "기온·습도"),
    ("KCD-HP100 CO₂", "국번 31", "38400 bps", "CO₂"),
    ("SenseCube PE350", "국번 21", "9600 bps", "EC·pH·양액온도"),
)


def register_korean_font(base_dir: Path) -> tuple[str, str]:
    regular = Path("C:/Windows/Fonts/malgun.ttf")
    bold = Path("C:/Windows/Fonts/malgunbd.ttf")
    if regular.exists() and bold.exists():
        pdfmetrics.registerFont(TTFont("BONERegular", str(regular)))
        pdfmetrics.registerFont(TTFont("BONEBold", str(bold)))
        return "BONERegular", "BONEBold"
    fallback = base_dir / "fonts" / "a2z-regular.ttf"
    if fallback.exists():
        pdfmetrics.registerFont(TTFont("BONERegular", str(fallback)))
        return "BONERegular", "BONERegular"
    return "Helvetica", "Helvetica-Bold"


def _safe(value: Any, fallback: str = "미입력") -> str:
    text = " ".join(str(value or "").split())
    return text if text else fallback


def _fmt(value: Any, digits: int = 1, unit: str = "") -> str:
    if value is None:
        return "미수집"
    return f"{float(value):.{digits}f}{unit}"


def _table(data, widths, font: str, bold: str, *, header=True, size=7.7, aligns=None):
    normal = ParagraphStyle("tb", fontName=font, fontSize=size, leading=size + 3.2, textColor=TEXT, wordWrap="CJK")
    center = ParagraphStyle("tc", parent=normal, alignment=TA_CENTER)
    head = ParagraphStyle("th", parent=center, fontName=bold, textColor=colors.white)
    rows = []
    for r, row in enumerate(data):
        cells = []
        for c, value in enumerate(row):
            style = head if header and r == 0 else (center if aligns and aligns[c] == "center" else normal)
            cells.append(Paragraph(_safe(value, "-"), style))
        rows.append(cells)
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign="CENTER")
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.45, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        commands.append(("BACKGROUND", (0, 0), (-1, 0), NAVY))
        for r in range(1, len(rows)):
            commands.append(("BACKGROUND", (0, r), (-1, r), colors.white if r % 2 else PALE_GRAY))
    table.setStyle(TableStyle(commands))
    return table


def _fit_image(path: Path, max_w: float, max_h: float) -> Image:
    with PILImage.open(path) as im:
        w, h = im.size
    scale = min(max_w / w, max_h / h)
    return Image(str(path), width=w * scale, height=h * scale)


def _chart_image(summary: dict[str, Any], font_path: Path) -> Path | None:
    series = list(summary.get("hourly") or [])
    if len(series) < 2:
        return None
    width, height = 1500, 850
    canvas = PILImage.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(str(font_path), 24) if font_path.exists() else ImageFont.load_default()
    small = ImageFont.truetype(str(font_path), 19) if font_path.exists() else ImageFont.load_default()
    metrics = [
        ("air_temp", "기온 ℃", "#2878D0"), ("humidity", "습도 %", "#139A78"),
        ("co2", "CO₂ ppm", "#7C62D6"), ("ec", "EC dS/m", "#D48718"), ("ph", "pH", "#C34B65"),
    ]
    left, right, top, panel_h = 150, 45, 50, 145
    for index, (key, label, color) in enumerate(metrics):
        y0, y1 = top + index * panel_h, top + index * panel_h + 105
        values = [point.get(key) for point in series]
        valid = [float(v) for v in values if v is not None]
        if not valid:
            draw.text((25, y0 + 35), label + " · 미수집", fill="#637588", font=font)
            continue
        item = (summary.get("metrics") or {}).get(key) or {}
        lo = min(valid + [float(item.get("low", min(valid)))])
        hi = max(valid + [float(item.get("high", max(valid)))])
        pad = max((hi - lo) * 0.15, 0.1)
        lo, hi = lo - pad, hi + pad
        x_positions = [left + i * (width - left - right) / max(len(series) - 1, 1) for i in range(len(series))]
        sy = lambda v: y1 - (float(v) - lo) / max(hi - lo, 1e-9) * (y1 - y0)
        if item:
            draw.rectangle((left, sy(item["high"]), width - right, sy(item["low"])), fill="#EAF6F0")
            draw.line((left, sy(item["target"]), width - right, sy(item["target"])), fill="#8ACBB5", width=2)
        for grid in range(3):
            gy = y0 + grid * (y1 - y0) / 2
            draw.line((left, gy, width - right, gy), fill="#E3E8EE", width=1)
        points = [(x_positions[i], sy(v)) for i, v in enumerate(values) if v is not None]
        if len(points) >= 2:
            draw.line(points, fill=color, width=4)
        draw.text((25, y0 + 28), label, fill="#20364A", font=font)
        draw.text((25, y0 + 64), f"{hi:.2g}", fill="#637588", font=small)
        draw.text((25, y1 - 8), f"{lo:.2g}", fill="#637588", font=small)
    step = max(1, len(series) // 6)
    for i in range(0, len(series), step):
        stamp = str(series[i].get("recorded_at") or "")
        draw.text((left + i * (width - left - right) / max(len(series) - 1, 1) - 30, height - 48), stamp[5:13].replace("T", " "), fill="#637588", font=small)
    draw.text((left, 12), "24시간 시간당 평균 · 연녹색 영역은 생육단계 관리범위", fill="#20364A", font=small)
    handle = NamedTemporaryFile(prefix="bone_report_chart_", suffix=".png", delete=False)
    handle.close()
    target = Path(handle.name)
    canvas.save(target)
    return target


def _generate_daily_pdf_legacy(
    output_path: Path, report_date: str,
    window_summary: dict[str, Any], previous_summary: dict[str, Any],
    analysis: dict[str, Any] | None, captures: list[dict[str, Any]] | None,
    model: str, data_source: str, base_dir: Path, *,
    actuator_events: list[dict[str, Any]] | None = None,
    intervention_effects: list[dict[str, Any]] | None = None,
    recommendations: list[dict[str, Any]] | None = None,
    control_validation_records: list[dict[str, Any]] | None = None,
    growth_stage: str = "육묘기", management_profile: dict[str, float] | None = None,
    growth_score: dict[str, Any] | None = None,
    window_start: str = "", window_end: str = "",
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    font, bold = register_korean_font(base_dir)
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontName=font, fontSize=8.7, leading=13.4, textColor=TEXT, wordWrap="CJK", spaceAfter=4)
    small = ParagraphStyle("small", parent=body, fontSize=7.3, leading=10.8, textColor=MUTED)
    h1 = ParagraphStyle("h1", parent=body, fontName=bold, fontSize=18, leading=23, textColor=NAVY, spaceAfter=7)
    h2 = ParagraphStyle("h2", parent=body, fontName=bold, fontSize=11.5, leading=16, textColor=NAVY, spaceBefore=5, spaceAfter=5)
    hero = ParagraphStyle("hero", parent=body, fontName=bold, fontSize=23, leading=28, textColor=colors.white)
    score_style = ParagraphStyle("score", parent=body, fontName=bold, fontSize=30, leading=32, textColor=BLUE, alignment=TA_CENTER)
    doc = SimpleDocTemplate(str(output_path), pagesize=A4, rightMargin=16*mm, leftMargin=16*mm, topMargin=14*mm, bottomMargin=15*mm, title=f"BONE 브로콜리 24시간 생육 의사결정 보고서 {report_date}", author="BONE Broccoli One")
    temp_files: list[Path] = []
    insight, profile, score = dict(analysis or {}), management_profile or {}, growth_score or {}
    status = _safe(insight.get("overall_status"), _safe(score.get("status"), "판단 불가"))
    captures, events, recommendations = captures or [], actuator_events or [], recommendations or []
    control_validation_records = control_validation_records or []
    story = []

    brand = Table([[Paragraph("BONE", hero), Paragraph("BROCCOLI ONE<br/><font size='9'>24시간 생육 의사결정 보고서</font>", ParagraphStyle("brand", parent=body, fontName=bold, fontSize=13, leading=17, textColor=colors.white))]], colWidths=[42*mm,134*mm])
    brand.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),NAVY),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),10),("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10)]))
    story += [brand, Spacer(1,5*mm)]
    meta = [
        ["보고 기준일",report_date,"분석 시간창",f"{window_start[:16].replace('T',' ')} ~ {window_end[:16].replace('T',' ')} KST"],
        ["생육단계",growth_stage,"실측 출처",data_source],
        ["분석 모델",model,"분석 규격",_safe(insight.get("prompt_version"),"미입력")],
        ["생성 시각",f"{report_date} 12:00:00 KST","사람 검토","미검토 · 서명 없음"],
    ]
    story += [_table(meta,[25*mm,45*mm,27*mm,79*mm],font,bold,header=False,size=7.8),Spacer(1,4*mm)]
    score_text = str(score.get("score")) if score.get("score") is not None else "-"
    score_card = Table([[Paragraph(f"{score_text}<font size='12'>/100</font>",score_style),Paragraph(f"<b>{status}</b><br/>{_safe(insight.get('executive_summary'),'통합 분석 결과가 없습니다.')}",body)]],colWidths=[42*mm,134*mm])
    score_card.setStyle(TableStyle([("BACKGROUND",(0,0),(0,0),PALE_BLUE),("BACKGROUND",(1,0),(1,0),PALE_GREEN),("BOX",(0,0),(-1,-1),0.8,LINE),("INNERGRID",(0,0),(-1,-1),0.5,LINE),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),10),("RIGHTPADDING",(0,0),(-1,-1),10),("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10)]))
    story += [score_card, Paragraph("1. 오늘의 결론이 만들어진 근거 사슬",h2)]
    rows = [["판단","센서 근거","사진 근거","해석·확신도"]]
    for item in list(insight.get("integrated_findings") or [])[:3]:
        rows.append([item.get("finding"),item.get("sensor_evidence"),item.get("image_evidence"),f"{item.get('interpretation')} · {item.get('confidence')}"])
    if len(rows)==1: rows.append(["판단 불가","근거 없음","근거 없음","통합분석 미입력"])
    story += [_table(rows,[31*mm,48*mm,49*mm,48*mm],font,bold,size=7.2),Paragraph("2. 생육단계와 관리 기준",h2),Paragraph(_safe(insight.get("growth_stage_assessment"),"생육단계 판단 근거 미입력"),body)]
    profile_rows=[["EC","pH","기온","습도","CO₂"],[f"{profile.get('ec_low','-')}~{profile.get('ec_high','-')} · 목표 {profile.get('ec_target','-')}",f"{profile.get('ph_low','-')}~{profile.get('ph_high','-')} · 목표 {profile.get('ph_target','-')}",f"{profile.get('temp_low','-')}~{profile.get('temp_high','-')}℃",f"{profile.get('humidity_low','-')}~{profile.get('humidity_high','-')}%","350~1500 ppm"]]
    story += [_table(profile_rows,[35.2*mm]*5,font,bold,size=7.2,aligns=["center"]*5)]

    story += [PageBreak(),Paragraph("24시간 RS485 실측 분석",h1),Paragraph(f"분석 창 {window_start[:19].replace('T',' ')}부터 {window_end[:19].replace('T',' ')}까지 · 원본 {window_summary.get('row_count',0):,}행 · 시간당 평균 그래프",body)]
    rows=[["항목","24시간 평균","최소~최대","표준편차","범위내","전일 평균 대비","판정"]]
    for key in ("ec","ph","air_temp","humidity","co2","solution_temp"):
        item=(window_summary.get("metrics") or {}).get(key)
        if not item: rows.append([key,"미수집","-","-","-","-","판단 불가"]); continue
        change=item.get("mean_change")
        rows.append([item["label"],_fmt(item["mean"],item["digits"],item["unit"]),f"{_fmt(item['minimum'],item['digits'])}~{_fmt(item['maximum'],item['digits'],item['unit'])}",_fmt(item["stddev"],item["digits"],item["unit"]),f"{item['in_range_pct']:.1f}%",_fmt(change,item["digits"],item["unit"]) if change is not None else "비교 불가",item["status"]])
    story.append(_table(rows,[18*mm,28*mm,38*mm,25*mm,21*mm,29*mm,23*mm],font,bold,size=7.2,aligns=["center"]*7))
    chart=_chart_image(window_summary,Path("C:/Windows/Fonts/malgun.ttf"))
    if chart:
        temp_files.append(chart); story += [Spacer(1,3*mm),_fit_image(chart,176*mm,88*mm)]
    story += [PageBreak(), Paragraph("센서 해석과 데이터 품질",h1), Paragraph("센서별 해석",h2)]
    rows=[["항목","실측·추세","운영 의미"]]
    for item in list(insight.get("sensor_interpretation") or [])[:6]:
        rows.append([item.get("metric"),f"{item.get('evidence')} · {item.get('trend')}",f"{item.get('meaning')} · {item.get('status')}"])
    story += [_table(rows,[23*mm,77*mm,76*mm],font,bold,size=7.2),Paragraph("데이터 품질과 장치 출처",h2)]
    rows=[["장치","통신","측정 항목","표본·제외","교정일"]]
    for name,address,baud,measured in SENSOR_META:
        keys=("air_temp","humidity") if "온·습도" in name else (("co2",) if "CO₂" in name else ("ec","ph","solution_temp"))
        counts=[((window_summary.get("metrics") or {}).get(k) or {}).get("count",0) for k in keys]
        excluded=sum(((window_summary.get("metrics") or {}).get(k) or {}).get("excluded",0) for k in keys)
        rows.append([name,f"{address} · {baud}",measured,f"최소 {min(counts or [0]):,}개 · 제외 {excluded:,}개","미입력"])
    story.append(_table(rows,[41*mm,36*mm,37*mm,43*mm,19*mm],font,bold,size=7.0))

    story += [PageBreak(),Paragraph("카메라 3대 생육 관찰과 전일 비교",h1)]
    image_cells=[]; camera_meta=[]
    for index,capture in enumerate(captures[:3]):
        path=Path(str(capture.get("path") or "")); camera_id=str(capture.get("camera_id") or f"CAM-{index+1:02d}")
        if path.is_file():
            with PILImage.open(path) as im: resolution=f"{im.width}×{im.height}"
            image_cells.append([Paragraph(f"<b>{camera_id}</b><br/><font size='7'>{str(capture.get('captured_at') or '')[:19].replace('T',' ')} KST</font>",body),_fit_image(path,54*mm,42*mm)])
        else:
            resolution="미입력"; image_cells.append(Paragraph(f"{camera_id}<br/>이미지 없음",body))
        camera_meta.append([camera_id,str(capture.get("captured_at") or "")[:19].replace("T"," "),resolution,"서버 저장시각 사용 · 영상 OSD 제외"])
    while len(image_cells)<3: image_cells.append(Paragraph("카메라 영상 미입력",body))
    image_table=Table([image_cells],colWidths=[58.6*mm]*3)
    image_table.setStyle(TableStyle([("BOX",(0,0),(-1,-1),0.6,LINE),("INNERGRID",(0,0),(-1,-1),0.4,LINE),("VALIGN",(0,0),(-1,-1),"TOP"),("ALIGN",(0,0),(-1,-1),"CENTER"),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
    story += [image_table,Spacer(1,3*mm),Paragraph("촬영시각 판정 원칙: 영상의 1970년 OSD는 카메라 내부 시계 오류로 제외하며, 대시보드 서버가 captures 테이블에 기록한 KST 시각을 공식 촬영시각으로 사용한다.",small),Paragraph("영상 증거 메타데이터",h2),_table([["카메라","서버 저장시각(KST)","해상도","시각 검증"]]+camera_meta,[24*mm,48*mm,32*mm,72*mm],font,bold,size=7.3,aligns=["center","center","center","left"])]
    story += [PageBreak(), Paragraph("카메라별 AI 관찰과 변화 해석",h1)]
    rows=[["시야","당일 사진에서 직접 보이는 사실","전일 동일 시야 비교","확신도"]]
    for item in list(insight.get("camera_observations") or [])[:3]: rows.append([item.get("camera_id"),item.get("visible_observation"),item.get("comparison"),item.get("confidence")])
    if len(rows)==1: rows.append(["판단 불가","AI 이미지 관찰 미입력","비교 불가","낮음"])
    story += [_table(rows,[20*mm,68*mm,68*mm,20*mm],font,bold,size=7.3,aligns=["center","left","left","center"]),Paragraph("영상 해석 한계",h2)]
    limits=list(insight.get("limitations") or [])[:4]
    story += [Paragraph(" · ".join(f"• {_safe(item)}" for item in limits) if limits else "• 기록된 제한 없음",body),Paragraph("수치형 피복률·녹색도·균일도는 고정 ROI와 조명 교정, 검증 오버레이가 없으므로 산출하지 않았다.",small)]

    story += [PageBreak(),Paragraph("제안·승인·작동·효과의 감사 기록",h1)]
    rows=[["우선","근거 유형","조건과 판단 이유","제안","승인·검증"]]
    for item in list(insight.get("action_proposals") or [])[:5]: rows.append([item.get("priority"),item.get("basis_type"),f"{item.get('condition')}<br/>{item.get('rationale')}",item.get("proposal"),f"{item.get('approval')}<br/>{item.get('verification')}"])
    story += [_table(rows,[15*mm,25*mm,53*mm,42*mm,41*mm],font,bold,size=6.8), Spacer(1,3*mm), Paragraph("※ AI는 제안을 작성할 뿐 장치를 직접 작동하지 않는다. 실제 제어는 Telegram 사람 승인과 Pico 안전검사를 거친다.",small)]
    story += [PageBreak(), Paragraph("24시간 제어 이력",h1)]
    counts={}
    for event in events:
        label=f"{event.get('actuator','미상')}:{event.get('result','기록')}"; counts[label]=counts.get(label,0)+1
    story += [Paragraph("24시간 제어 이력 요약",h2),Paragraph(f"액추에이터 감사기록 {len(events)}건 · 제안 {len(recommendations)}건 · "+(" · ".join(f"{k} {v}건" for k,v in sorted(counts.items())) if counts else "실행 이력 없음"),body)]
    rows=[["시각","장치","시간","출처","결과"]]
    for event in events[-8:]: rows.append([str(event.get("created_at") or "")[11:19],event.get("actuator"),f"{event.get('duration_seconds',0)}초",event.get("source"),event.get("result")])
    if len(rows)==1: rows.append(["-","작동 없음","-","-","-"])
    story += [_table(rows,[25*mm,31*mm,20*mm,67*mm,33*mm],font,bold,size=7.1,aligns=["center","center","center","left","center"])]
    if control_validation_records:
        story += [Paragraph("제어 로직 검증 기록",h2)]
        validation_rows=[["시간","장치","실측값","판단 기준","로직 출력"]]
        for record in control_validation_records:
            validation_rows.append([
                str(record.get("recorded_at") or "")[11:19],
                record.get("device"),
                record.get("measured"),
                record.get("criterion"),
                record.get("decision"),
            ])
        story += [
            _table(validation_rows,[25*mm,29*mm,41*mm,47*mm,34*mm],font,bold,size=7.0,aligns=["center","center","center","left","center"]),
            Spacer(1,2*mm),
            Paragraph(
                "※ 당시 RS485 실측값에 현재 제어 기준을 다시 적용한 로직 검증 결과이다.",
                small,
            ),
        ]
    story += [PageBreak(), Paragraph("조치 효과와 다음 운용 계획",h1), Paragraph("조치 전후 효과 확인",h2)]
    rows=[["조치","조치 전","조치 후","관찰 변화","해석 제한"]]
    for effect in (intervention_effects or [])[-3:]:
        before,after=effect.get("before") or {},effect.get("after") or {}
        rows.append([f"{effect.get('actuator')} · {effect.get('pulse_count',0)}회/{effect.get('total_seconds',0)}초",f"EC {_fmt(before.get('ec'),3)} · pH {_fmt(before.get('ph'),2)}",f"EC {_fmt(after.get('ec'),3)} · pH {_fmt(after.get('ph'),2)}",f"ΔEC {_fmt(effect.get('ec_change'),3)} · ΔpH {_fmt(effect.get('ph_change'),2)}",effect.get("observation_note")])
    if len(rows)==1: rows.append(["연결 가능한 보정 없음","-","-","산출 불가","조치와 가까운 전후 실측쌍 없음"])
    story += [_table(rows,[34*mm,36*mm,36*mm,34*mm,36*mm],font,bold,size=7.0),Paragraph("다음 24시간 확인 계획",h2)]
    checks=list(insight.get("next_checks") or [])[:6]
    story += [Paragraph("　".join(f"□ {_safe(item)}" for item in checks) if checks else "□ 현장 확인 항목 미입력",body),Paragraph("사람 검토",h2),_table([["검토 상태","□ 일치　□ 일부 일치　□ 불일치","검토자","미기재","검토 시각","미기재"]],[25*mm,48*mm,22*mm,28*mm,24*mm,29*mm],font,bold,header=False,size=7.5,aligns=["center"]*6),Spacer(1,3*mm),Paragraph(DISCLAIMER,small)]

    def footer(canvas,document):
        canvas.saveState(); canvas.setStrokeColor(LINE); canvas.setLineWidth(0.5); canvas.line(16*mm,11*mm,A4[0]-16*mm,11*mm)
        canvas.setFont(font,7); canvas.setFillColor(MUTED); canvas.drawString(16*mm,7*mm,f"BONE · {report_date} · 서버시각 기준 · {data_source}"); canvas.drawRightString(A4[0]-16*mm,7*mm,f"{document.page}"); canvas.restoreState()
    try:
        doc.build(story,onFirstPage=footer,onLaterPages=footer)
    finally:
        for path in temp_files: path.unlink(missing_ok=True)


def _clip(value: Any, limit: int) -> str:
    text = _safe(value, "-")
    return text if len(text) <= limit else text[: max(1, limit - 1)].rstrip() + "…"


def _compact_table(data, widths, font: str, bold: str, *, size=6.6, aligns=None):
    normal = ParagraphStyle("ctb", fontName=font, fontSize=size, leading=size + 2.3, textColor=TEXT, wordWrap="CJK")
    center = ParagraphStyle("ctc", parent=normal, alignment=TA_CENTER)
    head = ParagraphStyle("cth", parent=center, fontName=bold, textColor=colors.white)
    rows = []
    for r, row in enumerate(data):
        cells = []
        for c, value in enumerate(row):
            style = head if r == 0 else (center if aligns and aligns[c] == "center" else normal)
            cells.append(Paragraph(_safe(value, "-"), style))
        rows.append(cells)
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="CENTER")
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
    ]
    for r in range(1, len(rows)):
        commands.append(("BACKGROUND", (0, r), (-1, r), colors.white if r % 2 else PALE_GRAY))
    table.setStyle(TableStyle(commands))
    return table


def generate_daily_pdf(
    output_path: Path, report_date: str,
    window_summary: dict[str, Any], previous_summary: dict[str, Any],
    analysis: dict[str, Any] | None, captures: list[dict[str, Any]] | None,
    model: str, data_source: str, base_dir: Path, *,
    actuator_events: list[dict[str, Any]] | None = None,
    intervention_effects: list[dict[str, Any]] | None = None,
    recommendations: list[dict[str, Any]] | None = None,
    control_validation_records: list[dict[str, Any]] | None = None,
    growth_stage: str = "육묘기", management_profile: dict[str, float] | None = None,
    growth_score: dict[str, Any] | None = None,
    window_start: str = "", window_end: str = "",
) -> None:
    """Create a dense, presentation-ready three-page daily report."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    font, bold = register_korean_font(base_dir)
    styles = getSampleStyleSheet()
    body = ParagraphStyle("cbody", parent=styles["Normal"], fontName=font, fontSize=7.3, leading=10.3, textColor=TEXT, wordWrap="CJK", spaceAfter=2)
    small = ParagraphStyle("csmall", parent=body, fontSize=6.2, leading=8.2, textColor=MUTED)
    h1 = ParagraphStyle("ch1", parent=body, fontName=bold, fontSize=16, leading=20, textColor=NAVY, spaceAfter=5)
    h2 = ParagraphStyle("ch2", parent=body, fontName=bold, fontSize=9.8, leading=12.5, textColor=NAVY, spaceBefore=3, spaceAfter=3)
    hero = ParagraphStyle("chero", parent=body, fontName=bold, fontSize=21, leading=24, textColor=colors.white)
    score_style = ParagraphStyle("cscore", parent=body, fontName=bold, fontSize=27, leading=29, textColor=BLUE, alignment=TA_CENTER)
    doc = SimpleDocTemplate(
        str(output_path), pagesize=A4, rightMargin=13*mm, leftMargin=13*mm,
        topMargin=11*mm, bottomMargin=13*mm,
        title=f"BONE 브로콜리 3쪽 일일 생육 의사결정 보고서 {report_date}",
        author="BONE Broccoli One",
    )
    temp_files: list[Path] = []
    insight, profile, score = dict(analysis or {}), management_profile or {}, growth_score or {}
    captures = list(captures or [])
    events = list(actuator_events or [])
    recommendations = list(recommendations or [])
    validation = list(control_validation_records or [])
    effects = list(intervention_effects or [])
    status = _safe(insight.get("overall_status"), _safe(score.get("status"), "판단 불가"))
    story = []

    # Page 1 — decision summary and evidence chain.
    brand = Table([
        [Paragraph("BONE", hero), Paragraph("BROCCOLI ONE<br/><font size='8'>3쪽 일일 생육 의사결정 보고서</font>", ParagraphStyle("cbrand", parent=body, fontName=bold, fontSize=12, leading=15, textColor=colors.white))]
    ], colWidths=[42*mm,142*mm])
    brand.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),NAVY),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),9),("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
    ]))
    story += [brand, Spacer(1,3*mm)]
    meta = [
        ["보고일",report_date,"24시간 분석창",f"{window_start[:16].replace('T',' ')} ~ {window_end[:16].replace('T',' ')} KST"],
        ["생육단계",growth_stage,"실측 출처",data_source],
        ["분석 모델",model,"분석 규격",_safe(insight.get("prompt_version"),"미입력")],
        ["생성 시각",f"{report_date} 12:00:00 KST","사람 검토","미검토 · 서명 없음"],
    ]
    story += [_compact_table(meta,[23*mm,40*mm,28*mm,93*mm],font,bold,size=6.7),Spacer(1,3*mm)]
    score_text = str(score.get("score")) if score.get("score") is not None else "-"
    summary = _clip(insight.get("executive_summary"), 520)
    score_card = Table([
        [Paragraph(f"{score_text}<font size='10'>/100</font>",score_style), Paragraph(f"<b>{status}</b><br/>{summary}",body)]
    ], colWidths=[38*mm,146*mm])
    score_card.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(0,0),PALE_BLUE),("BACKGROUND",(1,0),(1,0),PALE_GREEN),
        ("BOX",(0,0),(-1,-1),0.7,LINE),("INNERGRID",(0,0),(-1,-1),0.4,LINE),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),7),
        ("RIGHTPADDING",(0,0),(-1,-1),7),("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),
    ]))
    story += [score_card, Paragraph("종합판단의 근거 사슬",h2)]
    finding_rows = [["판단","센서 근거","영상 근거","해석·확신도"]]
    for item in list(insight.get("integrated_findings") or [])[:3]:
        finding_rows.append([
            _clip(item.get("finding"),70), _clip(item.get("sensor_evidence"),135),
            _clip(item.get("image_evidence"),125), _clip(f"{item.get('interpretation')} · {item.get('confidence')}",115),
        ])
    if len(finding_rows) == 1:
        finding_rows.append(["판단 불가","근거 없음","근거 없음","통합분석 미입력"])
    story += [_compact_table(finding_rows,[27*mm,52*mm,52*mm,53*mm],font,bold,size=6.3), Paragraph("생육단계와 관리 기준",h2)]
    story += [Paragraph(_clip(insight.get("growth_stage_assessment"),420),body)]
    profile_rows = [["EC","pH","기온","습도","CO₂"],[
        f"{profile.get('ec_low','-')}~{profile.get('ec_high','-')} / 목표 {profile.get('ec_target','-')}",
        f"{profile.get('ph_low','-')}~{profile.get('ph_high','-')} / 목표 {profile.get('ph_target','-')}",
        f"{profile.get('temp_low','-')}~{profile.get('temp_high','-')}℃",
        f"{profile.get('humidity_low','-')}~{profile.get('humidity_high','-')}%",
        "350~1500 ppm",
    ]]
    story += [_compact_table(profile_rows,[36.8*mm]*5,font,bold,size=6.5,aligns=["center"]*5)]

    # Page 2 — sensor and camera evidence.
    story += [PageBreak(), Paragraph("센서·카메라 증거",h1)]
    metric_rows = [["항목","평균","최소~최대","표준편차","범위내","전일 대비","판정"]]
    for key in ("ec","ph","air_temp","humidity","co2","solution_temp"):
        item = (window_summary.get("metrics") or {}).get(key)
        if not item:
            metric_rows.append([key,"미수집","-","-","-","-","판단 불가"])
            continue
        change = item.get("mean_change")
        metric_rows.append([
            item["label"], _fmt(item["mean"],item["digits"],item["unit"]),
            f"{_fmt(item['minimum'],item['digits'])}~{_fmt(item['maximum'],item['digits'],item['unit'])}",
            _fmt(item["stddev"],item["digits"],item["unit"]), f"{item['in_range_pct']:.1f}%",
            _fmt(change,item["digits"],item["unit"]) if change is not None else "-", item["status"],
        ])
    story += [_compact_table(metric_rows,[18*mm,27*mm,37*mm,25*mm,20*mm,29*mm,28*mm],font,bold,size=6.3,aligns=["center"]*7)]
    chart = _chart_image(window_summary,Path("C:/Windows/Fonts/malgun.ttf"))
    if chart:
        temp_files.append(chart)
        story += [Spacer(1,1.5*mm), _fit_image(chart,184*mm,69*mm)]
    story += [Paragraph("카메라 3대 관찰",h2)]
    capture_by_id = {str(item.get("camera_id")): item for item in captures}
    image_cells = []
    for camera_id in ("CAM-01","CAM-02","CAM-03"):
        capture = capture_by_id.get(camera_id) or {}
        path = Path(str(capture.get("path") or ""))
        cell: list[Any] = [Paragraph(f"<b>{camera_id}</b> · {_safe(str(capture.get('captured_at') or '')[:19].replace('T',' '),'미촬영')}",small)]
        if path.is_file():
            cell += [Spacer(1,1*mm), _fit_image(path,58*mm,34*mm)]
        else:
            cell += [Spacer(1,5*mm), Paragraph("이미지 미입력",body)]
        image_cells.append(cell)
    camera_table = Table([image_cells],colWidths=[61.3*mm]*3)
    camera_table.setStyle(TableStyle([
        ("BOX",(0,0),(-1,-1),0.5,LINE),("INNERGRID",(0,0),(-1,-1),0.35,LINE),
        ("VALIGN",(0,0),(-1,-1),"TOP"),("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
    ]))
    story += [camera_table]
    observation_rows = [["시야","당일 관찰·전일 비교","확신도"]]
    for item in list(insight.get("camera_observations") or [])[:3]:
        observation_rows.append([
            item.get("camera_id"),
            _clip(f"{item.get('visible_observation')} / 전일: {item.get('comparison')}",235),
            item.get("confidence"),
        ])
    if len(observation_rows) == 1:
        observation_rows.append(["-","AI 이미지 관찰 미입력","낮음"])
    story += [_compact_table(observation_rows,[20*mm,143*mm,21*mm],font,bold,size=6.0,aligns=["center","left","center"])]
    quality = window_summary.get("row_count",0)
    excluded = sum(int((item or {}).get("excluded",0)) for item in (window_summary.get("metrics") or {}).values())
    story += [Paragraph(
        f"출처·품질: RS485 원본 {quality:,}행 · 이상값 제외 {excluded:,}건 · 센서 교정일 미입력 · 카메라 시각은 서버 KST 저장시각 사용(영상 OSD 제외).",
        small,
    )]

    # Page 3 — actions, audit, control validation, and follow-up.
    story += [PageBreak(), Paragraph("제안·제어·효과·다음 계획",h1), Paragraph("우선 조치 제안",h2)]
    proposal_rows = [["우선","조건·근거","제안","승인·효과 확인"]]
    for item in list(insight.get("action_proposals") or [])[:3]:
        proposal_rows.append([
            item.get("priority"),
            _clip(f"{item.get('condition')} · {item.get('rationale')}",155),
            _clip(item.get("proposal"),125),
            _clip(f"{item.get('approval')} · {item.get('verification')}",135),
        ])
    if len(proposal_rows) == 1:
        proposal_rows.append(["-","제안 근거 미입력","현장 확인","사람 검토"])
    story += [_compact_table(proposal_rows,[15*mm,62*mm,49*mm,58*mm],font,bold,size=6.1)]

    labels = {"led":"LED","raw_water":"원수","supply":"양액 공급","mixing":"교반","ec":"A+B 양액","ph":"pH 산성액","fan":"환풍기"}
    counts: dict[str,int] = {}
    for event in events:
        label = f"{labels.get(str(event.get('actuator')),str(event.get('actuator') or '미상'))}:{event.get('result','기록')}"
        counts[label] = counts.get(label,0) + 1
    story += [Paragraph("24시간 제어 이력",h2), Paragraph(
        f"감사기록 {len(events)}건 · 제안 {len(recommendations)}건 · " + (" · ".join(f"{k} {v}건" for k,v in sorted(counts.items())) if counts else "실행 이력 없음"),
        small,
    )]
    event_rows = [["시간","장치","동작시간","출처","결과"]]
    for event in events[-5:]:
        event_rows.append([
            str(event.get("created_at") or "")[11:19], labels.get(str(event.get("actuator")),event.get("actuator")),
            f"{event.get('duration_seconds',0)}초", _clip(event.get("source"),42), event.get("result"),
        ])
    if len(event_rows) == 1:
        event_rows.append(["-","작동 없음","-","-","-"])
    story += [_compact_table(event_rows,[23*mm,31*mm,22*mm,72*mm,36*mm],font,bold,size=6.2,aligns=["center","center","center","left","center"])]

    story += [Paragraph("제어 로직 검증 기록",h2)]
    validation_rows = [["시간","장치","실측값","판단 기준","로직 출력"]]
    for record in validation:
        validation_rows.append([
            str(record.get("recorded_at") or "")[11:19], record.get("device"), record.get("measured"),
            record.get("criterion"), record.get("decision"),
        ])
    if len(validation_rows) == 1:
        validation_rows.append(["-","환경 제어","실측 없음","기준 적용 불가","판단 불가"])
    story += [_compact_table(validation_rows,[23*mm,29*mm,38*mm,57*mm,37*mm],font,bold,size=6.2,aligns=["center","center","center","left","center"]), Paragraph(
        "※ 당시 RS485 실측값에 현재 제어 기준을 다시 적용한 로직 검증 결과이다.", small,
    )]

    story += [Paragraph("조치 효과와 다음 24시간 확인",h2)]
    effect_rows = [["조치","전→후","관찰 변화·해석 한계"]]
    for effect in effects[-2:]:
        before, after = effect.get("before") or {}, effect.get("after") or {}
        effect_rows.append([
            f"{labels.get(str(effect.get('actuator')),effect.get('actuator'))} {effect.get('pulse_count',0)}회/{effect.get('total_seconds',0)}초",
            f"EC {_fmt(before.get('ec'),3)}→{_fmt(after.get('ec'),3)} · pH {_fmt(before.get('ph'),2)}→{_fmt(after.get('ph'),2)}",
            _clip(effect.get("observation_note"),100),
        ])
    if len(effect_rows) == 1:
        effect_rows.append(["연결 가능한 보정 없음","-","가까운 전후 실측쌍 없음"])
    story += [_compact_table(effect_rows,[42*mm,66*mm,76*mm],font,bold,size=6.1)]
    checks = list(insight.get("next_checks") or [])[:4]
    story += [Paragraph("　".join(f"□ {_clip(item,75)}" for item in checks) if checks else "□ 현장 확인 항목 미입력",body)]
    story += [_compact_table([
        ["사람 검토","□ 일치　□ 일부 일치　□ 불일치","검토자","미기재","시각","미기재"]
    ],[25*mm,55*mm,22*mm,31*mm,20*mm,31*mm],font,bold,size=6.3,aligns=["center"]*6), Paragraph(DISCLAIMER,small)]

    def footer(canvas,document):
        canvas.saveState()
        canvas.setStrokeColor(LINE); canvas.setLineWidth(0.5); canvas.line(13*mm,9*mm,A4[0]-13*mm,9*mm)
        canvas.setFont(font,6.3); canvas.setFillColor(MUTED)
        canvas.drawString(13*mm,5.5*mm,f"BONE · {report_date} · 서버시각 기준 · {data_source}")
        canvas.drawRightString(A4[0]-13*mm,5.5*mm,f"{document.page}/3")
        canvas.restoreState()

    try:
        doc.build(story,onFirstPage=footer,onLaterPages=footer)
    finally:
        for path in temp_files:
            path.unlink(missing_ok=True)
