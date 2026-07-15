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
| I2C1 SDA | GP14 |
| I2C1 SCL | GP15 |
| Relay S1 / LED | GP16 (physical pin 21) |
| Relay S2 / solenoid | GP17 (physical pin 22) |
| Relay S3 / supply pump | GP18 (physical pin 24) |
| Relay S4 / mixing pump | GP19 (physical pin 25) |
| Relay S5 / EC dosing pump | GP20 (physical pin 26) |
| Relay S6 / pH dosing pump | GP21 (physical pin 27) |
| Relay S7 / spare | GP22 (physical pin 29) |

현재 단독 시험에서는 PmodRS485 VCC를 Pico 2 W 36번 `3V3(OUT)`으로 공급하고 Pmod GND를 Pico GND와 연결했습니다.
실제 PE350은 별도 5V 전원으로 공급하며, PE350 전원 GND와 Pico GND는 연결하지 않습니다.
최종 외부 3.3V 전원을 사용할 때는 Pico의 `3V3(OUT)`과 동시에 연결하지 않습니다.

### PE350 실기 검증 결과 (2026-07-15)

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
