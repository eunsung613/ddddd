# 학교 노트북 작업 인수인계

## Codex에게 처음 보낼 문장

아래 문장을 학교 노트북의 새 Codex 채팅에 보내세요.

> 이 컴퓨터는 Pico2 W가 USB로 연결된 학교 서버용 노트북이다. 저장소의 `PROJECT_CONTEXT_MQTT_PICO2W.md`, `SCHOOL_HANDOFF.md`, `school_server/README.md`, `pico/README.md`를 먼저 읽고 현재 상태를 정리해 줘. 추측해서 코드를 만들거나 기존에 동작하는 파일을 수정하지 말고, 확인된 학교용 `main.py`와 `mqtt_usb_bridge.py`를 저장소에 안전하게 복사하는 작업부터 도와줘.

## 현재 완료된 상태

- 개인 게이밍 노트북에서 프로젝트 구조를 만들었다.
- GitHub 비공개 저장소에 `main` 브랜치를 게시했다.
- 현재 원격 저장소: `https://github.com/eunsung613/ddddd`
- 첫 커밋: `a13366f` (`MQTT 프로젝트 초기 구조 추가`)
- 개인 노트북에서 검증한 MQTT 구독/명령 프로그램은 `home_client/`와 `backups/`에 있다.
- `config.home.json` 같은 실제 설정 파일은 Git에 올라가지 않도록 제외했다.
- 학교에서 실제로 동작한 `main.py`와 `mqtt_usb_bridge.py`는 아직 저장소에 복사하지 않았다.

## 학교 노트북에서 할 일

1. 이 비공개 저장소를 학교 노트북에 Clone하고 폴더를 VS Code로 연다.
2. Pico2 W에서 실제 동작 중인 `main.py`를 먼저 확인하고 `pico/main.py`로 복사한다.
3. 학교 노트북에서 실제 동작한 `mqtt_usb_bridge.py`를 확인하고 `school_server/mqtt_usb_bridge.py`로 복사한다.
4. 복사본과 원본이 같은지 확인한 뒤에만 Commit/Push한다.
5. 이후 학교용 설정 분리와 실행 방법 정리를 진행한다.

## 중요한 제한

- 현재 장비 역할은 **학교 서버용 노트북**이다. 개인 게이밍 노트북으로 가정하지 않는다.
- 동작하는 원본 파일을 바로 고치지 않는다. 먼저 저장소에 백업하고 내용과 실행 환경을 확인한다.
- Pico2 W의 COM 포트는 학교 노트북에서 직접 확인한다. 번호를 추측하지 않는다.
- Thonny가 COM 포트를 사용 중이면 브리지 프로그램이 같은 포트를 열 수 없다.
- 시험은 내장 LED처럼 안전한 대상으로 시작한다. 펌프, 릴레이, 220V 장치는 사용자가 명시적으로 확인하기 전에는 제어하지 않는다.
- `broker.hivemq.com:1883`은 공개 테스트 브로커이므로 대회 실운영용으로 확정하지 않는다.

## 검증된 통신 구조

```text
Pico2 W
  ↕ USB Serial
학교 서버용 노트북 (mqtt_usb_bridge.py)
  ↕ MQTT Broker
개인 게이밍 노트북 (Subscriber / Command Publisher / Dashboard)
```

학교 Wi-Fi가 WPA/WPA2-Enterprise 방식이라 Pico2 W가 직접 접속하지 않고, 학교 노트북이 USB Serial과 MQTT 사이의 게이트웨이 역할을 한다.
