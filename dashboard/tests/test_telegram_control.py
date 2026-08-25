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
    telegram_command_argument,
    telegram_daily_caption,
    stabilize_growth_stage,
    word_chain_play,
    word_chain_start,
    word_chain_stop,
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
    assert_equal(telegram_command_name("/wordchain@brococolibot 사과"), "/wordchain", "word-chain command")
    assert_equal(telegram_command_argument("/끝말잇기 사과"), "사과", "word-chain opening word")
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

    start = word_chain_start("test-chat", "사과")
    if "봇: 과자" not in start or "‘자’" not in start:
        raise AssertionError("word-chain did not make a valid opening reply: {!r}".format(start))
    turn = word_chain_play("test-chat", "자동차")
    if "봇: 차표" not in turn:
        raise AssertionError("word-chain did not continue the player turn: {!r}".format(turn))
    assert_equal(word_chain_stop("test-chat"), "🎮 끝말잇기를 종료했어요.", "word-chain stop")

    previous = {"created_at": "2026-08-24T12:00:00+09:00", "result": {"growth_stage": "활착기"}}
    held = stabilize_growth_stage({
        "growth_stage": "생육기", "growth_stage_confidence": "중간",
        "growth_stage_reason": "본엽이 관찰됨",
    }, previous, 3)
    assert_equal(held["growth_stage"], "활착기", "medium-confidence stage change held")
    assert_equal(held["growth_stage_transition"], "변경 보류", "stage change hold label")
    confirmed = stabilize_growth_stage({
        "growth_stage": "생육기", "growth_stage_confidence": "높음",
        "growth_stage_reason": "전일보다 잎 수와 크기가 뚜렷하게 증가함",
    }, previous, 3)
    assert_equal(confirmed["growth_stage"], "생육기", "high-confidence stage change accepted")
    assert_equal(confirmed["growth_stage_transition"], "변경 확정", "stage change confirmation label")
    print("Telegram control tests passed")


if __name__ == "__main__":
    main()
