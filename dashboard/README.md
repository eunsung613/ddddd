# Broccoli One 통합 대시보드

학교 서버용 Windows 노트북에서 다음 기능을 한 프로세스로 실행합니다.

- Pico 2 W USB 센서 수집: AHT10, SCD40, PE350
- SQLite 시계열 저장 및 기간별 조회
- Hikvision JPEG 정기 촬영 및 원본 저장
- OpenAI 이미지·센서 분석과 실제 모델명 기록
- AI/규칙 제안 → 사람 승인/거절 → 안전검사 → Pico 명령
- 일일 생육관찰 PDF(액추에이터 감사 기록 포함)와 선택적 텔레그램 전송
- 00·06·12·18시 촬영/분석, 매일 20시 보고서 스케줄
- 학교 서버 MQTT 발행과 외부 게이밍 노트북 읽기 전용 구독

## 안전 설계

- `SMARTFARM_CONTROL_ENABLED=0`이 기본값이므로 승인해도 실제 GPIO 출력은 없습니다.
- EC와 pH 정량펌프는 `SMARTFARM_CHEMICAL_CONTROL_ENABLED=1`을 별도로 설정해야 합니다.
- LED 광주기는 AI와 분리된 고정 서울시간 스케줄이며 `SMARTFARM_LED_SCHEDULE_HARDWARE_ENABLED=1`일 때 LED만 명령할 수 있습니다.
- Pico는 부팅할 때 모든 LOW 트리거 릴레이를 OFF로 만들고 장치별 최대 작동시간 후 자동 OFF합니다.
- AI는 릴레이 명령을 직접 전송하지 않습니다. 제어 요청은 봇/고정 안전 규칙이 만들고 사람이 텔레그램에서 최종 승인합니다. 각 요청·승인·거절·안전 차단·Pico 전송·Pico 응답은 SQLite와 일일 PDF에 기록됩니다.
- 센서 데이터가 20초 이상 지연되면 실물 제어를 차단합니다.
- SCD40을 의도적으로 제거한 설치에서는 `SMARTFARM_SCD40_REQUIRED=0`으로 두면
  AHT10·PE350 실측값만으로 제어 근거를 판정합니다.

## 게이밍 노트북에서 모의 화면 확인

```powershell
py -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File school_server\run_dashboard_demo.ps1
```

브라우저에서 `http://127.0.0.1:8765`를 엽니다. 모든 센서값은 `모의 데이터`로 표시되고 하드웨어 명령은 차단됩니다.

## 서로 다른 Wi-Fi에서 MQTT로 실측 센서 보기

학교 서버는 통합 대시보드가 COM 포트를 계속 소유한 채, 이미 수집한 센서값만
MQTT에 발행합니다. 별도 USB 브리지를 동시에 실행하지 않습니다. MQTT 메시지에는
카메라 사진·비밀번호·액추에이터 명령을 넣지 않으며 `cmd` 토픽도 구독하지 않습니다.

학교 서버 `.env`:

```dotenv
SMARTFARM_SIMULATION=0
SMARTFARM_MQTT_PUBLISH_ENABLED=1
SMARTFARM_MQTT_SUBSCRIBE_ENABLED=0
SMARTFARM_MQTT_CONFIG=config.school.json
```

게이밍 노트북에서는 저장소를 받은 뒤 다음을 준비합니다.

```powershell
git pull
py -m pip install -r requirements.txt
Copy-Item config.home.example.json config.home.json
Copy-Item .env.example .env
```

게이밍 노트북 `.env`:

```dotenv
SMARTFARM_SIMULATION=0
SMARTFARM_AUTOMATION_ENABLED=0
SMARTFARM_CONTROL_ENABLED=0
SMARTFARM_CHEMICAL_CONTROL_ENABLED=0
SMARTFARM_LED_SCHEDULE_HARDWARE_ENABLED=0
SMARTFARM_MQTT_PUBLISH_ENABLED=0
SMARTFARM_MQTT_SUBSCRIBE_ENABLED=1
SMARTFARM_MQTT_CONFIG=config.home.json
```

`config.home.json`의 broker와 `topics.telemetry`가 학교 서버의
`config.school.json`과 같아야 합니다. 그 다음 게이밍 노트북에서 실행합니다.

```powershell
py -m dashboard.server
```

브라우저에서 `http://127.0.0.1:8765`를 열면 MQTT로 받은 실측값과, 게이밍
노트북에서 수신을 시작한 뒤 누적된 그래프를 볼 수 있습니다. 서버 카메라 사진과
과거 SQLite 자료는 MQTT 센서 토픽에 포함되지 않습니다.

현재 예시의 `broker.hivemq.com:1883`은 인증 없는 공개 시험 브로커입니다.
조회 시험에만 사용하고 펌프·릴레이 제어에는 사용하지 않습니다. 운영 전에는
TLS와 계정 인증을 제공하는 전용 브로커로 교체해야 합니다.

## 학교 서버 노트북에서 실행

1. 저장소에서 `git pull`을 실행합니다.
2. `py -m pip install -r requirements.txt`를 실행합니다.
3. `.env.example`을 `.env`로 복사하고 학교 설정과 비밀값을 입력합니다.
4. `config.school.example.json`을 `config.school.json`으로 복사하고 Pico COM 포트를 입력합니다.
5. Pico의 `config.py`에 현재 RS485/I2C 설정이 저장되어 있는지 확인합니다.
6. 다음 명령으로 통합 런타임을 업로드하고 서버를 시작합니다.

```powershell
powershell -ExecutionPolicy Bypass -File school_server\run_smartfarm_dashboard.ps1
```

학교 서버의 `.env`에서 `SMARTFARM_MQTT_PUBLISH_ENABLED=1`로 설정하면 통합 센서값을 `config.school.json`의 telemetry topic으로 발행합니다. 별도의 `pe350_mqtt_bridge.py`를 동시에 실행하면 COM 포트가 충돌하므로 실행하지 않습니다.

## 외부 Wi-Fi의 게이밍 노트북

학교 서버와 동일한 telemetry topic이 들어 있는 `config.home.json`을 준비한 뒤 실행합니다.

```powershell
git pull
py -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File home_client\run_remote_dashboard.ps1
```

브라우저에서 `http://127.0.0.1:8765`를 열면 학교 서버의 실측값이 `MQTT LIVE`로 표시됩니다. 게이밍 노트북 모드는 조회 전용이며 MQTT 제어 명령을 발행하지 않습니다.

학교 서버에서는 `.env`의 다음 값을 사용합니다.

```dotenv
SMARTFARM_SIMULATION=0
SMARTFARM_AUTOMATION_ENABLED=1
SMARTFARM_PICO_UPLOAD_ENABLED=0
SMARTFARM_CONTROL_ENABLED=0
SMARTFARM_CHEMICAL_CONTROL_ENABLED=0
SMARTFARM_LED_SCHEDULE_HARDWARE_ENABLED=0
SMARTFARM_MQTT_PUBLISH_ENABLED=1
SMARTFARM_MQTT_SUBSCRIBE_ENABLED=0
SMARTFARM_MQTT_CONFIG=config.school.json
```

`SMARTFARM_PICO_UPLOAD_ENABLED=1`은 액추에이터 전원을 분리하고 Pico
런타임 파일을 갱신할 때만 일시적으로 사용합니다. 평상시 서버 실행에서는
`0`으로 유지합니다. Pico의 `ACTUATOR_OUTPUTS_ARMED`도 기본적으로 `False`라서
서버와 장치 양쪽 안전장치를 모두 명시적으로 해제하기 전에는 ON 출력이
거부됩니다.

실물 제어 활성화는 비상정지, 릴레이 자동 OFF, 각 액추에이터 단독 시험, USB 끊김 재시험을 마친 뒤 마지막에 진행합니다.

LED 광주기만 사용할 때는 다른 제어 플래그를 `0`으로 유지하고
`SMARTFARM_LED_SCHEDULE_HARDWARE_ENABLED=1`만 설정합니다. 대시보드 자동화
센터에서 ON/OFF 시각과 활성 여부를 저장하면 서버가 서울시간 기준으로
LED 상태를 맞춥니다. 광주기는 최대 16시간이며 비활성화하면 OFF 명령을
보냅니다.

OpenAI API 키는 시스템 화면에서 저장할 수 있습니다. 키는 브라우저로 다시
반환되지 않고 서버 노트북의 `.env`에만 기록됩니다. 비밀 설정 및 LED 광주기
변경 API는 서버 노트북의 로컬 접속에서만 허용합니다. 원격으로 사용할 때는
반드시 로그인과 HTTPS/VPN을 먼저 적용합니다.

## 카메라

카메라 비밀번호는 Git에 올리지 않고 `.env`에만 저장합니다. Hikvision 기본 JPEG 경로 예시는 다음과 같습니다.

```text
http://192.168.0.60/ISAPI/Streaming/channels/101/picture
```

서버가 Digest 인증으로 사진을 가져오며 카메라 IP/포트를 외부 인터넷에 직접 공개하지 않습니다.

시스템 페이지의 `Hikvision 카메라 3대 설정`에서 이름, JPEG 주소, 사용자명과 비밀번호를 저장하고 바로 촬영 시험을 할 수 있습니다. 새 카메라는 모두 기본 IP `192.168.1.64`를 사용할 수 있으므로 한 대씩 활성화한 뒤 학교 카메라망의 `192.168.0.60`, `.61`, `.62`처럼 서로 다른 고정 IP를 먼저 지정해야 합니다. 서버 노트북 이더넷에는 같은 망의 `192.168.0.100/24` 주소가 필요합니다. 대시보드는 수동 촬영과 자동화가 켜진 경우 00·06·18시 정기 촬영 결과를 카메라별로 표시합니다. 텔레그램 정오 브리핑은 별도로 12시에 새 사진을 촬영합니다.

## 텔레그램 정오 브리핑과 승인

시스템 페이지의 `텔레그램 정오 알림·최종 승인`에서 봇 토큰, 대상 채팅 ID,
승인자 Telegram 숫자 ID 또는 FFK 그룹 전체 승인 옵션을 저장합니다. 토큰은 서버의 `.env`에만 저장되며 화면에
다시 표시되지 않습니다. 매일 12:00(Asia/Seoul)에 카메라 촬영, AI 관찰, 센서
실측값을 한 메시지와 사진으로 전송합니다.

승인 기능은 다음 값이 모두 저장되고 활성화됐을 때만 작동합니다.

- `TELEGRAM_BOT_TOKEN`과 `TELEGRAM_CHAT_ID`
- 쉼표·줄바꿈으로 구분한 `TELEGRAM_APPROVER_USER_IDS` (지정 승인자), 또는
  `SMARTFARM_TELEGRAM_ALLOW_GROUP_MEMBERS=1` (FFK 전체 구성원)
- `SMARTFARM_TELEGRAM_APPROVAL_ENABLED=1`

FFK 전체 구성원 승인을 사용할 때는 Telegram의 현재 구성원 여부를 승인 시점에 확인하므로,
봇을 FFK 그룹의 관리자로 지정해야 합니다. 이 봇에는 메시지 삭제·초대·관리 권한이 필요
없으며, 관리자 지위는 구성원 확인용입니다. 승인 버튼은 허용된 채팅과 사용자 ID에서만
처리하며, 기본 유효시간은 10분입니다.
버튼을 누르는 것만으로는 AI가 장치를 직접 제어하지 않습니다. 기존의 센서 신선도,
최대 작동시간, EC/pH 별도 잠금, Pico 장치측 잠금을 모두 다시 통과한 뒤에만 명령이
전송됩니다. 현재 자동 제안 범위는 과고온·과습의 환풍기뿐입니다. EC/pH·원수·양액
펌프는 목표값과 수위 검증이 완성되기 전까지 AI 자동 제안 대상이 아닙니다.

원수·양액 공급·교반·EC·pH 정량펌프도 제어 화면에서 요청할 수 있으며, 요청은
FFK 텔레그램의 승인/거절 버튼을 거쳐야 합니다. EC/pH 펌프는 별도 화학 제어 잠금이
해제된 경우에만 승인 후 Pico로 전송됩니다. 모든 요청, 사람 결정, 안전 차단, 명령
전송, Pico 응답은 `액추에이터 작동 기록`과 당일 PDF의 감사 기록 표에 보관됩니다.

`SMARTFARM_SENSOR_ALERTS_ENABLED=1`과 `SMARTFARM_NUTRIENT_FEEDBACK_ENABLED=1`을
모두 켜면, 서버가 60초마다 신선한 실측값을 확인합니다. EC가 1.5 dS/m 미만이면
A+B 양액펌프 보정, pH가 6.5 초과이면 산성액 보정의 텔레그램 승인 요청을 한 번만
보냅니다. 승인된 보정 세션은 설정된 시간의 A+B 주입(최대 10초) 또는 산성액 주입(최대 5초) → 30초 교반 → PE350 재측정을 최대 3회 반복하며,
EC 1.5~2.0 또는 pH 5.5~6.5 도달, 센서 지연, pH 하한 아래, 횟수 제한에서 즉시 끝납니다.
횟수 제한 뒤에도 값이 기준 밖이면 새 텔레그램 재승인 요청을 보내므로, 사람이 매 묶음의
추가 주입을 확인하면서 목표값까지 이어갈 수 있습니다. 새 알림은 같은 항목에 대해 기본
15분 간격으로 제한됩니다.

봇에 다른 서비스의 webhook이 설정되어 있으면 Telegram long polling이 동작하지
않습니다. 시스템 페이지의 `봇 연결 확인`에서 이를 확인하고, webhook이 있으면 해당
서비스의 webhook을 먼저 정리합니다. 이 서버는 승인 수신을 위해 외부 webhook 포트를
열지 않습니다.

## 외부 접속

서버는 `0.0.0.0:8765`에서 실행되지만 이 사실만으로 안전한 외부 배포가 완료되는 것은 아닙니다. 외부 접속 전에는 반드시 다음을 적용해야 합니다.

- `.env`의 `DASHBOARD_USERNAME`, `DASHBOARD_PASSWORD` 설정
- Cloudflare Tunnel 또는 VPN을 통한 HTTPS
- 카메라 관리 페이지와 RTSP 포트 직접 공개 금지
- 학교 정책에 맞는 접근 계정 관리

현재 `broker.hivemq.com:1883`과 기존 topic은 외부망 센서 표시 시험에만 사용합니다. 실제 액추에이터 제어에는 사용자 인증과 TLS가 있는 전용 Broker가 필요합니다.
