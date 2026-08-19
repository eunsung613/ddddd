# Broccoli One 통합 대시보드

학교 서버용 Windows 노트북에서 다음 기능을 한 프로세스로 실행합니다.

- Pico 2 W USB 센서 수집: AHT10, SCD40, PE350
- SQLite 시계열 저장 및 기간별 조회
- Hikvision JPEG 정기 촬영 및 원본 저장
- OpenAI 이미지·센서 분석과 실제 모델명 기록
- AI/규칙 제안 → 사람 승인/거절 → 안전검사 → Pico 명령
- 2쪽 일일 생육관찰 PDF와 선택적 텔레그램 전송
- 00·06·12·18시 촬영/분석, 매일 20시 보고서 스케줄
- 학교 서버 MQTT 발행과 외부 게이밍 노트북 읽기 전용 구독

## 안전 설계

- `SMARTFARM_CONTROL_ENABLED=0`이 기본값이므로 승인해도 실제 GPIO 출력은 없습니다.
- EC와 pH 정량펌프는 `SMARTFARM_CHEMICAL_CONTROL_ENABLED=1`을 별도로 설정해야 합니다.
- Pico는 부팅할 때 모든 LOW 트리거 릴레이를 OFF로 만들고 장치별 최대 작동시간 후 자동 OFF합니다.
- AI는 릴레이 명령을 직접 전송하지 않습니다. 현재 자동 장치 제안은 고정 임계값 규칙이 만들고 사람이 최종 승인합니다.
- 센서 데이터가 20초 이상 지연되면 실물 제어를 차단합니다.

## 게이밍 노트북에서 안전하게 확인

```powershell
py -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File school_server\run_dashboard_demo.ps1
```

브라우저에서 `http://127.0.0.1:8765`를 엽니다. 모든 센서값은 `모의 데이터`로 표시되고 하드웨어 명령은 차단됩니다.

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

이 실행 스크립트는 `SMARTFARM_MQTT_MODE=publish`를 적용하므로 통합 센서값을 `config.school.json`의 telemetry topic으로 발행합니다. 별도의 `pe350_mqtt_bridge.py`를 동시에 실행하면 COM 포트가 충돌하므로 실행하지 않습니다.

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
SMARTFARM_CONTROL_ENABLED=0
SMARTFARM_CHEMICAL_CONTROL_ENABLED=0
```

실물 제어 활성화는 비상정지, 릴레이 자동 OFF, 각 액추에이터 단독 시험, USB 끊김 재시험을 마친 뒤 마지막에 진행합니다.

## 카메라

카메라 비밀번호는 Git에 올리지 않고 `.env`에만 저장합니다. Hikvision 기본 JPEG 경로 예시는 다음과 같습니다.

```text
http://192.168.0.60/ISAPI/Streaming/channels/101/picture
```

서버가 Digest 인증으로 사진을 가져오며 카메라 IP/포트를 외부 인터넷에 직접 공개하지 않습니다.

## 외부 접속

서버는 `0.0.0.0:8765`에서 실행되지만 이 사실만으로 안전한 외부 배포가 완료되는 것은 아닙니다. 외부 접속 전에는 반드시 다음을 적용해야 합니다.

- `.env`의 `DASHBOARD_USERNAME`, `DASHBOARD_PASSWORD` 설정
- Cloudflare Tunnel 또는 VPN을 통한 HTTPS
- 카메라 관리 페이지와 RTSP 포트 직접 공개 금지
- 학교 정책에 맞는 접근 계정 관리

현재 `broker.hivemq.com:1883`과 기존 topic은 외부망 센서 표시 시험에만 사용합니다. 실제 액추에이터 제어에는 사용자 인증과 TLS가 있는 전용 Broker가 필요합니다.
