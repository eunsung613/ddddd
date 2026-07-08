# Pico2 W MQTT Gateway

학교의 Pico2 W를 USB Serial로 학교 서버용 노트북에 연결하고, MQTT를 통해 개인 게이밍 노트북에서 센서값을 확인하고 명령을 보내는 프로젝트입니다.

## 장비 역할

### 학교 서버용 노트북

- Pico2 W와 USB로 직접 연결합니다.
- `pico/main.py`를 Thonny로 Pico2 W에 저장합니다.
- Thonny를 종료한 뒤 `school_server/mqtt_usb_bridge.py`를 실행합니다.
- 개인 노트북용 프로그램은 이 장비에서 실행하지 않습니다.

현재 학교 노트북의 성공 코드는 아직 이 저장소에 복사되지 않았습니다. 파일을 확보하기 전까지 빈 구현을 추측해서 만들지 않습니다.

### 개인 게이밍 노트북

- Pico2 W의 COM 포트를 열지 않습니다.
- MQTT Broker와만 통신합니다.
- 센서값 수신: `home_client/mqtt_subscribe_test.py`
- 제어 명령: `home_client/mqtt_cmd_test.py`

## 개인 노트북 실행

PowerShell에서 프로젝트 폴더로 이동한 뒤 실행합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item config.home.example.json config.home.json
python home_client\mqtt_subscribe_test.py
```

명령 발행 프로그램은 별도 터미널에서 실행합니다.

```powershell
.\.venv\Scripts\Activate.ps1
python home_client\mqtt_cmd_test.py
```

## 설정 파일

- 예제 설정은 Git으로 공유합니다.
- 실제 장비별 설정인 `config.home.json`, `config.school.json`은 Git에서 제외합니다.
- 향후 Broker 비밀번호와 인증서는 저장소에 올리지 않습니다.

## 현재 안전 범위

- `broker.hivemq.com:1883`은 공개 테스트 Broker입니다.
- 현재 코드는 내장 LED와 저전압 테스트에만 사용합니다.
- 실제 펌프나 220V 부하는 연결하지 않습니다.
- 제어 명령은 항상 `retain=False`를 사용합니다.

## GitHub 연결

이 폴더는 로컬 Git 저장소로 준비되어 있습니다. GitHub에서 비공개 저장소를 만든 뒤 표시되는 원격 저장소 주소를 사용합니다.

```powershell
git remote add origin <GITHUB_PRIVATE_REPOSITORY_URL>
git branch -M main
git push -u origin main
```
