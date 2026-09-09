# 포켓몬 카드 대시보드 — 작업 핸드오프 (260909 밤)

> 내일 어느 PC에서든 이어가기 위한 인수인계. **배포·GitHub·작업트리 전부 `8b0d9e3` 안정본으로 통일됨.**

## 현재 상태 (안정)
- **리포:** github.com/DanielJ1025/pokemon-price-dashboard (`master`, origin 동기화됨)
- **정적 생성기:** `watcher/pokemon_price_dashboard_gen.py` → `pokemon_price_dashboard.html` → **Artifact** `https://claude.ai/code/artifact/5b5c3fef-8216-4b12-99b1-b354d821e0a2`
- **라이브 웹앱:** `app.py`(Flask) → **Render** (콜렉토리 실시간 1h 캐시)
- ⚠️ **gen.py와 app.py는 로직 파리티 유지 필수** (같은 `_TABS_JS`/`_TABS_CSS`/`_tr`/`table_html`). 한쪽 바꾸면 반드시 다른쪽도.
- 재생성: `cd watcher && python pokemon_price_dashboard_gen.py` (`.imgcache` 디스크캐시로 ~37초). 검증: 스크립트 추출 후 `node --check`.

## 오늘까지 반영된 기능
좌측 세로 사이드바(검색·필터칩·저장/불러오기 바) · 팩별 등급그룹 접이식(MUR·UR·SAR 병합·최고등급 펼침·칩 고정폭 정렬) · 전체 카드(홀로·커먼까지) · 이름앞 [등급]태그 · 카드 검색 · 썸네일 라이트박스 · 정규세트 [NNN] · 수량 스텝퍼 · 필터(보유/미보유/여분2+/★위시) · 세트 완성도 진행바 · 위시리스트 · **내 보유카드 탭**(도감/목록 뷰 · 팩별/전체 그룹 · 금액·등급·이름·일본가 엑셀식 정렬+오름/내림 · 종/장 구분 · **📈 가치 추이 스파크라인** · 백업 코드) · 팩 태그(교차뷰) · eBay 미국 판매완료 링크 · 표 금액 우측정렬(₩) · 풀폭 반응형.

## ✅ 완료(260910): 📊 등급별 · 📦 팩별 보유 현황
보유 탭에 가치비중 막대 분석 블록 구현·배포 완료(`breakdown()`, 양쪽 파리티). 아래는 참고 코드 보존.

### 1) `renderOwned` 바로 앞에 `breakdown()` 함수 추가
```js
function breakdown(){
 const RK={MUR:0,HR:0,UR:1,SAR:2,SR:3,AR:4,RR:5,R:6,ACE:7,U:8,C:9},TOP={MUR:1,HR:1,UR:1,SAR:1};
 const gr={};let tv=0;
 document.querySelectorAll('.qty').forEach(el=>{const q=DB.qty[el.dataset.id]||0;if(q<=0)return;const tr=el.closest('tr');const t=tr.querySelector('.rtag');let r=t?t.textContent.replace(/[\[\]]/g,'').trim():'-';const key=TOP[r]?'MUR·UR·SAR':r;const kr=+el.dataset.kr||0;const g=gr[key]||(gr[key]={u:0,c:0,v:0,o:(key==='MUR·UR·SAR'?-1:(RK[r]==null?10:RK[r]))});g.u++;g.c+=q;g.v+=q*kr;tv+=q*kr;});
 const rkeys=Object.keys(gr);if(!rkeys.length)return '';
 const rrows=rkeys.sort((a,b)=>gr[a].o-gr[b].o).map(k=>{const g=gr[k],p=tv?Math.round(g.v/tv*100):0;return '<div class="bd-row"><span class="bd-lbl">'+k+'</span><span class="bd-bar"><i style="width:'+p+'%"></i></span><span class="bd-v">'+g.u+'종 '+g.c+'장 · '+won(g.v)+'</span></div>';}).join('');
 let pv=0;const pr=[];packs.forEach(sec=>{const st=packStat(sec);if(!st.cards)return;pv+=st.val;pr.push({n:(sec.querySelector('h2')||{textContent:''}).textContent.trim(),st:st});});
 const prows=pr.sort((a,b)=>b.st.val-a.st.val).map(x=>{const p=pv?Math.round(x.st.val/pv*100):0;return '<div class="bd-row"><span class="bd-lbl">'+x.n+'</span><span class="bd-bar"><i style="width:'+p+'%"></i></span><span class="bd-v">'+x.st.uniq+'종 '+x.st.cards+'장 · '+won(x.st.val)+'</span></div>';}).join('');
 return '<div class="bdwrap"><div class="bd-col"><div class="bd-h">📊 등급별 보유</div>'+rrows+'</div><div class="bd-col"><div class="bd-h">📦 팩별 보유</div>'+prows+'</div></div>';
}
```
(파이썬 f-string이 아니라 JS 문자열이므로 gen.py 삽입 시 `\\[\\]` 이스케이프 주의)

### 2) `renderOwned` head에서 `sparkline()` 다음에 `+breakdown()` 호출

### 3) CSS 추가 (gen.py `_CSS`, app.py `_CSS`)
```css
.bdwrap{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:4px 0 16px}
.bd-col{background:var(--surface-2);border:1px solid var(--border);border-radius:11px;padding:12px 14px}
.bd-h{font-size:12.5px;font-weight:800;color:var(--muted);margin-bottom:8px}
.bd-row{display:flex;align-items:center;gap:8px;font-size:12px;margin:4px 0}
.bd-lbl{flex:0 0 96px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bd-bar{flex:1;height:8px;background:var(--surface);border:1px solid var(--border);border-radius:4px;overflow:hidden;min-width:40px}
.bd-bar i{display:block;height:100%;background:var(--sar)}
.bd-v{flex:0 0 auto;color:var(--faint);font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap}
@media(max-width:700px){.bdwrap{grid-template-columns:1fr}}
```

## ⏳ 대기 중 결정 (사용자 선택 필요)
1. **열 폭/위치 조정** — 넣을지, 폭만/순서까지
2. **US eBay 숫자** — 밸류카드만 무료 API키(JustTCG 등, 하루 100건)로 숫자 vs 지금처럼 링크 유지. (eBay 판매완료가 직접조회는 파트너 전용이라 불가)
3. **구글드라이브 자동 동기화** — Render+OAuth(클라이언트 ID 발급 필요, Render 전용) vs 지금처럼 백업파일을 드라이브 동기화 폴더에 저장(무개발·즉시)

## 확정된 사실 (헤매지 말 것)
- **콜렉토리는 kr/jp/cn 전부 KRW(원화)로 줌** (`currency` 필드 확인). 일본 열은 "일본 시장가 원화환산" → **원화 유지가 맞음**(엔화 변환 안 함). US 시세는 콜렉토리에 없음.
- **보유 데이터 = localStorage `pkm_db{qty,wish,hist}`**. origin별·브라우저별 분리(Artifact ≠ Render). 이전은 백업 파일/코드로만.
- Artifact CSP = 외부호출 불가 → 클라우드/US-API/구글드라이브 자동동기화는 **Render에서만** 가능.
- 이미지: gen=임베드(120px/q50, 파일 ~7MB), app=CDN URL. 라이트박스 `img.tth,img.ath`.
