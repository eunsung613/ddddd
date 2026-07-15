# PE350 외부망 대시보드 시험

이 시험은 EC, pH, 양액 온도를 읽어서 표시하는 단계만 다룬다. 펌프와 릴레이 제어는 하지 않는다.

## 역할 분리

### 서버용 노트북 (학교)

- Pico 2 W와 USB로 연결한다.
- Pico에서 PE350 값을 읽는다.
- 측정값을 MQTT에 발행한다.
- 대시보드를 실행하지 않는다.

### 게이밍 노트북 (집 또는 다른 인터넷망)

- Pico나 PE350을 연결하지 않는다.
- MQTT 측정값만 구독한다.
- FastAPI 대시보드를 실행한다.

## 1. 서버용 노트북 준비

GitHub 저장소 폴더에서 다음 명령을 실행한다.

```powershell
git pull
py -m pip install -r requirements.txt
Copy-Item config.school.example.json config.school.json
```

Windows 장치 관리자에서 Pico의 실제 COM 번호를 확인하고 `config.school.json`의 다음 값을 바꾼다.

```json
"serial_port": "COM번호"
```

Thonny를 완전히 종료한다. Thonny와 브리지 프로그램은 같은 COM 포트를 동시에 사용할 수 없다.

```powershell
py school_server\pe350_mqtt_bridge.py
```

성공하면 약 1초마다 다음 형식의 출력이 보인다.

```text
발행 #1: EC 0.109 dS/m | pH 7.20 | 양액 온도 21.7 °C
```

## 2. 게이밍 노트북 준비

게이밍 노트북의 저장소에 `config.home.json`이 있어야 한다. MQTT topic은 서버용 설정과 같아야 한다.

대시보드 폴더에서 다음 명령을 실행한다.

```powershell
py -m pip install -r requirements.txt
py server.py
```

브라우저에서 `http://127.0.0.1:8765`를 연다.

## 3. 외부망 확인

1. 서버용 노트북과 게이밍 노트북을 서로 다른 Wi-Fi 또는 핫스팟에 연결한다.
2. 서버용 노트북 터미널에서 MQTT 발행 번호가 계속 증가하는지 확인한다.
3. 게이밍 노트북 대시보드에서 EC, pH, 양액 온도가 갱신되는지 확인한다.
4. 서버용 브리지를 종료했을 때 10초 뒤 대시보드가 `OFFLINE`으로 바뀌는지 확인한다.

이 구조에서는 첫 외부망 시험에 Cloudflare가 필요 없다. MQTT가 두 노트북 사이의 측정값을 전달하고, 웹 대시보드는 게이밍 노트북 안에서만 연다.

## 주의

현재 설정의 `broker.hivemq.com`은 공개 시험용 브로커다. EC, pH 읽기 시험에만 사용한다. 실제 펌프나 릴레이 제어 명령에는 사용하지 않는다.
