"""Pure safety checks for Telegram status and approval helpers."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dashboard.server import (
    parse_telegram_callback,
    telegram_approver_ids,
    telegram_callback_data,
    telegram_command_name,
    telegram_daily_caption,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError("{}: {!r} != {!r}".format(label, actual, expected))


def main():
    assert_equal(telegram_callback_data(42, "approve"), "farm:a:42", "approve button")
    assert_equal(parse_telegram_callback("farm:r:42"), ("reject", 42), "reject parser")
    assert_equal(telegram_command_name("/status@brococolibot 지금 상태"), "/status", "status command")
    assert_equal(telegram_command_name("/start@brococolibot"), "/start", "start command")
    assert_equal(telegram_command_name("/report@brococolibot"), "/report", "report command")
    assert_equal(telegram_command_name("/help@brococolibot"), "/help", "help command")
    assert_equal(telegram_command_name("/stop@brococolibot"), "/stop", "stop command")
    assert_equal(telegram_approver_ids("12345, 67890"), {12345, 67890}, "approver IDs")
    assert_equal(telegram_approver_ids("12345\n67890"), {12345, 67890}, "approver IDs on separate lines")
    try:
        parse_telegram_callback("farm:a:not-a-number")
    except ValueError:
        pass
    else:
        raise AssertionError("malformed callback was accepted")
    try:
        telegram_approver_ids("12345,abc")
    except ValueError:
        pass
    else:
        raise AssertionError("malformed approver ID was accepted")

    caption = telegram_daily_caption(
        {"source": "measured:pico_usb", "air_temp": 22.7, "humidity": 88.8, "ec": 1.113, "ph": 7.0},
        {
            "overall_status": "주의",
            "confidence": "중간",
            "summary": "습도가 기준보다 높음",
            "observations": ["잎 상태를 사진으로 관찰"],
            "limitations": ["SCD40 미설치", "OpenAI unavailable: RateLimitError: HTTP 429"],
            "model": "rule-engine:no-ai",
        },
        True,
    )
    for expected in ("🥦 브로콜리 | 오늘의 상태", "🟠 상태: 주의", "🌡 환경 (Pico 센서 실측)", "📷 최신 사진: 첨부됨", "🤖 분석 방식: 기본 안전 분석"):
        if expected not in caption:
            raise AssertionError("caption omitted {!r}".format(expected))
    for hidden in ("OpenAI", "RateLimitError", "HTTP 429", "rule-engine:no-ai"):
        if hidden in caption:
            raise AssertionError("caption exposed technical detail {!r}".format(hidden))
    print("Telegram control tests passed")


if __name__ == "__main__":
    main()
