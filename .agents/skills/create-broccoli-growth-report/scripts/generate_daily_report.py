import argparse
import json
from pathlib import Path

from PIL import Image, ImageOps
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


PAGE_W, PAGE_H = A4
BLACK = (0, 0, 0)
GRAY_LIGHT = (0.94, 0.94, 0.94)
GRAY_MID = (0.86, 0.86, 0.86)
GRAY_TEXT = (0.42, 0.42, 0.42)
STATUS_VALUES = {"정상", "주의", "경고", "판단 불가"}
SOURCE_TYPES = {"실측", "계산", "AI 관찰", "가상", "미입력"}
LIMITATION = "본 보고서는 영상 및 센서 데이터에 기반한 생육 의사결정 지원 자료이며, 병해충과 생리장해의 확정 진단을 대체하지 않는다."


def parse_args():
    parser = argparse.ArgumentParser(description="브로콜리 AI 일일 생육관찰 PDF 생성")
    parser.add_argument("--input", required=True, type=Path, help="일일 보고 JSON")
    parser.add_argument("--photo", required=True, type=Path, help="카메라 사진")
    parser.add_argument("--output", required=True, type=Path, help="출력 PDF")
    parser.add_argument("--font", type=Path, help="한글 TTF/TTC 폰트")
    parser.add_argument("--reporter-signature", type=Path, help="승인된 보고자 서명 이미지")
    parser.add_argument("--reviewer-stamp", type=Path, help="승인된 확인자 도장 이미지")
    return parser.parse_args()


def require(mapping, key, context):
    value = mapping.get(key)
    if value is None or value == "":
        raise ValueError(f"{context}.{key} 값이 없습니다")
    return value


def load_and_validate(path, photo, signature, stamp):
    if not path.is_file():
        raise FileNotFoundError(path)
    if not photo.is_file():
        raise FileNotFoundError(photo)
    data = json.loads(path.read_text(encoding="utf-8"))

    for group in ("report", "image", "sensors", "system", "analysis", "review"):
        if group not in data:
            raise ValueError(f"필수 그룹이 없습니다: {group}")

    report = data["report"]
    for key in ("date", "crop", "facility", "zone", "growth_stage", "report_type", "team", "operators"):
        require(report, key, "report")
    if not isinstance(report["operators"], list) or not report["operators"]:
        raise ValueError("report.operators는 1명 이상의 배열이어야 합니다")

    image = data["image"]
    for key in ("camera_id", "capture_time", "server_received_time", "timestamp_status", "resolution", "viewpoint", "overall_status", "confidence", "confidence_reason", "observations", "metrics"):
        require(image, key, "image")
    if image["overall_status"] not in STATUS_VALUES:
        raise ValueError("image.overall_status는 정상/주의/경고/판단 불가 중 하나여야 합니다")
    for metric in image["metrics"]:
        require(metric, "name", "image.metrics[]")
        require(metric, "status", "image.metrics[]")
        require(metric, "reason", "image.metrics[]")
        if metric["status"] != "산출 불가":
            if metric.get("value") is None:
                raise ValueError(f"{metric['name']}의 계산값이 없습니다")
            for key in ("method_version", "evidence"):
                require(metric, key, f"image.metrics[{metric['name']}]")

    if not isinstance(data["sensors"], list) or not data["sensors"]:
        raise ValueError("sensors는 1개 이상의 배열이어야 합니다")
    for sensor in data["sensors"]:
        for key in ("name", "source_type", "sensor_id", "mean", "min", "max", "unit", "accepted_min", "accepted_max", "sample_count", "period_start", "period_end"):
            require(sensor, key, "sensors[]")
        if sensor["source_type"] not in SOURCE_TYPES:
            raise ValueError(f"지원하지 않는 데이터 출처: {sensor['source_type']}")
        if sensor["source_type"] == "실측" and int(sensor["sample_count"]) <= 0:
            raise ValueError(f"실측 센서 {sensor['name']}의 sample_count는 1 이상이어야 합니다")
        if sensor["source_type"] == "실측" and not sensor.get("calibration_date"):
            raise ValueError(f"실측 센서 {sensor['name']}의 calibration_date가 없습니다")
        if float(sensor["min"]) > float(sensor["max"]):
            raise ValueError(f"센서 {sensor['name']}의 min이 max보다 큽니다")

    review = data["review"]
    require(review, "reviewer", "review")
    if not isinstance(review.get("approved"), bool):
        raise ValueError("review.approved는 true 또는 false여야 합니다")
    if (signature or stamp) and not review["approved"]:
        raise ValueError("서명 또는 도장은 review.approved=true인 승인 보고서에만 넣을 수 있습니다")
    for optional_file in (signature, stamp):
        if optional_file and not optional_file.is_file():
            raise FileNotFoundError(optional_file)
    return data


def register_korean_font(requested=None):
    candidates = []
    if requested:
        candidates.append(requested)
    candidates.extend(
        [
            Path(r"C:\Windows\Fonts\gulim.ttc"),
            Path(r"C:\Windows\Fonts\malgun.ttf"),
            Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
        ]
    )
    for path in candidates:
        if not path.is_file():
            continue
        kwargs = {"subfontIndex": 0} if path.suffix.lower() == ".ttc" else {}
        pdfmetrics.registerFont(TTFont("ReportKorean", str(path), **kwargs))
        return path
    raise FileNotFoundError("한글 폰트를 찾을 수 없습니다. --font로 TTF/TTC 파일을 지정하세요")


def set_fill(c, rgb):
    c.setFillColorRGB(*rgb)


def wrap_text(text, size, width):
    lines = []
    for paragraph in str(text).split("\n"):
        if not paragraph:
            lines.append("")
            continue
        line = ""
        for word in paragraph.split(" "):
            candidate = word if not line else f"{line} {word}"
            if pdfmetrics.stringWidth(candidate, "ReportKorean", size) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
            line = ""
            fragment = ""
            for char in word:
                if pdfmetrics.stringWidth(fragment + char, "ReportKorean", size) <= width:
                    fragment += char
                else:
                    if fragment:
                        lines.append(fragment)
                    fragment = char
            line = fragment
        if line:
            lines.append(line)
    return lines


def draw_wrapped(c, text, x, top, width, size=8.5, leading=12, max_lines=None, align="left"):
    lines = wrap_text(text, size, width)
    if max_lines is not None:
        lines = lines[:max_lines]
    c.setFont("ReportKorean", size)
    set_fill(c, BLACK)
    y = top
    for line in lines:
        if align == "center":
            c.drawCentredString(x + width / 2, y, line)
        elif align == "right":
            c.drawRightString(x + width, y, line)
        else:
            c.drawString(x, y, line)
        y -= leading
    return y


def draw_cell(c, x, bottom, width, height, text="", label=False, align="left", size=8, padding=2.2 * mm):
    c.saveState()
    if label:
        set_fill(c, GRAY_LIGHT)
        c.rect(x, bottom, width, height, fill=1, stroke=0)
    c.setStrokeColorRGB(*BLACK)
    c.setLineWidth(0.6)
    c.rect(x, bottom, width, height, fill=0, stroke=1)
    if text not in (None, ""):
        usable = width - 2 * padding
        lines = wrap_text(text, size, usable)
        leading = size + 3
        y = bottom + (height + len(lines) * leading) / 2 - leading
        c.setFont("ReportKorean", size)
        set_fill(c, BLACK)
        for line in lines:
            if align == "center" or label:
                c.drawCentredString(x + width / 2, y, line)
            elif align == "right":
                c.drawRightString(x + width - padding, y, line)
            else:
                c.drawString(x + padding, y, line)
            y -= leading
    c.restoreState()


def draw_header(c, page, total, report):
    c.setFont("ReportKorean", 8)
    set_fill(c, BLACK)
    c.drawString(25 * mm, PAGE_H - 16 * mm, f"{report['crop']} AI 일일 생육관찰 보고서")
    c.drawRightString(PAGE_W - 25 * mm, PAGE_H - 16 * mm, f"{page} / {total}")
    c.setStrokeColorRGB(*BLACK)
    c.setLineWidth(0.5)
    c.line(25 * mm, PAGE_H - 19 * mm, PAGE_W - 25 * mm, PAGE_H - 19 * mm)


def draw_footer(c, page):
    c.setFont("ReportKorean", 7)
    set_fill(c, GRAY_TEXT)
    c.drawString(25 * mm, 14 * mm, "AI·영상·센서 기반 생육 의사결정 지원 보고서")
    c.drawRightString(PAGE_W - 25 * mm, 14 * mm, f"- {page} -")


def section_title(c, y, title):
    c.setFont("ReportKorean", 15)
    set_fill(c, BLACK)
    c.drawString(25 * mm, y, title)
    c.setLineWidth(0.9)
    c.line(25 * mm, y - 4 * mm, PAGE_W - 25 * mm, y - 4 * mm)


def transparent_art(path):
    image = Image.open(path).convert("RGBA")
    pixels = []
    for r, g, b, a in image.getdata():
        pixels.append((r, g, b, 0 if r >= 245 and g >= 245 and b >= 245 else a))
    image.putdata(pixels)
    return ImageReader(image)


def draw_photo(c, path, x, y, width, height):
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        ratio = min(width / image.width, height / image.height)
        draw_w = image.width * ratio
        draw_h = image.height * ratio
        c.drawImage(ImageReader(image), x + (width - draw_w) / 2, y + (height - draw_h) / 2, draw_w, draw_h)
    c.setStrokeColorRGB(*BLACK)
    c.rect(x, y, width, height, fill=0, stroke=1)


def sensor_status(sensor):
    low = float(sensor["accepted_min"])
    high = float(sensor["accepted_max"])
    minimum = float(sensor["min"])
    maximum = float(sensor["max"])
    mean = float(sensor["mean"])
    if minimum >= low and maximum <= high:
        return "정상"
    if low <= mean <= high:
        return "주의"
    return "경고"


def format_number(value):
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def page_one(c, data, signature, stamp):
    report = data["report"]
    image = data["image"]
    analysis = data["analysis"]
    review = data["review"]
    operators = ", ".join(report["operators"])
    dat = "미입력" if report.get("dat") is None else f"{report['dat']}일차"

    c.setFont("ReportKorean", 21)
    set_fill(c, BLACK)
    c.drawCentredString(PAGE_W / 2, 274 * mm, f"{report['crop']} AI 일일 생육관찰 보고서")
    x, width = 25 * mm, 160 * mm

    draw_cell(c, x, 239 * mm, 28 * mm, 16 * mm, "담당자", label=True, size=9)
    draw_cell(c, x + 28 * mm, 247 * mm, 23 * mm, 8 * mm, "소속", label=True, size=8)
    draw_cell(c, x + 51 * mm, 247 * mm, 49 * mm, 8 * mm, report["team"], align="center", size=8)
    draw_cell(c, x + 100 * mm, 247 * mm, 22 * mm, 8 * mm, "확인", label=True, size=8)
    draw_cell(c, x + 122 * mm, 247 * mm, 38 * mm, 8 * mm, review["reviewer"], align="center", size=8)
    draw_cell(c, x + 28 * mm, 239 * mm, 23 * mm, 8 * mm, "성명", label=True, size=8)
    draw_cell(c, x + 51 * mm, 239 * mm, 49 * mm, 8 * mm, operators, align="center", size=8)
    draw_cell(c, x + 100 * mm, 239 * mm, 22 * mm, 8 * mm, "보고구분", label=True, size=8)
    draw_cell(c, x + 122 * mm, 239 * mm, 38 * mm, 8 * mm, report["report_type"], align="center", size=8)
    draw_cell(c, x, 230 * mm, 28 * mm, 9 * mm, "분석 모델", label=True, size=8)
    draw_cell(c, x + 28 * mm, 230 * mm, 132 * mm, 9 * mm, analysis["model_id"], size=8)

    draw_cell(c, x, 216 * mm, 28 * mm, 14 * mm, "기본 정보", label=True, size=8)
    draw_cell(c, x + 28 * mm, 216 * mm, 132 * mm, 14 * mm, f"기준일 {report['date']} · {report['facility']} / {report['zone']} · DAT {dat} · {report['growth_stage']}", size=8)
    draw_cell(c, x, 196 * mm, 28 * mm, 20 * mm, "보고 목적", label=True, size=8)
    draw_cell(c, x + 28 * mm, 196 * mm, 132 * mm, 20 * mm, "고정형 카메라 영상과 환경 센서 기록을 함께 검토하여 생육 상태, 데이터 품질, 현장 확인 항목을 일일 단위로 기록한다.", size=8)

    c.setFont("ReportKorean", 12)
    c.drawString(x, 187 * mm, "데이터 신뢰성 요약")
    source_counts = {}
    for sensor in data["sensors"]:
        source_counts[sensor["source_type"]] = source_counts.get(sensor["source_type"], 0) + 1
    source_text = " · ".join(f"{key} {value}개" for key, value in source_counts.items())
    integrity_rows = [
        ("영상", f"{image['camera_id']} · {image['resolution']} · {image['viewpoint']}", image["overall_status"]),
        ("촬영 시각", image["capture_time"], image["timestamp_status"]),
        ("서버 수신", image["server_received_time"], "기록"),
        ("센서 출처", source_text, "구분 완료"),
        ("사람 검토", review.get("human_result", "검토 대기"), "승인" if review["approved"] else "검토 대기"),
    ]
    y = 171 * mm
    for name, value, status in integrity_rows:
        draw_cell(c, x, y, 28 * mm, 10 * mm, name, label=True, size=8)
        draw_cell(c, x + 28 * mm, y, 102 * mm, 10 * mm, value, size=7.5)
        draw_cell(c, x + 130 * mm, y, 30 * mm, 10 * mm, status, align="center", size=8)
        y -= 10 * mm

    c.setFont("ReportKorean", 12)
    c.drawString(x, 113 * mm, "시스템 이상 및 조치")
    anomalies = data["system"].get("anomalies") or ["기록된 이상 없음"]
    anomaly_text = "\n".join(f"- {item}" for item in anomalies)
    draw_cell(c, x, 76 * mm, width, 31 * mm, anomaly_text, size=8)
    draw_cell(c, x, 61 * mm, 28 * mm, 15 * mm, "분석 메타", label=True, size=8)
    draw_cell(c, x + 28 * mm, 61 * mm, 132 * mm, 15 * mm, f"프롬프트 {analysis['prompt_version']} · 코드 {analysis['code_version']} · 생성 {analysis['generated_at']}", size=7.5)

    draw_cell(c, x, 28 * mm, width, 27 * mm, "", size=8)
    c.setFont("ReportKorean", 8.5)
    c.drawCentredString(PAGE_W / 2, 45 * mm, "위와 같이 브로콜리 일일 생육관찰 결과를 보고합니다.")
    c.drawCentredString(PAGE_W / 2, 37 * mm, report["date"])
    c.drawString(79 * mm, 31.5 * mm, f"보고자  {operators}  (인)")
    c.drawString(143 * mm, 31.5 * mm, f"확인자  {review['reviewer']}  (인)")
    if signature:
        c.drawImage(transparent_art(signature), 119 * mm, 28.5 * mm, 23 * mm, 9 * mm, mask="auto")
    if stamp:
        c.drawImage(transparent_art(stamp), 166 * mm, 29 * mm, 10 * mm, 10 * mm, mask="auto")


def page_two(c, data, photo):
    report = data["report"]
    image = data["image"]
    draw_header(c, 2, 3, report)
    section_title(c, PAGE_H - 32 * mm, "1. 사진 관찰 및 영상 지표")
    x, width = 25 * mm, 160 * mm

    draw_cell(c, x, 238 * mm, 28 * mm, 10 * mm, "촬영 자료", label=True, size=8)
    draw_cell(c, x + 28 * mm, 238 * mm, 132 * mm, 10 * mm, photo.name, size=8)
    draw_cell(c, x, 228 * mm, 28 * mm, 10 * mm, "촬영/수신", label=True, size=8)
    draw_cell(c, x + 28 * mm, 228 * mm, 132 * mm, 10 * mm, f"촬영 {image['capture_time']} · 서버 수신 {image['server_received_time']}", size=7)

    draw_photo(c, photo, x, 128 * mm, width, 94 * mm)
    c.setFont("ReportKorean", 7)
    c.drawCentredString(PAGE_W / 2, 124 * mm, f"그림 1. {image['camera_id']} 원본 영상 (사진만 컬러)")

    c.setFont("ReportKorean", 11)
    c.drawString(x, 115 * mm, "1.1 AI 영상 관찰")
    observation_text = "\n".join(f"- {item}" for item in image["observations"])
    draw_cell(c, x, 86 * mm, width, 24 * mm, observation_text, size=8)
    draw_cell(c, x, 74 * mm, 28 * mm, 12 * mm, "관찰 판정", label=True, size=8)
    draw_cell(c, x + 28 * mm, 74 * mm, 30 * mm, 12 * mm, image["overall_status"], align="center", size=9)
    draw_cell(c, x + 58 * mm, 74 * mm, 28 * mm, 12 * mm, "신뢰도", label=True, size=8)
    draw_cell(c, x + 86 * mm, 74 * mm, 74 * mm, 12 * mm, f"{image['confidence']} · {image['confidence_reason']}", size=7.2)

    c.setFont("ReportKorean", 11)
    c.drawString(x, 65 * mm, "1.2 정량 영상 지표")
    col_widths = [35 * mm, 32 * mm, 93 * mm]
    headers = ["분석 항목", "산출값/상태", "근거 또는 산출 조건"]
    y = 50 * mm
    cursor_x = x
    for header, col_width in zip(headers, col_widths):
        draw_cell(c, cursor_x, y, col_width, 9 * mm, header, label=True, align="center", size=8)
        cursor_x += col_width
    for metric in image["metrics"][:3]:
        y -= 9 * mm
        value = metric["status"] if metric["status"] == "산출 불가" else f"{metric['value']} ({metric['status']})"
        cursor_x = x
        for index, (text, col_width) in enumerate(zip((metric["name"], value, metric["reason"]), col_widths)):
            draw_cell(c, cursor_x, y, col_width, 9 * mm, text, align="center" if index < 2 else "left", size=7)
            cursor_x += col_width
    draw_footer(c, 2)


def page_three(c, data, signature, stamp):
    report = data["report"]
    review = data["review"]
    operators = ", ".join(report["operators"])
    draw_header(c, 3, 3, report)
    section_title(c, PAGE_H - 32 * mm, "2. 환경 데이터 및 금일 조치")
    x, width = 25 * mm, 160 * mm

    source_types = sorted({sensor["source_type"] for sensor in data["sensors"]})
    warning = "센서 데이터 출처: " + ", ".join(source_types)
    if "가상" in source_types:
        warning += " · 가상값은 실제 재배 및 자동제어 판단에 사용 금지"
    draw_cell(c, x, 235 * mm, width, 14 * mm, warning, label=True, align="center", size=8)

    headers = ["항목", "출처/센서", "평균 (최소-최대)", "적정 범위", "판정"]
    col_widths = [24 * mm, 35 * mm, 45 * mm, 31 * mm, 25 * mm]
    y = 223 * mm
    cursor_x = x
    for header, col_width in zip(headers, col_widths):
        draw_cell(c, cursor_x, y, col_width, 10 * mm, header, label=True, align="center", size=7.5)
        cursor_x += col_width
    for sensor in data["sensors"][:6]:
        y -= 11 * mm
        measured = f"{format_number(sensor['mean'])} ({format_number(sensor['min'])}-{format_number(sensor['max'])}) {sensor['unit']}"
        accepted = f"{format_number(sensor['accepted_min'])}-{format_number(sensor['accepted_max'])} {sensor['unit']}"
        values = (sensor["name"], f"{sensor['source_type']} / {sensor['sensor_id']}", measured, accepted, sensor_status(sensor))
        cursor_x = x
        for index, (value, col_width) in enumerate(zip(values, col_widths)):
            draw_cell(c, cursor_x, y, col_width, 11 * mm, value, align="center" if index != 1 else "left", size=6.8)
            cursor_x += col_width

    details_y = y - 13 * mm
    first_sensor = data["sensors"][0]
    period_text = f"측정 기간: {first_sensor['period_start']} - {first_sensor['period_end']} · 센서별 표본 수와 보정일은 원본 JSON에 기록"
    draw_cell(c, x, details_y, width, 10 * mm, period_text, size=7)

    rec_title_y = details_y - 10 * mm
    c.setFont("ReportKorean", 11)
    c.drawString(x, rec_title_y, "2.1 금일 권고사항")
    rec_bottom = rec_title_y - 39 * mm
    recommendation_text = "\n".join(f"□ {item}" for item in data.get("recommendations", []))
    draw_cell(c, x, rec_bottom, width, 34 * mm, recommendation_text, size=8)

    conclusion_title_y = rec_bottom - 9 * mm
    c.setFont("ReportKorean", 11)
    c.drawString(x, conclusion_title_y, "2.2 일일 결론 및 한계")
    conclusion_bottom = conclusion_title_y - 42 * mm
    draw_cell(c, x, conclusion_bottom, width, 37 * mm, f"{data.get('conclusion', '미입력')}\n\n※ {LIMITATION}", size=8)

    review_bottom = 32 * mm
    draw_cell(c, x, review_bottom, 24 * mm, 14 * mm, "담당", label=True, size=8)
    draw_cell(c, x + 24 * mm, review_bottom, 56 * mm, 14 * mm, f"{operators}  (인)", align="center", size=8)
    draw_cell(c, x + 80 * mm, review_bottom, 24 * mm, 14 * mm, "확인", label=True, size=8)
    draw_cell(c, x + 104 * mm, review_bottom, 56 * mm, 14 * mm, f"{review['reviewer']}  (인)\n{review.get('human_result', '검토 대기')}", align="center", size=8)
    if signature:
        c.drawImage(transparent_art(signature), x + 55 * mm, review_bottom + 3 * mm, 17 * mm, 7 * mm, mask="auto")
    if stamp:
        c.drawImage(transparent_art(stamp), x + 137 * mm, review_bottom + 2 * mm, 10 * mm, 10 * mm, mask="auto")
    draw_footer(c, 3)


def build(data, photo, output, font_path, signature=None, stamp=None):
    used_font = register_korean_font(font_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(output), pagesize=A4, pageCompression=1)
    c.setTitle(f"{data['report']['crop']} AI 일일 생육관찰 보고서")
    c.setAuthor(", ".join(data["report"]["operators"]))
    c.setSubject("영상 및 센서 데이터 기반 생육 의사결정 지원 보고서")
    page_one(c, data, signature, stamp)
    c.showPage()
    page_two(c, data, photo)
    c.showPage()
    page_three(c, data, signature, stamp)
    c.save()
    return used_font


def main():
    args = parse_args()
    data = load_and_validate(args.input, args.photo, args.reporter_signature, args.reviewer_stamp)
    used_font = build(data, args.photo, args.output, args.font, args.reporter_signature, args.reviewer_stamp)
    print(f"PDF: {args.output.resolve()}")
    print(f"FONT: {used_font}")


if __name__ == "__main__":
    main()
