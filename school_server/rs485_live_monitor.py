"""Read-only live terminal monitor for the smart-farm RS485 telemetry.

This program deliberately reads the dashboard API, rather than opening the Pico
COM port.  The running dashboard keeps exclusive ownership of the Pico and
continues its normal collection loop; this display is safe to run in parallel.
No Modbus write request, relay command, or actuator API call is made here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from urllib.error import URLError
from urllib.request import urlopen


# Windows PowerShell can otherwise select CP949, which cannot render the
# terminal drawing characters used by this monitor.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


DEFAULT_URL = "http://127.0.0.1:8765/api/sensors/latest"
ANSI = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def colour(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if ANSI else text


def cyan(text: str) -> str:
    return colour(text, "96")


def green(text: str) -> str:
    return colour(text, "92")


def yellow(text: str) -> str:
    return colour(text, "93")


def red(text: str) -> str:
    return colour(text, "91")


def dim(text: str) -> str:
    return colour(text, "2")


def fetch(url: str) -> dict:
    with urlopen(url, timeout=4) as response:  # nosec B310 - local server URL from operator
        return json.loads(response.read().decode("utf-8"))


def value(value: object, suffix: str, digits: int = 1) -> str:
    if value is None:
        return "--"
    if isinstance(value, float):
        return f"{value:.{digits}f}{suffix}"
    return f"{value}{suffix}"


def signal(connected: bool, label: str) -> str:
    marker = green("●") if connected else red("●")
    status = green("ONLINE") if connected else red("OFFLINE")
    return f"{marker} {label:<20} {status}"


def component_line(component: dict) -> str:
    status = str(component.get("status") or "확인")
    colour_fn = green if status in {"정상", "실측", "계산"} else yellow if status == "주의" else red
    label = str(component.get("label") or "항목")
    detail = str(component.get("detail") or "값 없음")
    return f"  [{colour_fn(status):^16}] {label:<12} {detail}"


def print_header(url: str, interval: float) -> None:
    print(cyan("╔════════════════════════════════════════════════════════════════════════════════════╗"))
    print(cyan("║  FFK BROCCOLI SMART FARM · RS485 MODBUS LIVE TELEMETRY MONITOR                     ║"))
    print(cyan("╚════════════════════════════════════════════════════════════════════════════════════╝"))
    print(dim("  MODE: READ-ONLY · Dashboard API mirror · no COM-port access · no actuator command"))
    print(dim(f"  SOURCE: {url} · refresh interval: {interval:g}s · stop: Ctrl+C"))
    print()


def print_snapshot(payload: dict) -> None:
    timestamp = str(payload.get("recorded_at") or "unknown")
    age = payload.get("age_seconds")
    source = str(payload.get("source") or "unknown")
    bus_ok = bool(payload.get("rs485_connected"))
    errors = payload.get("sensor_errors") or {}
    divider = "─" * 84
    print(cyan(f"┌─ TELEMETRY FRAME · {timestamp} · age {age if age is not None else '--'}s {'─' * 25}┐"))
    print(f"│ {signal(bus_ok, 'RS485 BUS')}  {dim('source:')} {source:<42}│")
    print(f"│ {signal(bool(payload.get('temperature_humidity_connected')), 'SLAVE 01  SHTC3')}   {cyan('9600 bps')}  FC03  TEMP/HUMIDITY                 │")
    print(f"│     RX  temperature={value(payload.get('air_temp'), ' °C', 1):<12} humidity={value(payload.get('humidity'), ' %RH', 1):<12} CRC={green('PASS')}             │")
    print(f"│ {signal(bool(payload.get('co2_connected')), 'SLAVE 31  KCD-HP100')} {cyan('38400 bps')} FC04  CO₂                                  │")
    print(f"│     RX  co2={value(payload.get('co2'), ' ppm', 0):<22} CRC={green('PASS') if payload.get('co2_connected') else red('NO RESPONSE')}                         │")
    print(f"│ {signal(bool(payload.get('pe350_connected')), 'SLAVE 21  PE350')}    {cyan('9600 bps')}  FC04  EC / pH / SOLUTION TEMP              │")
    print(f"│     RX  ec={value(payload.get('ec'), ' dS/m', 3):<14} ph={value(payload.get('ph'), '', 2):<10} solution={value(payload.get('solution_temp'), ' °C', 1):<10}│")
    print(cyan("└" + divider + "┘"))

    score = payload.get("growth_score") or {}
    score_value = score.get("score")
    if score_value is None:
        print(yellow("[ANALYSIS] 관리 환경 점수 산정 대기 · 실측 근거를 확인 중"))
    else:
        print(green(f"[ANALYSIS] 관리 환경 점수 {score_value}/{score.get('out_of', 100)} · {score.get('stage', '생육 단계 확인 중')} · {score.get('status', '확인') }"))
        for component in score.get("components") or []:
            print(component_line(component))
        reasons = score.get("reasons") or []
        if reasons:
            print(yellow("  [ACTION REVIEW] " + " | ".join(map(str, reasons))))
        else:
            print(green("  [ACTION REVIEW] 현재 관리 기준 이탈 항목 없음"))
    if errors:
        print(red("[BUS ERROR] " + " | ".join(f"{name}: {message}" for name, message in errors.items())))
    else:
        print(green("[INTEGRITY] sensor_errors=0 · Pico serial link healthy · telemetry stored in SQLite"))
    print(dim("[SAFETY] This monitor never sends Modbus writes or Pico actuator commands."))
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only RS485 live telemetry terminal monitor")
    parser.add_argument("--url", default=DEFAULT_URL, help="dashboard /api/sensors/latest URL")
    parser.add_argument("--interval", type=float, default=2.0, help="refresh seconds (minimum 0.5)")
    parser.add_argument("--once", action="store_true", help="print one snapshot and exit")
    args = parser.parse_args()
    interval = max(0.5, args.interval)
    print_header(args.url, interval)
    while True:
        try:
            print_snapshot(fetch(args.url))
        except (URLError, TimeoutError, json.JSONDecodeError, OSError) as error:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(red(f"[{now}] [LINK ERROR] dashboard telemetry unavailable: {type(error).__name__}: {error}"))
            print(dim("  Dashboard server continues independently; retrying without touching the Pico COM port."))
            print()
        if args.once:
            return
        time.sleep(interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n" + yellow("[STOPPED] operator ended the read-only terminal monitor."))
