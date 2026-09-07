# 포켓몬 카드 시세판 — Render 라이브 웹앱

콜렉토리 공개 API를 실시간 조회(1시간 캐시)해 **어디서나 항상 최신** 한국/일본 시세를 보여주는 웹앱.
정적 Artifact(`pokemon_price_dashboard.html`)와 달리 클라우드에 상주해 폰·PC 어디서든 접속.

## 로컬 실행 (테스트)

```powershell
Set-Location "90_SYSTEM/automation/pokemon_dashboard_web"
pip install -r requirements.txt
python app.py

# → http://localhost:5000

```

## Render 배포 (무료)

1. **Render 로그인** → https://dashboard.render.com (GitHub 계정 연동)
2. **New +** → **Web Service** → 이 리포(`pokemon-price-dashboard`) 선택
3. 설정 (render.yaml이 자동 채움 — Blueprint로 하면 원클릭):
   - **Root Directory**: (리포 루트 — 비워두면 됨)
   - **Runtime**: Python
   - **Build**: `pip install -r requirements.txt`
   - **Start**: `gunicorn app:app --timeout 120 --workers 1`
   - **Plan**: Free
4. **Create Web Service** → 몇 분 뒤 `https://pokemon-price-dashboard.onrender.com` 발급
5. 그 주소를 폰 홈화면에 추가하면 앱처럼 씀.

> **Blueprint 방식(추천):** New + → **Blueprint** → 리포 선택 → `render.yaml` 자동 인식 → Apply. 위 설정 수동 입력 불필요.

## 특징

- **이미지 임베드 불필요**: 서버 렌더라 콜렉토리 CDN 이미지 URL 직접 사용(가벼움).
- **1시간 캐시**: 콜렉토리 API 부담 최소화(`CACHE_TTL`).
- **무료 플랜 주의**: 15분 무접속 시 슬립 → 첫 접속이 느릴 수 있음(웨이크업 ~30초). keepalive 핑 걸면 상시 유지.
- 감시 팩/상한은 `app.py`의 `PACKS`·`MIN_KR`·`TOPN`에서 수정.

## 정적 버전과의 관계

- **정적(Artifact)**: `pokemon_price_dashboard_gen.py`가 생성. 공유 링크·이미지 임베드. 갱신은 재생성+재발행.
- **라이브(이 앱)**: 항상 최신·어디서나. 이미지는 실시간 로드.
둘 다 같은 콜렉토리 소스·같은 디자인.

---

## 📡 감시기 (텔레그램 매물 알림) — `watcher/`

정가~조금 위 실구매가로 포켓몬 카드 박스가 뜨면 텔레그램 알림. 다나와 정식몰 집계(쿠팡 품절유령 필터 포함). 순수 파이썬, 크레딧 0.

**각 PC 세팅:**
```powershell
git clone https://github.com/DanielJ1025/pokemon-price-dashboard
cd pokemon-price-dashboard/watcher
# .env 생성 (git 제외 — PC마다 직접):
#   TELEGRAM_BOT_TOKEN=<봇토큰>
#   TELEGRAM_CHAT_ID=<chat id>
python pokemon_deal_watch.py --dry-run   # 미리보기
powershell -ExecutionPolicy Bypass -File setup_pokemon_watch.ps1   # 상시 스케줄러 등록(3분)
```
- 상한/팩은 `pokemon_deal_watch.py`의 `WATCHES`에서 수정.
- 대시보드 정적 HTML 재생성: `python pokemon_price_dashboard_gen.py`
- 일본 여행 가이드: `watcher/일본_쇼핑가이드.md`
