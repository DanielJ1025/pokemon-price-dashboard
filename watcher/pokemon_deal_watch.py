#!/usr/bin/env python
"""포켓몬 카드 스마트스토어 매물 감시 → 가격 상한 이하 신규 매물을 텔레그램으로 즉시 알림.

github_trending_watch.py 와 동일한 뼈대:
- **순수 python 감지기**: 네이버 검색 OpenAPI(shop)로 최신 매물을 조회 →
  가격 상한 이하 + 이전에 못 본 것만 골라 텔레그램 푸시 + state 에 기록.
  claude CLI / Anthropic API 호출 없음 → 스케줄러/훅에서 불려도 안전.
- 자격증명은 .env 에서 읽는다(하드코딩 금지). 없으면 조용히 skip, exit 0.

감시 소스 3종 (키 있는 것만 자동으로 켜짐):
    - 네이버쇼핑: 지마켓·옥션·11번가·스마트스토어 등 정식몰 통합 (NAVER_CLIENT_ID/SECRET)
    - 번개장터: 중고 개인거래 (무인증 — 항상 켜짐)
    - 쿠팡: 쿠팡 파트너스 API (COUPANG_ACCESS_KEY/SECRET_KEY, 로켓배송 재고는 제한적)
가격추적: 각 매물 가격을 state 에 기록 → 이전보다 내려오면 '📉 가격 하락' 알림.

필요한 .env 값:
    NAVER_CLIENT_ID=...          # https://developers.naver.com 앱 등록(검색 API)
    NAVER_CLIENT_SECRET=...
    COUPANG_ACCESS_KEY=...       # (선택) https://partners.coupang.com 가입 후 발급
    COUPANG_SECRET_KEY=...
    TELEGRAM_BOT_TOKEN=...       # @BotFather 로 봇 생성
    TELEGRAM_CHAT_ID=...         # 봇에게 아무 메시지 보낸 뒤 getUpdates 로 확인(스크립트가 안내)

사용법:
    python pokemon_deal_watch.py --backfill   # 첫 도입: 현재 매물을 알림 없이 seen 등록(홍수 방지)
    python pokemon_deal_watch.py              # 감지·알림 (스케줄러로 N분마다)
    python pokemon_deal_watch.py --chat-id    # 내 채팅 ID 찾기(봇에게 먼저 말 걸고 실행)
    python pokemon_deal_watch.py --dry-run    # 텔레그램 안 보내고 콘솔로만 미리보기

절대 세션/스케줄러를 깨지 않는다: 키 없음·네트워크 오류 → 조용히 skip, exit 0.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
STATE = Path(__file__).resolve().parent / "pokemon_deal_watch_state.json"

# ── 감시 설정 (여기만 고치면 됨) ─────────────────────────────
# 세트별 감시: keyword(다나와 검색어) + max_price.
# ★ max_price = "배송비 포함 실구매가" 상한. 다나와 상품가에 배송비를 더한 값이 이 이하일 때만 알림.
#   (정가 + 약간 여유. 예: 정가 45,000 → 50,000 = 배송비·소폭 프리미엄까지 허용)
# 고점 팩 위주로 감시(개봉해서 대박카드 노림). 새 세트 나오면 여기 추가.
# list_price=한국판 공식 정가(알림에 '정가 대비' 표기용) / max_price=배송비포함 실구매가 상한
# hits=그 팩의 고점(치는)카드 + 대략 시세(한국판, 변동 큼 — 알림 참고용). 정가는 대략치라 편집 가능.
WATCHES = [
    {"keyword": "포켓몬 스톰에메랄다", "list_price": 45000, "max_price": 50000,
     "hits": "메가레쿠쟈 MUR ~70만 · 가이오가 AR · 이상해씨 AR"},
    {"keyword": "포켓몬 어비스아이",   "list_price": 45000, "max_price": 50000,
     "hits": "메가다크라이 ex MUR ~15만·SAR ~10만 · 무쿠 SAR ~3만"},
    {"keyword": "포켓몬 카드 151",     "list_price": 50000, "max_price": 55000,
     "hits": "리자몽 ex SAR ~11만 · 이상해꽃·거북왕 SAR 각 ~5만 · 뮤 ex SAR ~4.8만"},
    {"keyword": "포켓몬 초전브레이커", "list_price": 45000, "max_price": 45000,
     "hits": "피카츄 ex SAR ~10만 · 자포코일 AR"},
    {"keyword": "포켓몬 블랙볼트",     "list_price": 40000, "max_price": 45000,
     "hits": "제크로무 BWR ~12만+"},
    {"keyword": "포켓몬 화이트플레어", "list_price": 40000, "max_price": 52000,
     "hits": "레시라무 ex ~9.5만 · 제크로무 (인기라 정가로 잘 안 풀림·상한↑)"},
    {"keyword": "포켓몬 니힐제로",     "list_price": 45000, "max_price": 50000,
     "hits": "메가지가르데 ex MUR ~12만+ · 명희의 격려 SAR ~7만"},
    {"keyword": "포켓몬 낙원드래고나", "list_price": 45000, "max_price": 50000,
     "hits": "라티아스 ex SAR ~6.5~7만 · 루티아의 어필 SAR · 라티오스 AR (천장 낮음·인기 낮은 편)"},
]
PER_QUERY = 40                # 키워드당 최신 매물 상위 N (최대 100)
SORT = "date"                 # date=최신등록순(신규매물 감지에 적합), sim=정확도, asc=저가순
# 알림 하한 = 정가 × 이 비율. 이보다 싸면 미끼·부분품·싱글로 보고 컷(진짜 밀봉박스 아님).
# 0.55 = 정가 45,000 → 24,750원 미만 컷. 너무 조이면 진짜 급처를 놓치니 조절.
MIN_PRICE_RATIO = 0.55
# 가용성 리마인드(시간): 정가 이하 매물이 계속 존재하면, 신규·하락이 아니어도 이 주기마다 1회 재알림.
# 이 툴은 '변화 알림'이라 설치 때 이미 좋았던 안정 매물을 영영 못 받는 맹점이 있어, 그걸 메운다.
# 24 = 하루 1회 리마인드. 늘리면 조용, 줄이면 자주 상기.
REMIND_HOURS = 24
# 제목에 이 중 하나라도 있어야 알림(박스 단위만). 비우면 조건 해제.
REQUIRE_WORDS = ["박스", "확장팩", "30팩"]
# 제목에 이게 있으면 제외(액세서리 + 박스 아닌 낱개/분철/싱글 + 예약/부분 컷).
EXCLUDE_WORDS = [
    "슬리브", "덱박스", "보호", "케이스", "파일", "바인더", "플레이매트",  # 액세서리
    "낱개", "낱팩", "단품", "분철", "1팩", "한팩", "낱장", "싱글", "포장",  # 박스 아닌 단위
    "예약", "예판", "파츠", "부분", "분리",                                 # 예약판매·부분품
    "매입", "삽니다", "사요", "구매", "구합니다", "구함", "구해요",           # 삽니다(구매글) — 번개장터 매입글 컷
]
# ─────────────────────────────────────────────────────────

NAVER_SHOP_URL = "https://openapi.naver.com/v1/search/shop.json"


def log(msg: str) -> None:
    print(f"[pkm-deal] {msg}")


def load_env() -> None:
    """dotenv 없이 .env 수동 파싱 (워크스페이스 관례)."""
    for name in (".env", ".env.local"):
        p = ROOT / name
        if not p.is_file():
            continue
        try:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except OSError:
            pass


def load_state() -> dict:
    if STATE.is_file():
        try:
            data = json.loads(STATE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (ValueError, OSError):
            pass
    return {"prices": {}}


def save_state(state: dict) -> None:
    try:
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        log(f"상태 저장 실패(무시): {e}")


def strip_tags(s: str) -> str:
    """네이버 검색결과 title 의 <b> 태그 제거."""
    return (s.replace("<b>", "").replace("</b>", "")
             .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').strip())


def search_naver_shop(keyword: str, cid: str, secret: str) -> list[dict]:
    params = {"query": keyword, "display": PER_QUERY, "sort": SORT}
    url = f"{NAVER_SHOP_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "X-Naver-Client-Id": cid,
        "X-Naver-Client-Secret": secret,
        "User-Agent": "pokemon-deal-watch",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        log(f"네이버 API 실패({keyword!r}): {e}")
        return []
    out = []
    for it in data.get("items", []):
        try:
            price = int(it.get("lprice") or 0)
        except ValueError:
            price = 0
        out.append({
            "id": it.get("productId", ""),
            "title": strip_tags(it.get("title", "")),
            "price": price,
            "link": it.get("link", ""),
            "mall": it.get("mallName", ""),
        })
    return out


def search_bunjang(keyword: str, *_ignored) -> list[dict]:
    """번개장터 중고 매물 (공개 JSON, 인증 불필요). 최신순."""
    params = {"q": keyword, "order": "date", "page": 0, "n": PER_QUERY, "stat_device": "w"}
    url = f"https://api.bunjang.co.kr/api/1/find_v2.json?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "pokemon-deal-watch"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        log(f"번개장터 API 실패({keyword!r}): {e}")
        return []
    out = []
    for it in data.get("list", []):
        try:
            price = int(str(it.get("price") or "0").replace(",", ""))
        except ValueError:
            price = 0
        pid = str(it.get("pid") or "")
        out.append({
            "id": pid,
            "title": strip_tags(it.get("name", "")),
            "price": price,
            "link": f"https://m.bunjang.co.kr/products/{pid}",
            "mall": "번개장터",
        })
    return out


_DANAWA_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


def search_danawa(keyword: str, *_ignored) -> list[dict]:
    """다나와 통합검색 → 정식몰 최저가 집계(쿠팡·11번가·지마켓 등 포함). 무인증.

    다나와는 '등록된 상품'의 최저가를 보여주므로, 신규 매물보다 **가격 하락 추적**에
    적합하다(정가 이하로 최저가가 떨어지면 알림). 각 상품의 min_price 히든필드를 파싱.
    """
    url = f"https://search.danawa.com/dsearch.php?query={urllib.parse.quote(keyword)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": _DANAWA_UA, "Accept-Language": "ko-KR,ko;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            html = raw.decode("utf-8", "replace")
    except Exception as e:
        log(f"다나와 실패({keyword!r}): {e}")
        return []
    # pcode → 최저가 (숨은 input), pcode → 상품명(+링크)
    prices = dict(re.findall(r'id="min_price_(\d+)"\s*value="(\d+)"', html))
    out = []
    seen = set()
    for m in re.finditer(
            r'class="prod_name">\s*<a[^>]*href="[^"]*pcode=(\d+)[^"]*"[^>]*>(.*?)</a>',
            html, re.S):
        pcode = m.group(1)
        if pcode in seen:
            continue
        seen.add(pcode)
        title = strip_tags(re.sub(r"<[^>]+>", "", m.group(2)))
        try:
            price = int(prices.get(pcode, 0))
        except ValueError:
            price = 0
        out.append({
            "id": pcode,
            "title": title,
            "price": price,
            "link": f"https://prod.danawa.com/info/?pcode={pcode}",
            "mall": "다나와최저가",
        })
    return out


# 다나와 검색결과의 min_price 는 '상품가'라 배송비가 빠져있다(정가 45,000 상품 43,870+배송3,000
# =46,870 을 놓치는 오차). 판매처 비교 목록 AJAX에서 최저가(prc_c) 옆 배송비를 읽어 실구매가를 만든다.
_DANAWA_MALL_URL = "https://prod.danawa.com/info/ajax/getAllPriceCompareMallList.ajax.php"
_DEFAULT_SHIP = 3000   # 배송비 파싱 실패 시 보수적으로 가정(정가 근처 오탐 방지)
_GHOST_MALL = "쿠팡"   # 다나와는 재고표식 없음 + 쿠팡 최저가 품절유령 잦음 → 시세보다 크게 싼 쿠팡은 컷


def _ship_won(txt: str) -> int:
    """'배송비 3,000원' → 3000, '무료배송' → 0."""
    nums = re.findall(r"[\d,]+", txt)
    return int(nums[0].replace(",", "")) if nums else 0


def danawa_real_price(pcode: str):
    """다나와 판매처목록에서 '실제 구매가능한' (상품가, 배송비, 판매처수)를 추정해 반환.

    다나와 검색 min_price 는 품절 판매처의 유령가일 때가 있다(화이트플레어: 쿠팡 39,500이
    품절인데 가격만 남아 '재고안정'으로 오알림). 재고표식이 없으므로 두 단계로 유령을 거른다:
    ①쿠팡 유령 컷 — 비쿠팡 실매장 최저가 대비 8%+ 싼 쿠팡은 제외(주 유령원).
    ②전부 쿠팡뿐이면 하위 25%의 8%+ 가격점프 위를 실구매 경계로.
    판매처수 = 유령 제외 판매처 개수(많을수록 재고 안정). 실패 시 (None, _DEFAULT_SHIP, 0).
    """
    data = urllib.parse.urlencode({"pcode": pcode}).encode("utf-8")
    req = urllib.request.Request(_DANAWA_MALL_URL, data=data, headers={
        "User-Agent": _DANAWA_UA,
        "Referer": f"https://prod.danawa.com/info/?pcode={pcode}",
        "X-Requested-With": "XMLHttpRequest",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            html = raw.decode("utf-8", "replace")
    except Exception as e:
        log(f"다나와 판매처 조회 실패({pcode}): {e}")
        return None, _DEFAULT_SHIP, 0
    # 판매처별 (상품가, 배송비, 판매처명) — 각 prc_c 앞의 가장 가까운 로고 alt 를 판매처명으로.
    # (카드전용가 prc_t 는 일반 구매가 아니라 제외)
    sellers = []
    for m in re.finditer(r'<em class="prc_c">([\d,]+)</em>', html):
        price = int(m.group(1).replace(",", ""))
        alt = re.findall(r'alt="([^"]*)"', html[:m.start()])
        mall = alt[-1] if alt else ""
        sh = re.search(r'<span class="ship">\(([^)]*)\)', html[m.end():m.end() + 400])
        ship = _ship_won(sh.group(1)) if sh else _DEFAULT_SHIP
        sellers.append((price, ship, mall))
    if not sellers:
        return None, _DEFAULT_SHIP, 0
    sellers.sort()
    # ★쿠팡 품절유령 컷: 다나와 판매처목록엔 재고표식이 없고, 쿠팡 최저가는 품절인데도
    #   가격만 남아있는 경우가 잦다(화이트플레어: 쿠팡 39,500 품절인데 '재고안정'으로 오알림).
    #   비쿠팡 실매장 최저가 대비 8%+ 싼 쿠팡은 유령으로 보고 제외 → 진짜 구매가능 최저가만 남긴다.
    #   (쿠팡이 실매장 시세권이면 정상 판매로 유지 → 니힐·어비스 실매물은 안 잘림.)
    nc = [p for p, _, mall in sellers if _GHOST_MALL not in mall]
    if nc:
        floor = min(nc) * 0.92
        real = [(p, s, mall) for p, s, mall in sellers
                if not (_GHOST_MALL in mall and p < floor)]
        real.sort()
        item_price, ship, _mall = real[0]
        return item_price, ship, len(real)   # (상품가, 배송비, 유령제외 판매처수)
    # 전부 쿠팡뿐 → 하위 25% 안에서 8%+ 점프 위를 실구매 경계로(고립 초저가 유령 컷)
    prices = [p for p, _, _ in sellers]
    n = len(prices)
    real_idx = 0
    if n >= 4:
        limit = min(max(2, int(n * 0.25)), n - 1)
        for i in range(1, limit + 1):
            if prices[i] > prices[i - 1] * 1.08:
                real_idx = i
    item_price, ship, _mall = sellers[real_idx]
    return item_price, ship, n - real_idx


def _xml_tag(block: str, tag: str) -> str:
    """XML 블록에서 태그값 추출(CDATA 제거)."""
    m = re.search(rf"<{tag}>(.*?)</{tag}>", block, re.S)
    if not m:
        return ""
    v = m.group(1)
    v = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", v, flags=re.S)
    return v.strip()


def search_11st(keyword: str, apikey: str) -> list[dict]:
    """11번가 오픈API 상품검색 → 실제 판매중 상품(재고 정확). 키 필요(OPEN_API_11ST_KEY).

    발급: https://openapi.11st.co.kr → 회원가입 → 인증키 발급(무료·180일).
    XML 응답. 검색결과는 실판매 상품이라 다나와 품절유령 문제에서 자유롭다.
    """
    params = {"key": apikey, "apiCode": "ProductSearch",
              "keyword": keyword, "pageSize": PER_QUERY, "sortCd": "L"}  # L=낮은가격순
    url = "http://openapi.11st.co.kr/openapi/OpenApiService.tmall?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "pokemon-deal-watch"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
    except Exception as e:
        log(f"11번가 API 실패({keyword!r}): {e}")
        return []
    # 11번가 응답은 EUC-KR 또는 UTF-8 — utf-8 우선, 깨지면 euc-kr 폴백
    try:
        xml = raw.decode("utf-8")
        if "�" in xml:
            raise ValueError
    except (UnicodeDecodeError, ValueError):
        xml = raw.decode("euc-kr", "replace")
    out = []
    for block in re.findall(r"<Product>(.*?)</Product>", xml, re.S):
        name = strip_tags(_xml_tag(block, "ProductName"))
        price_txt = _xml_tag(block, "ProductPrice") or _xml_tag(block, "SalePrice")
        nums = re.findall(r"\d[\d,]*", price_txt)
        price = int(nums[0].replace(",", "")) if nums else 0
        out.append({
            "id": _xml_tag(block, "ProductCode"),
            "title": name,
            "price": price,
            "link": _xml_tag(block, "DetailPageUrl"),
            "mall": "11번가",
        })
    return out


def _coupang_auth(method: str, path_with_query: str, access: str, secret: str) -> str:
    """쿠팡 파트너스 HMAC 서명 헤더 생성."""
    signed_date = time.strftime("%y%m%dT%H%M%SZ", time.gmtime())
    path, _, query = path_with_query.partition("?")
    message = signed_date + method + path + query
    sig = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return (f"CEA algorithm=HmacSHA256, access-key={access}, "
            f"signed-date={signed_date}, signature={sig}")


def search_coupang(keyword: str, access: str, secret: str) -> list[dict]:
    """쿠팡 파트너스 상품 검색 API (COUPANG_ACCESS_KEY/SECRET_KEY 필요).
    ⚠️ 로켓배송 직매입 재고는 검색이 제한적일 수 있음."""
    q = urllib.parse.urlencode({"keyword": keyword, "limit": PER_QUERY})
    path = f"/v2/providers/affiliate_open_api/apis/openapi/v1/products/search?{q}"
    url = f"https://api-gateway.coupang.com{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": _coupang_auth("GET", path, access, secret),
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "pokemon-deal-watch",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        log(f"쿠팡 API 실패({keyword!r}): {e}")
        return []
    out = []
    for it in (data.get("data", {}) or {}).get("productData", []) or []:
        try:
            price = int(it.get("productPrice") or 0)
        except (ValueError, TypeError):
            price = 0
        out.append({
            "id": str(it.get("productId") or ""),
            "title": strip_tags(it.get("productName", "")),
            "price": price,
            "link": it.get("productUrl", ""),
            "mall": "쿠팡",
        })
    return out


def is_excluded(title: str) -> bool:
    if any(w in title for w in EXCLUDE_WORDS):
        return True
    if REQUIRE_WORDS and not any(w in title for w in REQUIRE_WORDS):
        return True  # 박스 단위 아님
    return False


def tg_api(method: str, token: str, params: dict) -> dict | None:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode("utf-8")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        log(f"텔레그램 {method} 실패: {e}")
        return None


def send_telegram(token: str, chat_id: str, text: str) -> bool:
    res = tg_api("sendMessage", token, {
        "chat_id": chat_id, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": "false",
    })
    return bool(res and res.get("ok"))


def find_chat_id(token: str) -> int:
    """봇에게 먼저 아무 메시지나 보낸 뒤 실행하면 chat_id 를 뽑아준다."""
    res = tg_api_get("getUpdates", token)
    if not res or not res.get("ok"):
        log("getUpdates 실패 — 봇 토큰 확인.")
        return 1
    ids = []
    for u in res.get("result", []):
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            ids.append((chat["id"], chat.get("title") or chat.get("username") or chat.get("first_name", "")))
    if not ids:
        log("업데이트 없음 — 텔레그램에서 봇에게 아무 메시지나 먼저 보낸 뒤 다시 실행하세요.")
        return 1
    log("찾은 chat_id (이걸 .env 의 TELEGRAM_CHAT_ID 에 넣으세요):")
    for cid, name in dict(ids).items():
        log(f"  {cid}  ({name})")
    return 0


def tg_api_get(method: str, token: str) -> dict | None:
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        log(f"텔레그램 {method} 실패: {e}")
        return None


def format_alert(deal: dict) -> str:
    drop = deal.get("drop", 0)
    if deal.get("new_low"):
        head = "🔥 <b>역대 최저가!</b>"
    elif drop:
        head = "📉 <b>가격 하락!</b>"
    elif deal.get("remind"):
        head = "🟢 <b>정가 이하 매물 있음</b>"
    else:
        head = "🎴 <b>포켓몬 카드 정가 매물</b>"
    dropline = f"  (▼{drop:,}원 하락)" if drop else ""
    # 다나와는 실구매가(배송포함) + 내역(상품가+배송비)을 함께 표기
    if "item_price" in deal:
        ship = deal.get("ship", 0)
        ship_txt = f"배송 {ship:,}" if ship else "무료배송"
        price_line = (f"💰 <b>{deal['price']:,}원</b>{dropline}  "
                      f"(상품 {deal['item_price']:,} + {ship_txt})  ·  🏬 {deal['mall']}")
    else:
        price_line = f"💰 {deal['price']:,}원{dropline}  ·  🏬 {deal['mall']}"
    lines = [head, f"<b>{deal['title']}</b>", price_line]
    # 정가 대비(실구매가 vs 한국판 정가)
    lp = deal.get("list_price")
    if lp:
        gap = deal["price"] - lp
        if gap > 0:
            vs = f"🏷 정가 {lp:,} 대비 <b>+{gap:,}원</b>"
        elif gap < 0:
            vs = f"🏷 정가 {lp:,} 대비 <b>-{abs(gap):,}원 (정가 이하!)</b>"
        else:
            vs = f"🏷 <b>정가 {lp:,} 딱</b>"
        lines.append(vs)
    # 판매처 수(재고 신뢰도) — 유령 제외 실판매처. 많을수록 재고 안정.
    malls = deal.get("malls")
    if malls:
        stock = "재고 안정" if malls >= 10 else ("재고 보통" if malls >= 4 else "⚠️재고 적음")
        lines.append(f"🏪 판매처 {malls}곳 ({stock})")
    # 고점(치는) 카드 + 시세 — 열어볼 가치 판단용
    if deal.get("hits"):
        lines.append(f"🎯 고점: {deal['hits']}")
    lines.append(deal["link"])
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="포켓몬 카드 스마트스토어 매물 감시")
    ap.add_argument("--backfill", action="store_true", help="첫 도입: 현재 매물을 알림 없이 seen 등록")
    ap.add_argument("--chat-id", action="store_true", help="내 텔레그램 chat_id 찾기")
    ap.add_argument("--dry-run", action="store_true", help="텔레그램 안 보내고 콘솔 미리보기")
    ap.add_argument("--max-new", type=int, default=15, help="한 실행 알림 상한(홍수 가드)")
    args = ap.parse_args()

    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")

    if args.chat_id:
        if not token:
            log("TELEGRAM_BOT_TOKEN 미설정.")
            return 0
        return find_chat_id(token)

    cid = os.environ.get("NAVER_CLIENT_ID", "")
    secret = os.environ.get("NAVER_CLIENT_SECRET", "")
    ck = os.environ.get("COUPANG_ACCESS_KEY", "")
    cs = os.environ.get("COUPANG_SECRET_KEY", "")
    key11 = os.environ.get("OPEN_API_11ST_KEY", "")

    # 소스 구성 — 정식몰만(중고 제외). 다나와는 무인증 정식몰 최저가 집계라 항상 켜짐.
    # 11번가 오픈API는 실판매 상품 직접 조회(재고 정확) — 키 있으면 켜짐.
    # 네이버 검색 OpenAPI 는 신규 앱 등록이 막혀 사실상 사용 불가(키 있으면만 시도).
    # 쿠팡 최저가는 다나와가 이미 포함하므로 파트너스 키는 선택.
    sources: list = []
    sources.append(("danawa", search_danawa))
    if key11:
        sources.append(("11st", lambda kw: search_11st(kw, key11)))
    if cid and secret:
        sources.append(("naver", lambda kw: search_naver_shop(kw, cid, secret)))
    if ck and cs:
        sources.append(("coupang", lambda kw: search_coupang(kw, ck, cs)))
    log("소스: " + ", ".join(s[0] for s in sources))

    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    state = load_state()
    prices: dict = state.get("prices", {})

    # 각 소스×키워드 조회 → 정가 이하 + 박스단위만 수집(소스별 id 프리픽스로 충돌 방지)
    found: dict[str, dict] = {}
    for w in WATCHES:
        kw, cap = w["keyword"], w["max_price"]
        for sname, fn in sources:
            for it in fn(kw):
                if not it["id"]:
                    continue
                key = f"{sname}:{it['id']}"
                if key in found:
                    continue
                # it["price"] = 상품가. 배송비는 더하기만 하므로, 상품가가 이미 상한 초과면 컷.
                if it["price"] <= 0 or it["price"] > cap:
                    continue
                if it["price"] < cap * MIN_PRICE_RATIO:
                    continue  # 정가 대비 과도하게 싼 건 미끼·부분품·싱글
                if is_excluded(it["title"]):
                    continue
                # 다나와는 '실제 구매가능한' 최저 상품가(품절유령 제거) + 배송비로 재판정.
                if sname == "danawa":
                    item_price, ship, mall_cnt = danawa_real_price(it["id"])
                    if item_price is None:
                        item_price = it["price"]      # 폴백: 검색 최저가
                    it["item_price"] = item_price     # 상품가(알림 표기용)
                    it["ship"] = ship
                    it["malls"] = mall_cnt            # 판매처수(재고 신뢰도)
                    it["price"] = item_price + ship   # price = 실구매가(배송포함)
                    if it["price"] > cap:
                        continue
                # 알림에 '정가 대비' + '고점 카드 시세'를 붙이기 위해 감시세트 정보 첨부
                it["list_price"] = w.get("list_price")
                it["hits"] = w.get("hits", "")
                found[key] = it

    lows: dict = state.get("lows", {})   # key → 역대 최저 실구매가(신저가 배지용)

    if args.backfill:
        for key, d in found.items():
            prices[key] = d["price"]
            lows[key] = min(lows.get(key, d["price"]), d["price"])
        state["prices"] = prices
        state["lows"] = lows
        save_state(state)
        log(f"backfill 완료 — 현재 매물 {len(found)}건 가격 등록(알림 안 감).")
        return 0

    # 알림 대상: ①처음 보는 정가이하 매물  ②가격이 이전보다 내려온 매물
    #           ③계속 정가 이하로 존재하는 매물(REMIND_HOURS마다 1회 가용성 리마인드)
    alerted: dict = state.get("alerted", {})   # key → 마지막 알림 epoch(리마인드 주기 계산용)
    now = time.time()
    remind_sec = REMIND_HOURS * 3600
    alerts: list[dict] = []
    for key, d in found.items():
        prev = prices.get(key)
        low = lows.get(key)
        d["new_low"] = low is not None and d["price"] < low   # 역대최저 갱신
        lows[key] = d["price"] if low is None else min(low, d["price"])
        last_alert = alerted.get(key, 0)
        if prev is None:
            d["drop"] = 0          # 신규 매물
        elif d["price"] < prev:
            d["drop"] = prev - d["price"]  # 가격 하락
        elif now - last_alert >= remind_sec:
            d["drop"] = 0                   # 계속 정가 이하로 존재 → 가용성 리마인드
            d["remind"] = True
        else:
            prices[key] = d["price"]       # 동일·상승 + 최근 알림함 → 갱신만, 알림 없음
            continue
        alerts.append(d)
        prices[key] = d["price"]
        alerted[key] = now

    alerts.sort(key=lambda x: x["price"])
    alerts = alerts[: args.max_new]
    state["prices"] = prices
    state["lows"] = lows
    state["alerted"] = alerted

    if not alerts:
        save_state(state)
        log("새 매물·가격하락 없음")
        return 0

    sent = 0
    for d in alerts:
        text = format_alert(d)
        if args.dry_run or not (token and chat_id):
            print("─" * 40)
            print(text)
        elif send_telegram(token, chat_id, text):
            sent += 1

    save_state(state)
    if args.dry_run or not (token and chat_id):
        log(f"미리보기 {len(alerts)}건 (텔레그램 미설정 or --dry-run).")
    else:
        log(f"알림대상 {len(alerts)}건 중 {sent}건 텔레그램 발송.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        log(f"예외 삼킴: {e}")
        raise SystemExit(0)
