# Pico 2 / Pico2 W

학교 서버용 노트북에서 검증한 Pico2 W `main.py`를 이 폴더에 복사할 예정입니다.

검증된 파일을 확보하기 전에는 새 구현을 추측해서 만들지 않습니다.

## 현재 추가된 안전 테스트

`pe350_read_only_test.py`는 PE350의 EC, pH, 온도 input register만 읽는 테스트입니다.
펌프, 릴레이, 24V 출력은 제어하지 않습니다.

### Pico 2 핀 정의

| 기능 | GPIO |
|---|---:|
| UART0 TX | GP0 |
| UART0 RX | GP1 |
| RS485 DE | GP2 |
| RS485 ~RE | GP3 |
| RS485 SHTC3 / KCD-HP100 / PE350 | UART0 shared bus |
| Relay S1 / LED | GP16 (physical pin 21) |
| Relay S2 / raw water | GP17 (physical pin 22) |
| Relay S3 / supply pump | GP18 (physical pin 24) |
| Relay S4 / mixing pump | GP19 (physical pin 25) |
| Relay S5 / EC dosing pump | GP20 (physical pin 26) |
| Relay S6 / pH dosing pump | GP21 (physical pin 27) |
| Relay S7 / fan | GP22 (physical pin 29) |

현재 단독 시험에서는 PmodRS485 VCC를 Pico 2 W 36번 `3V3(OUT)`으로 공급하고 Pmod GND를 Pico GND와 연결했습니다.
실제 PE350은 별도 5V 전원으로 공급하며, PE350 전원 GND와 Pico GND는 연결하지 않습니다.
최종 외부 3.3V 전원을 사용할 때는 Pico의 `3V3(OUT)`과 동시에 연결하지 않습니다.

### 현재 RS485 운영 설정 (2026-08-26)

| 장비 | 국번 | 속도 | 읽기 |
|---|---:|---:|---|
| SHTC3 온습도 | 1 | 9600bps | holding `0x0000`~`0x0001` |
| KCD-HP100-3F CO₂ | 31 | 38400bps | input `0x0004` |
| PE350 EC/pH | 21 | 9600bps | input `0x0001`~`0x0003` |

Pico 통합 런타임은 I2C를 사용하지 않으며, 세 RS485 장비를 순서대로 읽어 USB telemetry로 전송합니다.

### PE350 이전 실기 검증 결과 (2026-07-15)

- 전원: 별도 5V
- 통신: 9600bps, 8N1, no parity, Slave ID 31
- 배선: PE350 A → Pmod A+Y, PE350 B → Pmod B+Z
- 읽기: input register `0x0001` EC, `0x0002` pH, `0x0003` 온도
- 결과: 10회 연속 CRC 오류 없이 EC, pH, 온도 수신 성공
- 확인값: EC 0.109 dS/m, pH 7.20, 온도 21.7 °C

### Thonny에서 PE350 테스트

아래 파일을 Pico 2에 업로드한 뒤 `pe350_read_only_test.py`를 실행합니다.

```text
config.py
sensors/__init__.py
sensors/pe350.py
pe350_read_only_test.py
```

정상 요청 프레임은 다음과 같아야 합니다.

```text
EC TX   : 1F 04 00 01 00 01 63 B4
pH TX   : 1F 04 00 02 00 01 93 B4
temp TX : 1F 04 00 03 00 01 C2 74
```

응답이 없으면 전원, 배선, GND, A/B 교환, PE350 주소, 9600/38400 baud rate 순서로 확인합니다.

### RS485 센서 국번 탐색 (읽기 전용)

`rs485_address_scan.py`는 새로 연결한 RS485 온습도·CO₂·PE350의 국번과 통신 속도를 콘솔에 표시합니다. Modbus 읽기 함수 `0x03`·`0x04`만 사용하며 주소·통신속도·보정값을 바꾸는 쓰기 명령은 전혀 보내지 않습니다.

현재 기본 탐색 범위는 국번 `1..31`, 속도 `4800/9600/19200/38400/57600bps`입니다. 예상 기본값은 아래와 같지만, 탐색 결과를 기준으로 확정합니다.

| 장비 | 예상 국번 | 예상 속도 | 읽는 레지스터 |
|---|---:|---:|---|
| SHTC3 RS485 온습도 | 1 | 4800 | holding `0x0000` 2개 |
| SenseCube KCD-HP100-3F CO₂ | 31 | 38400 | input `0x0004` |
| SenseCube PE350 EC/pH | 31 | 9600 | input `0x0001` |

Thonny에서 실행하기 전에는 Pico에 저장된 정상 `main.py`가 남아 있는지 확인합니다. 이 파일을 실행하면 MicroPython soft reboot 때문에 정상 런타임이 잠시 멈출 수 있으므로, 스캐너는 기존 설정대로 **공급 펌프(GP18)만 ON 상태로 유지**합니다. 탐색 완료 후 Thonny에서 `Ctrl-D`를 눌러 저장된 `main.py` 런타임으로 반드시 되돌립니다. 다른 릴레이·펌프·설정에는 접근하지 않습니다.
