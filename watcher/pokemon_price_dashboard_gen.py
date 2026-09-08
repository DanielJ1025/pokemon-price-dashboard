#!/usr/bin/env python
"""포켓몬 카드 밸류 시세 대시보드 생성기 (콜렉토리 한국 실거래 + 번개장터 중고 다중소스).

콜렉토리 API에서 팩별 전 카드·한국/일본 시세·등급·이미지를 받고, 밸류카드엔
번개장터 중고 최저가를 붙여 정적 HTML 대시보드 생성. 순수 파이썬(Pillow).

사용: python pokemon_price_dashboard_gen.py  → 같은 폴더 pokemon_price_dashboard.html
"""
import base64
import io
import json
import sys
import urllib.parse
import urllib.request
import gzip
import html as H
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Pillow 필요: pip install Pillow"); sys.exit(1)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
OUT = Path(__file__).resolve().parent / "pokemon_price_dashboard.html"

PACKS = [
    ("어비스아이", "어비스아이", True), ("니힐제로", "니힐제로", True),
    ("스톰에메랄다", "스톰에메랄다", True), ("사이버저지", "사이버저지", False),
    ("메가심포니아", "메가심포니아", False), ("초전브레이커", "초전브레이커", False),
    ("블랙볼트", "블랙볼트", False), ("화이트플레어", "화이트플레어", False),
    ("낙원드래고나", "낙원드래고나", False), ("포켓몬 카드 151", "포켓몬카드 151", False),
]
IMG_MIN = 3000       # 이미지 그리드에 넣을 밸류 하한
TOPN = 15            # 팩당 이미지 카드 수
TABLE_MIN = 0        # 전체 표: 시세 있는 카드 전부(비주류·홀로·커먼까지)
RCLASS = {"MUR": "MUR", "HR": "MUR", "SAR": "SAR", "UR": "UR",
          "SR": "SR", "AR": "AR", "RR": "ex", "R": "ex"}
RORDER = {"MUR": 0, "HR": 0, "UR": 1, "SAR": 2, "SR": 3, "AR": 4, "RR": 5, "R": 6}
_BUNJANG_EXC = ["매입", "삽니다", "사요", "구매", "구합", "박스", "미개봉",
                "30팩", "20팩", "벌크", "일괄", "통", "세트"]


def _fetch(url, binary=False, headers=None):
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return raw if binary else raw.decode("utf-8", "replace")


def pull(query):
    url = ("https://collectory.cc/api/cards/search?q="
           + urllib.parse.quote(query) + "&limit=500")
    try:
        j = json.loads(_fetch(url, headers={"Referer": "https://collectory.cc/"}))
    except Exception as e:
        print(f"  API 실패({query!r}): {e}"); return []
    cards = (j.get("results", {}) or {}).get("cards") or j.get("cards") or []
    by = {}
    for c in cards:
        num = c.get("cardNumber", "")
        g = by.setdefault(num, {"num": num, "name": None, "rarity": None,
                                "img": None, "id": None, "kr": None, "jp": None})
        reg = c.get("region")
        if reg in ("kr", "jp"):
            g[reg] = c.get("price")
        if reg == "kr":
            g["name"] = c.get("name"); g["rarity"] = c.get("rarity")
            g["img"] = c.get("imageUrl"); g["id"] = c.get("id")
        if not g["img"]:
            g["img"] = c.get("imageUrl")
    out = [g for g in by.values() if g["kr"] and g["name"]]
    out.sort(key=lambda x: -(x["kr"] or 0))
    return out


def bunjang_low(name, rarity):
    """번개장터 중고 단품 최저가(대략). 매입·박스 제외, 이름·등급 키워드 매칭."""
    q = f"{name} {rarity}" if rarity else name
    url = ("https://api.bunjang.co.kr/api/1/find_v2.json?"
           + urllib.parse.urlencode({"q": q, "order": "score", "page": 0, "n": 30}))
    try:
        lst = json.loads(_fetch(url)).get("list", [])
    except Exception:
        return None
    prices = []
    for it in lst:
        nm = it.get("name", "")
        try:
            pr = int(str(it.get("price") or 0).replace(",", ""))
        except ValueError:
            pr = 0
        if pr < 1000 or any(e in nm for e in _BUNJANG_EXC):
            continue
        prices.append(pr)
    return min(prices) if prices else None


_imgcache = {}
_rawcache = {}


def _raw(url):
    """원본 바이트 1회만 다운로드(사이즈별 재사용)."""
    if url not in _rawcache:
        try:
            _rawcache[url] = _fetch(url, binary=True,
                                    headers={"Referer": "https://collectory.cc/"})
        except Exception:
            _rawcache[url] = None
    return _rawcache[url]


def thumb(url, box=(150, 210)):
    if not url:
        return ""
    key = (url, box)
    if key in _imgcache:
        return _imgcache[key]
    uri = ""
    raw = _raw(url)
    if raw:
        try:
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            im.thumbnail(box)
            buf = io.BytesIO()
            im.save(buf, format="WEBP", quality=70)
            uri = "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
        except Exception:
            uri = ""
    _imgcache[key] = uri
    return uri


def won(v):
    return f"₩{v:,}" if v else "-"


def card_html(g):
    rc = RCLASS.get(g["rarity"], "ex")
    img = thumb(g.get("img"))
    imgtag = (f'<img class="thumb" src="{img}" alt="" loading="lazy"/>' if img
              else '<div class="thumb noimg">🎴</div>')
    link = f"https://collectory.cc/cards/{g['id']}" if g.get("id") else "#"
    cmp = f'<span class="cmp">日 {won(g["jp"])}</span>' if g.get("jp") else ""
    bj = f'<span class="bj">번개 {won(g["bj"])}</span>' if g.get("bj") else ""
    top = " top" if g["kr"] >= 100000 else ""
    return (f'      <a class="card" href="{link}" target="_blank" rel="noopener">{imgtag}'
            f'<div class="cbody"><div class="card-top"><span class="chip {rc}">'
            f'{H.escape(g["rarity"] or "-")}</span><span class="num">{H.escape(g["num"])}'
            f'</span></div><div class="cname">{H.escape(g["name"])}</div>'
            f'<div class="price{top}">🇰🇷 {won(g["kr"])}</div>{cmp}{bj}</div></a>')


TOP_TIER = {"MUR", "HR", "UR", "SAR"}      # 최상위 등급 = 한 그룹으로 병합
TOP_KEY = "MUR·UR·SAR"


def _tr(g, show_rarity=False):
    link = f"https://collectory.cc/cards/{g['id']}" if g.get("id") else "#"
    im = thumb(g.get("img"), (64, 90))
    imgtag = (f'<img class="tth" src="{im}" loading="lazy" alt=""/>' if im
              else '<span class="tth noimg">🎴</span>')
    chip = (f'<span class="chip sm {RCLASS.get(g["rarity"], "ex")}">{H.escape(g["rarity"] or "-")}</span>'
            if show_rarity else "")
    ck = (f'<input type="checkbox" class="own-ck" data-id="{H.escape(str(g["id"]))}" '
          f'data-kr="{g["kr"] or 0}" title="보유 체크"/>' if g.get("id") else "")
    return (f'<tr><td class="tn">{H.escape(g["num"])}</td>'
            f'<td><div class="cardcell">{ck}{imgtag}<span class="cc-txt">{chip}'
            f'<a href="{link}" target="_blank" rel="noopener">{H.escape(g["name"])}</a>'
            f'</span></div></td>'
            f'<td class="tp">{won(g["kr"])}</td><td class="tj">{won(g.get("jp"))}</td></tr>')


def table_html(rows):
    """등급별 접이식 그룹. MUR·UR·SAR은 한 그룹으로 병합, 최고 등급만 기본 펼침, 그룹 내 가격순."""
    groups = {}
    for g in rows:
        k = TOP_KEY if g["rarity"] in TOP_TIER else (g["rarity"] or "-")
        groups.setdefault(k, []).append(g)
    ordered = sorted(groups.items(),
                     key=lambda kv: (-1 if kv[0] == TOP_KEY else RORDER.get(kv[0], 9), kv[0]))
    blocks = []
    for idx, (rar, gs) in enumerate(ordered):
        gs.sort(key=lambda x: -(x["kr"] or 0))
        merged = rar == TOP_KEY
        rc = "MUR" if merged else RCLASS.get(rar, "ex")
        op = " open" if idx == 0 else ""      # 최고 등급 그룹만 기본 펼침
        blocks.append(
            f'<details class="rgrp"{op}><summary><span class="chip sm {rc}">{H.escape(rar)}</span>'
            f'<span class="rgrp-n">{len(gs)}장</span><span class="rgrp-own"></span>'
            f'<span class="rgrp-top">최고 {won(gs[0]["kr"])}</span></summary>'
            f'<div class="tblwrap"><table><thead><tr><th>번호</th><th>카드</th>'
            f'<th>🇰🇷 한국</th><th>🇯🇵 일본</th></tr></thead><tbody>'
            + "".join(_tr(g, merged) for g in gs) + '</tbody></table></div></details>')
    return (f'<div class="full"><div class="full-hd">전체 카드 시세 · {len(rows)}장 · 등급별 '
            f'(MUR·UR·SAR 병합 · 최고 등급 기본 펼침 · 머리글로 가격정렬)</div>'
            + "".join(blocks) + '</div>')


def _base_count(rows):
    """정규세트 카드 상한(카드번호 분모 '046/081'→081). 최빈 분모=정규 장수."""
    from collections import Counter
    dens = Counter()
    for g in rows:
        num = g.get("num", "")
        if "/" in num:
            d = num.split("/", 1)[1].strip()
            if d.isdigit():
                dens[d] += 1
    return dens.most_common(1)[0][0] if dens else "?"


def section(disp, query, owned):
    rows = pull(query)
    if not rows:
        print(f"  {disp}: 없음"); return ""
    base = _base_count(rows)
    print(f"  {disp}: {len(rows)}장(정규 /{base}), 최고 ₩{rows[0]['kr']:,}")
    own = '<span class="own-badge">보유</span>' if owned else ""
    meta = f"{len(rows)}장 · 정규 /{base} · 최고 🇰🇷 ₩{rows[0]['kr']:,}"
    return (f'  <section class="pack"><div class="pack-head"><h2>{H.escape(disp)}</h2>{own}'
            f'<span class="pack-meta">{meta}<span class="own-cnt"></span></span></div>'
            f'{table_html(rows)}</section>')


def main():
    print("콜렉토리+번개장터에서 수집 중...")
    secs = "\n".join(section(*p) for p in PACKS)
    # 팩별 탭 + 매물·가성비 탭 (JS가 section.pack 을 동적 래핑). 260908 회사 탭 로직 이식.
    deals_js = "const DEALS=" + json.dumps(DEALS, ensure_ascii=False) + ";"
    tabs = (f'<style id="tabsfix">{_TABS_CSS}</style>\n'
            f'<script>\n{deals_js}\n{_TABS_JS}\n</script>')
    html = (f'<title>포켓몬 카드 밸류 시세 (한국·다중소스)</title>\n<style>{_CSS}</style>\n'
            f'<div class="wrap">\n{_HEADER}\n{secs}\n{_FOOTER}\n</div>\n{tabs}')
    OUT.write_text(html, encoding="utf-8")
    print(f"생성 완료: {OUT} ({len(html.encode('utf-8'))//1024}KB, "
          f"이미지 {sum(1 for v in _imgcache.values() if v)}장)")


_HEADER = '''  <header class="top">
    <h1>내 포켓몬 카드 시세판</h1>
    <p class="sub">한국 실거래(콜렉토리) · 일본 비교. 팩을 골라 보세요.</p>
    <p class="own-total"></p>
  </header>'''

_FOOTER = '''  <div class="note"><b>콜렉토리 한국 실거래</b> 기준(🇯🇵 일본 비교). 팩마다 <b>등급별 그룹</b> — 시세 있는 카드 전부(홀로·커먼까지), <b>MUR·UR·SAR 병합</b>·최고등급 기본 펼침. 정규 /NNN=정규세트 상한(그 위 번호=시크릿). (시세 미등록 카드는 표시 안 됨)</div>
  <footer>출처: 콜렉토리(collectory.cc)·번개장터 · Daniel 개인 참고용 · 시세 변동.</footer>'''

_CSS = ''':root{--bg:#f6f5f2;--surface:#fff;--surface-2:#f0eee9;--border:#e2ded6;--line:#ebe8e1;--text:#1c1e26;--muted:#6b6f7d;--faint:#9a9eac;--gold:#b8860b;--mur:#d1258a;--ur:#b8860b;--sar:#7c5cd6;--ar:#12a594;--sr:#2f7ae0;--ex:#7a8394;--own:#12a594;--shadow:0 1px 2px rgba(20,22,30,.06),0 8px 24px rgba(20,22,30,.05);--sans:"Pretendard",-apple-system,BlinkMacSystemFont,"Segoe UI","Malgun Gothic","Apple SD Gothic Neo",system-ui,sans-serif}
@media (prefers-color-scheme:dark){:root{--bg:#0e0f15;--surface:#171922;--surface-2:#1e2130;--border:#2a2e3c;--line:#23262f;--text:#e7e9f0;--muted:#9aa0b2;--faint:#6a7080;--gold:#e6b23c;--mur:#ff5db1;--ur:#e6b23c;--sar:#a78bfa;--ar:#34d3b0;--sr:#5b9bff;--ex:#8892a6;--own:#34d3b0;--shadow:0 1px 2px rgba(0,0,0,.4),0 10px 30px rgba(0,0,0,.35)}}
:root[data-theme="light"]{--bg:#f6f5f2;--surface:#fff;--surface-2:#f0eee9;--border:#e2ded6;--line:#ebe8e1;--text:#1c1e26;--muted:#6b6f7d;--faint:#9a9eac;--gold:#b8860b;--mur:#d1258a;--ur:#b8860b;--sar:#7c5cd6;--ar:#12a594;--sr:#2f7ae0;--ex:#7a8394;--own:#12a594}
:root[data-theme="dark"]{--bg:#0e0f15;--surface:#171922;--surface-2:#1e2130;--border:#2a2e3c;--line:#23262f;--text:#e7e9f0;--muted:#9aa0b2;--faint:#6a7080;--gold:#e6b23c;--mur:#ff5db1;--ur:#e6b23c;--sar:#a78bfa;--ar:#34d3b0;--sr:#5b9bff;--ex:#8892a6;--own:#34d3b0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);line-height:1.5}
.wrap{max-width:1100px;margin:0 auto;padding:40px 22px 72px}
.eyebrow{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--gold);font-weight:700;margin:0 0 10px}
h1{font-size:clamp(28px,5vw,40px);line-height:1.1;margin:0 0 8px;letter-spacing:-.02em;font-weight:800}
.sub{color:var(--muted);font-size:15px;margin:0;max-width:66ch}
.legend{display:flex;flex-wrap:wrap;gap:8px 14px;margin:20px 0 6px;align-items:center}
.legend .lg-lbl{font-size:12px;color:var(--faint);text-transform:uppercase;letter-spacing:.08em}
.rk{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);font-weight:600}
.dot{width:9px;height:9px;border-radius:3px}
.pack{margin-top:26px;background:var(--surface);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow);overflow:hidden}
.pack-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 12px;padding:18px 20px;border-bottom:1px solid var(--line);background:var(--surface-2)}
.pack-head h2{font-size:19px;margin:0;font-weight:800}
.own-badge{font-size:11px;font-weight:800;color:var(--own);border:1.5px solid var(--own);border-radius:999px;padding:2px 9px}
.pack-meta{margin-left:auto;font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px;padding:18px 20px}
.card{background:var(--surface-2);border:1px solid var(--border);border-radius:12px;overflow:hidden;display:flex;flex-direction:column;text-decoration:none;color:inherit;transition:transform .12s,box-shadow .12s}
.card:hover{transform:translateY(-2px);box-shadow:var(--shadow)}
.thumb{width:100%;aspect-ratio:5/7;object-fit:cover;display:block;background:var(--line)}
.thumb.noimg{display:flex;align-items:center;justify-content:center;font-size:38px;opacity:.5}
.cbody{padding:9px 11px 11px;display:flex;flex-direction:column;gap:3px}
.card-top{display:flex;align-items:center;justify-content:space-between;gap:6px}
.chip{font-size:10px;font-weight:800;padding:1px 6px;border-radius:5px;color:#fff;white-space:nowrap}
.chip.sm{font-size:9.5px;padding:0 5px}
.chip.MUR{background:var(--mur)}.chip.UR{background:var(--ur)}.chip.SAR{background:var(--sar)}.chip.AR{background:var(--ar)}.chip.SR{background:var(--sr)}.chip.ex{background:var(--ex)}
.num{font-size:10.5px;color:var(--faint);font-variant-numeric:tabular-nums}
.cname{font-size:13px;font-weight:700;line-height:1.25;min-height:2.4em}
.price{font-size:15.5px;font-weight:800;font-variant-numeric:tabular-nums}.price.top{color:var(--gold)}
.cmp,.bj{font-size:11px;color:var(--faint);font-variant-numeric:tabular-nums}
.bj{color:var(--ar)}
.full{border-top:1px solid var(--line);padding:2px 20px 14px}
.full-hd{font-size:12.5px;font-weight:700;color:var(--muted);padding:11px 0 3px}
.rgrp{border-bottom:1px solid var(--line)}.rgrp:last-child{border-bottom:0}
.rgrp>summary{list-style:none;padding:9px 2px;font-size:13px;font-weight:700;color:var(--text);cursor:pointer;user-select:none;display:flex;align-items:center;gap:9px}
.rgrp>summary::-webkit-details-marker{display:none}
.rgrp>summary:hover{color:var(--sar)}
.rgrp-n{color:var(--faint);font-weight:600;font-size:12px}
.rgrp-top{margin-left:auto;color:var(--faint);font-weight:600;font-size:12px}
.tblwrap{overflow-x:auto;padding:0 0 10px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;color:var(--faint);font-weight:600;padding:6px 8px;border-bottom:1px solid var(--border);font-size:11px;text-transform:uppercase;letter-spacing:.04em}
td{padding:6px 8px;border-bottom:1px solid var(--line)}
td a{color:inherit;text-decoration:none}td a:hover{color:var(--sar)}
.tn,.tp,.tj{font-variant-numeric:tabular-nums}.tp{font-weight:700}.tj{color:var(--faint)}
td{vertical-align:middle}
.cardcell{display:flex;align-items:center;gap:10px}
.tth{width:40px;height:56px;object-fit:cover;border-radius:5px;background:var(--line);flex:0 0 auto}
.tth.noimg{display:inline-flex;align-items:center;justify-content:center;font-size:18px;opacity:.5}
.cc-txt{display:flex;align-items:center;gap:7px;flex-wrap:wrap;min-width:0}
.note{margin-top:24px;background:var(--surface);border:1px solid var(--border);border-radius:11px;padding:13px 16px;font-size:13px;color:var(--muted)}.note b{color:var(--text)}
footer{margin-top:22px;color:var(--faint);font-size:12.5px}'''


DEALS = {
    "updated": "2026-09-07 스냅샷",
    "rows": [
        {"pack": "스톰에메랄다", "list": 45000, "price": 54870, "malls": 104,
         "top": "메가레쿠쟈 MUR ~70만 · 가이오가 AR", "ratio": 12.8, "under": False},
        {"pack": "어비스아이", "list": 45000, "price": 46030, "malls": 132,
         "top": "메가다크라이 ex MUR ~15만·SAR ~10만", "ratio": 3.3, "under": True},
        {"pack": "니힐제로", "list": 45000, "price": 43970, "malls": 65,
         "top": "메가지가르데 ex MUR ~12만+ · 명희의 격려 SAR ~7만", "ratio": 2.7, "under": True},
        {"pack": "블랙볼트", "list": 40000, "price": 54490, "malls": 63,
         "top": "제크로무 BWR ~12만+", "ratio": 2.2, "under": False},
        {"pack": "초전브레이커", "list": 45000, "price": 59490, "malls": 64,
         "top": "피카츄 ex SAR ~10만 · 자포코일 AR", "ratio": 1.7, "under": False},
        {"pack": "낙원드래고나", "list": 45000, "price": 46720, "malls": 45,
         "top": "라티아스 ex SAR ~6.5~7만 (천장 낮음)", "ratio": 1.5, "under": True},
        {"pack": "포켓몬 카드 151", "list": 50000, "price": None, "malls": 10,
         "top": "리자몽 ex SAR ~11만", "ratio": None, "under": False,
         "note": "다나와가 30팩 미집계·20개입 번들만 잡혀 가격 왜곡"},
        {"pack": "화이트플레어", "list": 40000, "price": 55000, "malls": 15,
         "top": "레시라무 BWR · 제크로무", "ratio": None, "under": False,
         "note": "쿠팡 품절유령 제외 후 실가"},
    ],
}

_TABS_CSS = '''.wrap{max-width:1240px;margin:0 auto;padding:36px 24px 72px;display:flex;gap:34px;align-items:flex-start}
.sidebar{position:sticky;top:22px;width:214px;flex:0 0 214px}
.sidebar .brand{margin:0 0 20px}
.sidebar .brand h1{font-size:21px;line-height:1.15;margin:0 0 6px;letter-spacing:-.02em;font-weight:800}
.sidebar .brand .sub{font-size:12px;color:var(--muted);margin:0;max-width:none;line-height:1.5}
.tablist{display:flex;flex-direction:column;gap:2px}
.tablist button{font:inherit;font-size:13.5px;font-weight:600;color:var(--muted);text-align:left;background:transparent;border:0;border-radius:9px;padding:8px 12px;cursor:pointer;width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:background .12s,color .12s}
.tablist button:hover{background:var(--surface-2);color:var(--text)}
.tablist button.active{background:var(--sar);color:#fff;font-weight:700}
.tablist button.deal{color:var(--gold)}
.tablist button.deal.active{background:var(--gold);color:#1c1e26}
.tablist .sep{height:1px;background:var(--border);margin:8px 6px}
.content{flex:1;min-width:0}
.content section.pack{margin-top:0}
section.pack[hidden],#deals-panel[hidden],#owned-panel[hidden]{display:none!important}
.tablist button.own{color:var(--own)}.tablist button.own.active{background:var(--own);color:#fff}
.own-ck{width:16px;height:16px;flex:0 0 auto;cursor:pointer;accent-color:var(--own);margin:0}
.own-cnt{color:var(--own);font-weight:700}
.rgrp-own{color:var(--own);font-weight:700;font-size:12px}
.own-total{color:var(--own);font-weight:800;font-size:12.5px;margin:9px 0 0}
#owned-panel h2{margin:0 0 2px}
#owned-panel .sub2{color:var(--muted);font-size:13px;margin:0 0 16px}
#owned-panel .dim{color:var(--faint)}
.owned-grp{margin:0 0 16px}
.owned-h{font-size:13.5px;font-weight:800;padding:9px 2px 7px;border-bottom:1px solid var(--line)}
.full th.sortable{cursor:pointer;user-select:none}.full th.sortable:hover{color:var(--text)}
.full th.sorted{color:var(--sar)}.full th.sorted[data-dir="down"]::after{content:" ▾"}.full th.sorted[data-dir="up"]::after{content:" ▴"}
@media(max-width:860px){
 .wrap{flex-direction:column;gap:14px;padding:24px 16px 60px}
 .sidebar{position:static;width:auto;flex:none}
 .sidebar .brand{margin-bottom:12px}
 .tablist{flex-direction:row;flex-wrap:wrap;gap:6px}
 .tablist button{width:auto;background:var(--surface-2);border:1px solid var(--border);border-radius:999px;padding:6px 12px;font-size:12.5px;font-weight:700}
 .tablist .sep{display:none}
}
#deals-panel{margin:2px 0 24px}
#deals-panel h2{margin:0 0 2px}
#deals-panel .sub2{color:var(--muted);font-size:12.5px;margin:0 0 14px;line-height:1.6}
#deals-panel .tblwrap{overflow-x:auto}
#deals-panel table{width:100%;border-collapse:collapse;font-size:13px;min-width:560px}
#deals-panel th,#deals-panel td{padding:9px 11px;border-bottom:1px solid var(--line);text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
#deals-panel th{color:var(--faint);font-weight:700;font-size:10.5px;letter-spacing:.04em;text-transform:uppercase}
#deals-panel td.name,#deals-panel th.name{text-align:left;font-weight:800}
#deals-panel td.top,#deals-panel th.top{text-align:left;color:var(--muted);font-weight:600;white-space:normal}
#deals-panel tr.under td{background:color-mix(in srgb,var(--own) 13%,transparent)}
#deals-panel .ratio{font-weight:800;color:var(--gold)}
#deals-panel .dim{color:var(--faint)}
#deals-panel .badge{display:inline-block;font-size:10px;font-weight:800;padding:2px 7px;border-radius:6px;background:var(--own);color:#fff;margin-left:6px}
#deals-panel .note2{color:var(--faint);font-size:11.5px;margin-top:14px;line-height:1.7}'''

_TABS_JS = '''(function(){
 const won=n=>n==null?"—":"₩"+n.toLocaleString();
 const numOf=s=>{const d=(s||"").replace(/[^0-9]/g,"");return d?+d:-1;};
 const OWNKEY="pkm_owned";
 let owned;try{owned=new Set(JSON.parse(localStorage.getItem(OWNKEY)||"[]"))}catch(e){owned=new Set();}
 const saveOwned=()=>{try{localStorage.setItem(OWNKEY,JSON.stringify([...owned]))}catch(e){}};
 function renderDeals(){
  const rows=DEALS.rows.map(r=>{
   const price=r.price==null?'<span class="dim">품절/왜곡</span>':won(r.price);
   const ratio=r.ratio==null?'<span class="dim">—</span>':'<span class="ratio">'+r.ratio+'x</span>';
   const badge=r.under?'<span class="badge">정가이하</span>':'';
   const note=r.note?'<div class="dim" style="font-size:11px;margin-top:3px">⚠️ '+r.note+'</div>':'';
   return '<tr class="'+(r.under?'under':'')+'">'
     +'<td class="name">'+r.pack+badge+'</td><td>'+won(r.list)+'</td><td>'+price+'</td>'
     +'<td>'+(r.malls||'—')+'</td><td>'+ratio+'</td><td class="top">'+r.top+note+'</td></tr>';
  }).join('');
  return '<h2>💰 매물 · 고점대비 가성비</h2>'
   +'<p class="sub2">감시기 <b>다나와 실구매가</b>(배송포함, 쿠팡 품절유령 제외) · <b>'+DEALS.updated+'</b><br>'
   +'<b>배수</b> = 고점카드 천장 ÷ 현재 박스가 = <b>뽑으면 최대 몇 배</b>(확률 미반영). <b>초록=정가 이하 구매 가능</b>.</p>'
   +'<div class="tblwrap"><table><thead><tr>'
   +'<th class="name">팩</th><th>정가</th><th>현재 실구매가</th><th>판매처</th><th>배수</th><th class="top">고점 천장 카드</th>'
   +'</tr></thead><tbody>'+rows+'</tbody></table></div>'
   +'<div class="note2">· 배수는 확률 미반영 참고치 · 매물 스냅샷은 감시기 기준일. 카드 시세는 각 팩 탭에서 라이브.</div>';
 }
 const wrap=document.querySelector('.wrap');
 const packs=[...wrap.querySelectorAll('section.pack')];
 if(!packs.length)return;
 const header=wrap.querySelector('header.top');
 const note=wrap.querySelector('.note');
 const footer=wrap.querySelector('footer');
 const dp=document.createElement('div');dp.id='deals-panel';dp.innerHTML=renderDeals();
 const opn=document.createElement('div');opn.id='owned-panel';
 // 좌측 사이드바(브랜드 + 세로 탭)
 const side=document.createElement('aside');side.className='sidebar';
 const brand=document.createElement('div');brand.className='brand';
 brand.innerHTML=header?header.innerHTML:'<h1>내 포켓몬 카드 시세판</h1>';
 const nav=document.createElement('nav');nav.className='tablist';
 side.appendChild(brand);side.appendChild(nav);
 // 우측 콘텐츠(선택 탭만 노출)
 const content=document.createElement('main');content.className='content';
 content.appendChild(dp);content.appendChild(opn);
 packs.forEach(p=>content.appendChild(p));
 if(note)content.appendChild(note);
 if(footer)content.appendChild(footer);
 wrap.innerHTML='';wrap.appendChild(side);wrap.appendChild(content);
 // 보유 체크: localStorage 저장, 팩/등급별 개수 + 사이드바 합계·총액
 const boxes=[...document.querySelectorAll('input.own-ck')];
 function updateCounts(){
  let total=0,val=0;
  packs.forEach(sec=>{
   let n=0;sec.querySelectorAll('input.own-ck').forEach(b=>{if(b.checked)n++;});
   total+=n;const el=sec.querySelector('.own-cnt');if(el)el.textContent=n?(' · 보유 '+n):'';
   sec.querySelectorAll('.rgrp').forEach(gr=>{let gn=0;gr.querySelectorAll('input.own-ck').forEach(b=>{if(b.checked)gn++;});const s=gr.querySelector('.rgrp-own');if(s)s.textContent=gn?('보유 '+gn):'';});
  });
  boxes.forEach(b=>{if(b.checked)val+=(+b.dataset.kr||0);});
  const t=brand.querySelector('.own-total');if(t)t.textContent=total?('🎴 보유 '+total+'장 · 추정 '+won(val)):'';
 }
 function renderOwned(){
  opn.innerHTML='';
  const head=document.createElement('div');opn.appendChild(head);
  let total=0,val=0;const blocks=[];
  packs.forEach(sec=>{
   const pack=(sec.querySelector('h2')||{textContent:''}).textContent.trim();
   const checked=[...sec.querySelectorAll('input.own-ck:checked')];
   if(!checked.length)return;
   let sub=0;const tb=document.createElement('tbody');
   checked.forEach(cb=>{const tr=cb.closest('tr');if(!tr)return;const kr=+cb.dataset.kr||0;sub+=kr;total++;val+=kr;const c=tr.cloneNode(true);const x=c.querySelector('input.own-ck');if(x)x.remove();tb.appendChild(c);});
   const d=document.createElement('div');d.className='owned-grp';
   d.innerHTML='<div class="owned-h">'+pack+' <span class="dim">'+checked.length+'장 · '+won(sub)+'</span></div>';
   const tbl=document.createElement('table');tbl.appendChild(tb);
   const w=document.createElement('div');w.className='tblwrap';w.appendChild(tbl);
   d.appendChild(w);blocks.push(d);
  });
  head.innerHTML='<h2>💼 내 보유카드</h2><p class="sub2">총 <b>'+total+'장</b> · 추정 가치 <b>'+won(val)+'</b> <span class="dim">(콜렉토리 한국 실거래 합계)</span></p>';
  if(!total){const e=document.createElement('p');e.className='dim';e.style.padding='10px 2px';e.textContent='체크한 카드가 없습니다. 각 팩에서 보유 카드를 체크하세요.';opn.appendChild(e);return;}
  blocks.forEach(b=>opn.appendChild(b));
 }
 boxes.forEach(b=>{if(owned.has(b.dataset.id))b.checked=true;b.addEventListener('change',()=>{b.checked?owned.add(b.dataset.id):owned.delete(b.dataset.id);saveOwned();updateCounts();if(!opn.hidden)renderOwned();});});
 const btns=[];
 function add(label,cls,onclick){const b=document.createElement('button');b.textContent=label;if(cls)b.className=cls;b.title=label;b.onclick=onclick;nav.appendChild(b);btns.push(b);return b;}
 function select(i){btns.forEach((b,j)=>b.classList.toggle('active',j===i));dp.hidden=(i!==0);opn.hidden=(i!==1);packs.forEach((p,j)=>p.hidden=(i!==j+2));if(i===1)renderOwned();try{localStorage.setItem('pkm_tab',i)}catch(e){}}
 add('💰 매물·가성비','deal',()=>select(0));
 add('💼 내 보유카드','own',()=>select(1));
 const sep=document.createElement('div');sep.className='sep';nav.appendChild(sep);
 packs.forEach((p,j)=>{const nm=(p.querySelector('h2')||{}).textContent||('팩'+(j+1));add(nm.trim(),'',()=>select(j+2));});
 updateCounts();
 let start=2;try{const s=parseInt(localStorage.getItem('pkm_tab'));if(!isNaN(s)&&s>=0&&s<packs.length+2)start=s;}catch(e){}
 select(start);
 // 등급그룹 표 정렬: 🇰🇷한국(2)·🇯🇵일본(3) 가격열 머리글 클릭 토글(기본 내림차순)
 document.querySelectorAll(".full table").forEach(tb=>{
  const tbody=tb.querySelector("tbody"),ths=tb.querySelectorAll("th");
  const rws=[...tbody.querySelectorAll("tr")];let last={i:null,dir:-1};
  function sort(i){const dir=last.i===i?-last.dir:-1;last={i,dir};rws.sort((a,b)=>(numOf(a.children[i].textContent)-numOf(b.children[i].textContent))*dir);rws.forEach(r=>tbody.appendChild(r));ths.forEach((t,j)=>{const on=j===i;t.classList.toggle("sorted",on);t.dataset.dir=on?(dir>0?"up":"down"):"";});}
  [2,3].forEach(i=>{const t=ths[i];if(!t)return;t.classList.add("sortable");t.title="클릭: 가격 정렬";t.addEventListener("click",()=>sort(i));});
 });
})();'''


if __name__ == "__main__":
    main()
