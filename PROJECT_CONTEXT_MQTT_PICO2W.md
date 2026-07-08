# Pico2 W MQTT Gateway 프로젝트 컨텍스트

> 이 파일은 Codex에서 이어서 작업하기 위한 프로젝트 정리 문서입니다.
> 핵심은 **학교 서버용 노트북**과 **개인 게이밍 노트북**의 역할을 절대 혼동하지 않는 것입니다.

---

## 1. 프로젝트 목적

학교 안에 설치될 Pico2 W와 센서/릴레이 장치를 외부 네트워크에서도 확인·제어할 수 있도록 만든다.

학교 Wi-Fi는 `WPA/WPA2-Enterprise` 인증서 방식이라 Pico2 W가 직접 Wi-Fi에 붙기 어렵다.
따라서 Pico2 W는 Wi-Fi를 사용하지 않고, **USB Serial**로 학교 서버용 노트북과 통신한다.

학교 서버용 노트북은 학교 Wi-Fi 인증을 처리하고, Pico2 W와 MQTT Broker 사이의 **Gateway/Bridge** 역할을 한다.

---

## 2. 반드시 구분해야 할 장비

### 2.1 학교 서버용 노트북

역할:

- 학교에 계속 두는 장비
- 학교 Wi-Fi에 연결됨
- Pico2 W가 USB로 물리적으로 연결되어 있음
- VSCode 설치되어 있음
- Thonny 설치되어 있음
- ChatGPT / Codex 사용 가능
- 선생님 ChatGPT 계정으로 로그인되어 있음
- `mqtt_usb_bridge.py`를 실행하는 장비
- Pico2 W와 MQTT Broker 사이의 Gateway 역할

주의:

- 이 노트북은 **Pico2 W와 직접 USB로 연결된 장비**이다.
- Thonny로 Pico2 W에 `main.py`를 저장한 뒤에는 Thonny를 닫아야 한다.
- Thonny가 COM 포트를 잡고 있으면 VSCode에서 실행하는 Python Bridge가 Pico2 W의 COM 포트를 열 수 없다.
- 이 노트북에서 `mqtt_usb_bridge.py`가 계속 실행되어야 외부에서 센서값을 받고 제어 명령을 보낼 수 있다.

---

### 2.2 개인 게이밍 노트북

역할:

- 선생님이 집이나 외부로 가져가는 장비
- 학교 안 Pico2 W와 직접 USB 연결되어 있지 않음
- 외부 Wi-Fi, 집 Wi-Fi, 핫스팟 등 다른 네트워크에서 접속 가능
- VSCode / Codex 사용 가능
- MQTT Subscriber / Command Publisher / Dashboard 역할
- 학교 서버용 노트북이 MQTT Broker에 올린 센서값을 구독함
- 외부에서 MQTT `cmd` topic으로 제어 명령을 보냄

주의:

- 개인 게이밍 노트북에서 Pico2 W의 COM 포트를 열려고 하면 안 된다.
- 개인 게이밍 노트북은 MQTT Broker와만 통신한다.
- 외부 네트워크에서 학교 안 Pico2 W를 제어하는 테스트는 이미 성공했다.

---

## 3. 현재 전체 구조

### 3.1 센서값 상행 흐름

```text
Pico2 W
→ USB Serial
→ 학교 서버용 노트북 mqtt_usb_bridge.py
→ MQTT Broker
→ 개인 게이밍 노트북 mqtt_subscribe_test.py / Dashboard
```

### 3.2 제어명령 하행 흐름

```text
개인 게이밍 노트북 mqtt_cmd_test.py / Dashboard
→ MQTT Broker
→ 학교 서버용 노트북 mqtt_usb_bridge.py
→ USB Serial
→ Pico2 W
→ 내장 LED / GP16 / 릴레이 제어
```

---

## 4. 현재까지 성공한 것

### 4.1 센서값 상행 성공

다음 경로가 검증되었다.

```text
Pico2 W
→ USB Serial
→ 학교 서버용 노트북
→ MQTT Broker
→ 개인 게이밍 노트북
```

개인 게이밍 노트북에서 외부 네트워크/핫스팟 상태로도 MQTT payload 수신을 확인했다.

수신 예시:

```json
{
  "lux": 12400,
  "device_id": "pico2w_001",
  "co2_ppm": 560,
  "rh": 62.0,
  "seq": 2090,
  "ec": 0.8,
  "relay_1": 0,
  "type": "telemetry",
  "temp_c": 24.0,
  "ph": 5.82,
  "site_id": "school",
  "zone_id": "room1",
  "bridge_id": "school_server_bridge_001",
  "ts": "2026-07-08T18:58:46+09:00"
}
```

---

### 4.2 제어명령 하행 성공

다음 경로가 검증되었다.

```text
개인 게이밍 노트북
→ MQTT cmd publish
→ MQTT Broker
→ 학교 서버용 노트북 cmd subscribe
→ USB Serial
→ Pico2 W
→ 내장 LED ON/OFF
```

개인 게이밍 노트북에서 명령을 보냈고, 학교 안 Pico2 W의 내장 LED ON/OFF가 정상 동작했다.

즉, 외부 Wi-Fi에서 학교 안 Pico2 W를 제어할 수 있는 통신 구조는 검증 완료되었다.

---

## 5. 현재 테스트용 MQTT Broker

현재는 테스트용으로 HiveMQ Public Broker를 사용한다.

```text
Broker: broker.hivemq.com
Port: 1883
```

주의:

- `broker.hivemq.com`은 공개 테스트 broker이다.
- 실제 릴레이, 펌프, 220V 부하 제어에는 사용하면 안 된다.
- 운영 단계에서는 username/password와 TLS가 있는 broker를 사용해야 한다.
- 운영 후보:
  - HiveMQ Cloud
  - Mosquitto VPS
  - EMQX Cloud
  - 자체 MQTT Broker

---

## 6. Topic 구조

### 6.1 Telemetry

센서값 업로드 topic:

```text
farm/school/room1/pico2w_001/telemetry
```

방향:

```text
Pico2 W → 학교 서버용 노트북 → MQTT Broker → 개인 노트북/Dashboard
```

---

### 6.2 Status

상태 topic:

```text
farm/school/room1/pico2w_001/status
```

사용 목적:

- bridge online
- serial connected
- Pico2 W ready
- 상태 확인 응답

---

### 6.3 Command

제어 명령 topic:

```text
farm/school/room1/pico2w_001/cmd
```

방향:

```text
개인 노트북/Dashboard → MQTT Broker → 학교 서버용 노트북 → Pico2 W
```

중요:

- `cmd` topic은 retained message를 사용하면 안 된다.
- `retain=False`로 publish해야 한다.
- 예전 ON 명령이 broker에 남아 있으면 재접속 시 장비가 갑자기 켜질 위험이 있다.

---

### 6.4 ACK

명령 응답 topic:

```text
farm/school/room1/pico2w_001/ack
```

방향:

```text
Pico2 W → 학교 서버용 노트북 → MQTT Broker → 개인 노트북/Dashboard
```

사용 목적:

- 명령 수신 확인
- Serial 명령 전송 확인
- Pico2 W 응답 확인
- 오류 응답 확인

---

## 7. Payload 구조

### 7.1 Telemetry payload 예시

```json
{
  "type": "telemetry",
  "device_id": "pico2w_001",
  "seq": 2090,
  "temp_c": 24.0,
  "rh": 62.0,
  "co2_ppm": 560,
  "lux": 12400,
  "ec": 0.8,
  "ph": 5.82,
  "relay_1": 0,
  "site_id": "school",
  "zone_id": "room1",
  "bridge_id": "school_server_bridge_001",
  "ts": "2026-07-08T18:58:46+09:00"
}
```

설명:

- Pico2 W는 기본 센서값과 `device_id`, `seq`, `relay_1` 등을 보낸다.
- 학교 서버용 노트북이 `site_id`, `zone_id`, `bridge_id`, `ts`를 추가한다.
- timestamp는 Pico2 W가 아니라 학교 서버용 노트북에서 붙이는 것이 좋다.

---

### 7.2 Command payload 예시

릴레이 ON:

```json
{
  "type": "cmd",
  "cmd_id": "cmd_1783506127_e6f9",
  "target": "relay_1",
  "action": "on"
}
```

릴레이 OFF:

```json
{
  "type": "cmd",
  "cmd_id": "cmd_1783506128_ab12",
  "target": "relay_1",
  "action": "off"
}
```

5초 ON 후 자동 OFF:

```json
{
  "type": "cmd",
  "cmd_id": "cmd_1783506129_cd34",
  "target": "relay_1",
  "action": "on",
  "duration_sec": 5
}
```

상태 확인:

```json
{
  "type": "cmd",
  "cmd_id": "cmd_1783506130_ef56",
  "target": "relay_1",
  "action": "status"
}
```

지원 action:

```text
on
off
toggle
status
```

---

### 7.3 ACK payload 예시

```json
{
  "type": "ack",
  "cmd_id": "cmd_1783506127_e6f9",
  "result": "ok",
  "serial_response": "ACK:RELAY1_ON",
  "ts": "2026-07-08T19:20:00+09:00"
}
```

---

## 8. Pico2 W 쪽 역할

Pico2 W는 현재 Wi-Fi를 사용하지 않는다.

역할:

- 가짜 센서값 생성
- 나중에 실제 센서값 읽기
- USB Serial로 JSON Lines 출력
- USB Serial로 명령 수신
- 내장 LED / GP16 제어
- ACK 또는 status 응답 출력

Pico2 W의 출력 방식:

```text
한 줄에 JSON 하나
또는
ACK/ERR 문자열 한 줄
```

예:

```json
{"type":"telemetry","device_id":"pico2w_001","seq":1,"temp_c":24.1}
```

예:

```text
ACK:RELAY1_ON
ACK:RELAY1_OFF
ERR:UNKNOWN_COMMAND
```

---

## 9. 학교 서버용 노트북 쪽 역할

학교 서버용 노트북은 Gateway이다.

필수 실행 파일:

```text
mqtt_usb_bridge.py
```

역할:

- Pico2 W COM 포트 열기
- USB Serial 데이터 수신
- JSON telemetry parse
- timestamp 추가
- MQTT telemetry publish
- MQTT cmd topic subscribe
- cmd payload를 Serial 명령으로 변환
- Pico2 W로 Serial 명령 전송
- Pico2 W의 ACK/ERR/status 응답을 MQTT로 publish

중요:

- 학교 서버용 노트북에서 `mqtt_usb_bridge.py`가 실행 중이어야 한다.
- 이 프로그램이 꺼져 있으면 외부 개인 노트북은 센서값도 못 받고 제어도 못 한다.
- Thonny가 Pico2 W COM 포트를 잡고 있으면 `mqtt_usb_bridge.py`가 실패한다.

---

## 10. 개인 게이밍 노트북 쪽 역할

개인 게이밍 노트북은 외부 관리자 PC이다.

현재 사용한 테스트 파일:

```text
mqtt_subscribe_test.py
mqtt_cmd_test.py
```

역할:

- MQTT telemetry topic subscribe
- 학교에서 올라오는 센서 payload 확인
- MQTT cmd topic publish
- ack/status topic subscribe
- 대시보드 실행

중요:

- 개인 게이밍 노트북은 Pico2 W COM 포트를 열지 않는다.
- 개인 게이밍 노트북은 MQTT Broker와만 통신한다.
- 학교 서버용 노트북과 같은 네트워크일 필요가 없다.
- 핫스팟/외부 Wi-Fi에서도 telemetry 수신과 cmd 제어가 동작했다.

---

## 11. 현재 파일 구성 권장안

Codex에서 프로젝트를 정리할 때 다음 구조를 권장한다.

```text
school_mqtt_test/
├─ PROJECT_CONTEXT_MQTT_PICO2W.md
├─ README.md
├─ config.school.json
├─ config.home.json
├─ pico/
│  └─ main.py
├─ school_server/
│  └─ mqtt_usb_bridge.py
├─ home_client/
│  ├─ mqtt_subscribe_test.py
│  ├─ mqtt_cmd_test.py
│  └─ dashboard_mqtt.py
└─ backups/
   ├─ main_success_led_control.py
   ├─ mqtt_usb_bridge_success.py
   └─ mqtt_cmd_test_success.py
```

---

## 12. Codex 작업 시 반드시 지킬 구분

### 학교 서버용 노트북에서 수정·실행할 파일

```text
pico/main.py
school_server/mqtt_usb_bridge.py
config.school.json
```

실행 위치:

```text
학교 서버용 노트북 VSCode 터미널
```

Pico2 W 코드 업로드:

```text
학교 서버용 노트북 Thonny
```

---

### 개인 게이밍 노트북에서 수정·실행할 파일

```text
home_client/mqtt_subscribe_test.py
home_client/mqtt_cmd_test.py
home_client/dashboard_mqtt.py
config.home.json
```

실행 위치:

```text
개인 게이밍 노트북 VSCode 터미널
```

---

## 13. 현재 확인된 문제와 해결 기록

### 문제 1: 학교 Wi-Fi가 WPA/WPA2-Enterprise 방식

해결:

- Pico2 W를 학교 Wi-Fi에 직접 연결하지 않음
- Pico2 W는 USB Serial만 사용
- 학교 서버용 노트북이 학교 Wi-Fi 인증과 MQTT 통신 담당

---

### 문제 2: USB RX / MQTT TX가 안 나옴

원인 후보:

- Thonny가 COM 포트를 잡고 있음
- Pico2 W `main.py`가 실행되지 않음
- COM 포트 번호가 다름
- Pico2 W 재부팅이 안 됨

해결:

- Thonny 종료
- Pico2 W USB 뺐다 다시 꽂기
- `python -m serial.tools.list_ports`로 COM 포트 확인
- `SERIAL_PORT` 수정

---

### 문제 3: 개인 노트북 터미널 출력이 너무 길어짐

해결:

- MQTT 메시지는 계속 받되 최신 payload만 저장
- 터미널 출력은 10초마다 한 번만 갱신
- `PRINT_INTERVAL_SEC = 10` 사용

---

### 문제 4: LED 제어가 안 됨

원인:

- 학교 서버용 노트북에서 코드 저장을 안 해서 예전 bridge 코드가 실행되고 있었음

해결:

- 양방향 bridge 코드 저장
- 다시 실행
- 외부 개인 노트북에서 LED ON/OFF 성공

---

## 14. 다음 개발 단계

### 14.1 현재 성공 코드 백업

가장 먼저 해야 한다.

```text
backups/
├─ main_success_led_control.py
├─ mqtt_usb_bridge_success.py
└─ mqtt_cmd_test_success.py
```

---

### 14.2 config 파일 분리

Codex에게 다음 작업을 시킬 것.

목표:

- broker 정보
- topic 정보
- COM 포트
- 출력 간격
- device_id
- site_id
- zone_id
- bridge_id

을 코드에서 분리한다.

예:

```json
{
  "serial_port": "COM5",
  "serial_baudrate": 115200,
  "mqtt_broker": "broker.hivemq.com",
  "mqtt_port": 1883,
  "mqtt_client_id": "school_server_bridge_001",
  "site_id": "school",
  "zone_id": "room1",
  "device_id": "pico2w_001",
  "topics": {
    "telemetry": "farm/school/room1/pico2w_001/telemetry",
    "status": "farm/school/room1/pico2w_001/status",
    "cmd": "farm/school/room1/pico2w_001/cmd",
    "ack": "farm/school/room1/pico2w_001/ack"
  }
}
```

---

### 14.3 Dashboard 연결

개인 게이밍 노트북에서 Codex로 기존 dashboard에 MQTT subscribe 기능을 붙인다.

요구사항:

- `telemetry` topic subscribe
- 최신 temp_c, rh, co2_ppm, lux, ec, ph 표시
- relay_1 상태 표시
- ts 표시
- cmd publish 버튼 추가
  - ON
  - OFF
  - TOGGLE
  - STATUS
  - 5초 ON 후 자동 OFF
- ack/status 출력 영역 추가

---

### 14.4 실제 센서값으로 교체

현재 telemetry는 가짜 센서값이다.
다음 단계에서 실제 센서값으로 교체한다.

우선순위:

1. SHT40 온습도
2. 조도 센서
3. CO2 센서
4. EC 센서
5. pH 센서

---

### 14.5 릴레이 제어 확장

현재는 Pico2 W 내장 LED ON/OFF까지 성공했다.

다음 단계:

```text
Pico2 W GP16
→ 릴레이 모듈 IN1
→ 릴레이 딸깍 테스트
→ 12V 저전압 부하 테스트
→ 실제 장비 제어
```

주의:

- 바로 220V 펌프를 연결하지 말 것.
- 먼저 GP16 출력 확인.
- 그 다음 릴레이 입력 확인.
- 그 다음 저전압 부하 확인.
- 마지막에 AC 부하를 연결할 것.

---

## 15. 안전 주의사항

- `broker.hivemq.com`은 공개 broker이므로 실제 펌프나 220V 부하 제어에 사용하면 안 된다.
- cmd topic은 retain=False로 publish해야 한다.
- ON 명령에는 가능하면 `duration_sec`를 넣어 무한 ON을 방지한다.
- Pico2 W 재부팅 시 릴레이 기본 상태는 OFF여야 한다.
- 실제 릴레이 연결 전에는 내장 LED와 저전압 LED로만 테스트한다.
- Pico2 W GPIO는 3.3V logic이다.
- 릴레이 모듈이 3.3V trigger를 지원하는지 확인해야 한다.
- 릴레이 코일을 GPIO가 직접 구동하면 안 된다.
- AC 220V 제어는 차단기, 퓨즈, 절연, 접지, 수동 차단 스위치, 비상 OFF를 고려해야 한다.

---

## 16. Codex에 넘길 첫 요청문

Codex에 아래처럼 요청하면 된다.

```text
PROJECT_CONTEXT_MQTT_PICO2W.md를 읽고 현재 프로젝트 구조를 정리해줘.

중요한 점은 학교 서버용 노트북과 개인 게이밍 노트북의 역할을 절대 혼동하지 않는 거야.

학교 서버용 노트북은 Pico2 W와 USB로 연결되어 있고 mqtt_usb_bridge.py를 실행하는 Gateway야.
개인 게이밍 노트북은 외부에서 MQTT telemetry를 보고 cmd를 보내는 관리자 PC야.

현재까지 성공한 것:
1. Pico2 W → USB → 학교 서버 노트북 → MQTT → 개인 노트북 telemetry 수신 성공
2. 개인 노트북 → MQTT cmd → 학교 서버 노트북 → USB → Pico2 W 내장 LED ON/OFF 성공

다음 작업:
1. 현재 성공 코드를 backups 폴더에 백업해줘.
2. school_server/mqtt_usb_bridge.py를 config.school.json 기반으로 정리해줘.
3. home_client/mqtt_subscribe_test.py와 mqtt_cmd_test.py를 config.home.json 기반으로 정리해줘.
4. 기존 대시보드에 MQTT telemetry 표시와 cmd 버튼을 붙일 준비를 해줘.
5. README.md에 학교 서버용 노트북에서 실행할 것과 개인 게이밍 노트북에서 실행할 것을 분리해서 적어줘.
6. broker.hivemq.com은 테스트 broker로 유지하되, 운영 broker로 바꾸기 쉽게 구조화해줘.
```

---

## 17. 현재 결론

현재 프로젝트는 다음 단계까지 성공했다.

```text
외부 Wi-Fi의 개인 게이밍 노트북에서
학교 안 Pico2 W의 센서값을 받고,
학교 안 Pico2 W의 내장 LED를 제어하는 데 성공했다.
```

다음 핵심 작업은 다음이다.

```text
1. 성공 코드 백업
2. 설정 파일 분리
3. 대시보드 연동
4. 실제 센서값 교체
5. 릴레이 모듈 테스트
6. 운영용 MQTT Broker 전환
```
