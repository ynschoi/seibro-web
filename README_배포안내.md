# SEIBRO 조회 웹앱 — 배포 안내

SPC명·평가단위·기간을 입력하면 SEIBRO에서 조회해 화면에 표로 보여주는 웹앱입니다.
여러 사람이 링크 하나로 접속할 수 있고, 모든 조회 기록이 로그에 남아 관리자가 볼 수 있습니다.

## 구성 파일
- `app.py` — 웹 서버 (Flask)
- `seibro_client.py` — SEIBRO 조회 로직
- `templates/index.html` — 조회 화면
- `templates/admin.html` — 관리자 로그 화면
- `requirements.txt`, `Procfile`, `render.yaml` — 배포용 설정

---

## 1단계: 로컬에서 먼저 실행 (테스트)

```
cd webapp
pip install -r requirements.txt
python app.py
```
→ 브라우저에서 http://127.0.0.1:5000 접속
→ 관리자 로그: http://127.0.0.1:5000/admin?pw=admin

---

## 2단계: 클라우드 무료 배포 (Render.com — 추천)

> ⚠️ **가장 중요**: 클라우드 서버 IP를 SEIBRO가 차단할 수 있습니다.
> 배포 후 조회가 되는지 **가장 먼저 확인**하세요. 안 되면 대안 논의 필요.

### 준비물
- GitHub 계정 (무료)
- Render.com 계정 (무료, GitHub으로 가입 가능)

### 절차
1. **GitHub에 `webapp` 폴더를 올린다** (새 저장소 생성 후 업로드)
2. **Render.com** 접속 → New → **Web Service**
3. 방금 만든 GitHub 저장소 연결
4. 설정 (render.yaml이 자동 인식되지만, 수동이면):
   - Runtime: **Python**
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app --timeout 120 --workers 1`
   - Plan: **Free**
5. **Environment** 탭에서 관리자 비밀번호 설정:
   - `SEIBRO_ADMIN_PW` = (원하는 비밀번호)
6. Deploy 클릭 → 몇 분 후 `https://xxxx.onrender.com` 주소 생성
7. **그 주소로 접속해 SPC명 조회 테스트** ← 여기서 되는지 확인!

### 접속
- 사용자: `https://xxxx.onrender.com`
- 관리자 로그: `https://xxxx.onrender.com/admin?pw=설정한비밀번호`

---

## 무료 티어 주의사항
- **콜드 스타트**: 15분간 아무도 안 쓰면 서버가 잠듦 → 다음 접속 시 첫 로딩 30초 정도. 조회 자체는 정상.
- **로그 영속성**: 무료 플랜은 재배포/재시작 시 `usage_log.db`가 초기화될 수 있음.
  로그를 영구 보관하려면 유료 디스크 또는 외부 DB(무료 Postgres 등) 연결 필요 — 필요 시 추가 작업.

## 만약 SEIBRO가 클라우드 IP를 차단하면
- 증상: 조회 시 "회사를 찾을 수 없습니다" 또는 계속 오류/빈 결과
- 대안: ① 다른 클라우드 지역/업체 시도, ② 프록시 경유, ③ 회원님 PC를 서버로 사용
  → 이 경우 별도 논의
