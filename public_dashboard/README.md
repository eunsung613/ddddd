# FFK 브로콜리 외부 조회 전용 대시보드

이 프로젝트는 Vercel에 올리는 **조회 전용** 화면입니다. Pico USB, 릴레이,
텔레그램 승인, 카메라 비밀번호, MQTT 명령 토픽은 포함하지 않습니다.

학교 서버는 `SMARTFARM_PUBLIC_SYNC_ENABLED=1`일 때 서명된 센서 요약을 60초마다
전송하며, 최근 카메라 사진이 바뀐 경우에만 최대 3장을 함께 전송합니다. Vercel Blob에는
공개용 센서 요약과 카메라 사진만 저장됩니다.

## 배포 전 준비

1. Vercel 계정에 로그인한 뒤 이 폴더에서 프로젝트를 연결합니다.

   ```powershell
   npx vercel login
   npx vercel link
   npx vercel blob create-store ffk-smartfarm-public
   ```

2. 같은 무작위 문자열을 Vercel 환경변수와 **학교 서버 노트북의 `.env`**에 각각 넣습니다.

   ```powershell
   npx vercel env add SMARTFARM_PUBLIC_SYNC_SECRET production
   ```

   `.env` 예시:

   ```text
   SMARTFARM_PUBLIC_SYNC_ENABLED=1
   SMARTFARM_PUBLIC_DASHBOARD_URL=https://프로젝트이름.vercel.app
   SMARTFARM_PUBLIC_SYNC_SECRET=Vercel에_넣은_동일한_긴_무작위_문자열
   SMARTFARM_PUBLIC_SYNC_INTERVAL_SECONDS=60
   ```

3. 배포합니다.

   ```powershell
   npx vercel --prod
   ```

배포 뒤 학교 서버를 재시작하면 첫 공개 데이터가 전송됩니다. Vercel 함수의
`/api/ingest`는 HMAC 서명이 맞는 학교 서버 요청만 받으며, 화면에는 제어 API가 없습니다.
