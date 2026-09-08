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
TABLE_MIN = 500      # 전체 표에 넣을 시세 하한(커먼 벌크 제외)
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


def thumb(url):
    if not url:
        return ""
    if url in _imgcache:
        return _imgcache[url]
    try:
        im = Image.open(io.BytesIO(_fetch(url, binary=True,
                        headers={"Referer": "https://collectory.cc/"}))).convert("RGB")
        im.thumbnail((150, 210))
        buf = io.BytesIO()
        im.save(buf, format="WEBP", quality=70)
        uri = "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        uri = ""
    _imgcache[url] = uri
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


def table_html(rows):
    trs = []
    for g in rows:
        rc = RCLASS.get(g["rarity"], "ex")
        link = f"https://collectory.cc/cards/{g['id']}" if g.get("id") else "#"
        trs.append(
            f'<tr><td><span class="chip sm {rc}">{H.escape(g["rarity"] or "-")}</span></td>'
            f'<td class="tn">{H.escape(g["num"])}</td>'
            f'<td><a href="{link}" target="_blank" rel="noopener">{H.escape(g["name"])}</a></td>'
            f'<td class="tp">{won(g["kr"])}</td>'
            f'<td class="tj">{won(g.get("jp"))}</td></tr>')
    return ('<details class="full"><summary>전체 카드 시세 펼치기 ('
            + str(len(rows)) + '장, 등급별)</summary>'
            '<div class="tblwrap"><table><thead><tr><th>등급</th><th>번호</th>'
            '<th>카드</th><th>🇰🇷 한국</th><th>🇯🇵 일본</th></tr></thead><tbody>'
            + "".join(trs) + "</tbody></table></div></details>")


def section(disp, query, owned):
    rows = pull(query)
    if not rows:
        print(f"  {disp}: 없음"); return ""
    grid = [g for g in rows if g["kr"] >= IMG_MIN][:TOPN]
    for g in grid:                                  # 밸류카드에 번개 붙이기
        g["bj"] = bunjang_low(g["name"], g["rarity"])
    table = sorted([g for g in rows if g["kr"] >= TABLE_MIN],
                   key=lambda x: (RORDER.get(x["rarity"], 9), -(x["kr"] or 0)))
    print(f"  {disp}: 밸류 {len(grid)} + 표 {len(table)}장, 최고 ₩{rows[0]['kr']:,}")
    own = '<span class="own-badge">보유</span>' if owned else ""
    body = "\n".join(card_html(g) for g in grid)
    meta = f"밸류 {len([g for g in rows if g['kr']>=IMG_MIN])}장 · 최고 🇰🇷 ₩{rows[0]['kr']:,}"
    return (f'  <section class="pack"><div class="pack-head"><h2>{H.escape(disp)}</h2>{own}'
            f'<span class="pack-meta">{meta}</span></div><div class="grid">\n{body}\n</div>'
            f'{table_html(table)}</section>')


def main():
    print("콜렉토리+번개장터에서 수집 중...")
    secs = "\n".join(section(*p) for p in PACKS)
    html = (f'<title>포켓몬 카드 밸류 시세 (한국·다중소스)</title>\n<style>{_CSS}</style>\n'
            f'<div class="wrap">\n{_HEADER}\n{secs}\n{_FOOTER}\n</div>')
    OUT.write_text(html, encoding="utf-8")
    print(f"생성 완료: {OUT} ({len(html.encode('utf-8'))//1024}KB, "
          f"이미지 {sum(1 for v in _imgcache.values() if v)}장)")


_HEADER = '''  <header class="top">
    <p class="eyebrow">Pokémon TCG · 팩별 밸류카드 · 한국 실거래</p>
    <h1>내 포켓몬 카드 시세판</h1>
    <p class="sub">감시 10팩의 카드를 <b>한국 실거래(콜렉토리)</b>로 — 이미지·등급·한국 시세 + <b>일본 비교</b>. 밸류카드엔 <b>번개장터 중고 최저가</b>도. 각 팩 "전체 카드 시세 펼치기"로 SR·AR·RR급까지 다 봅니다.</p>
    <div class="legend"><span class="lg-lbl">등급</span>
      <span class="rk"><span class="dot" style="background:var(--mur)"></span>MUR</span>
      <span class="rk"><span class="dot" style="background:var(--sar)"></span>SAR</span>
      <span class="rk"><span class="dot" style="background:var(--ur)"></span>UR</span>
      <span class="rk"><span class="dot" style="background:var(--sr)"></span>SR</span>
      <span class="rk"><span class="dot" style="background:var(--ar)"></span>AR</span>
      <span class="rk"><span class="dot" style="background:var(--ex)"></span>RR/R</span></div>
  </header>'''

_FOOTER = '''  <div class="note"><b>다중소스.</b> 카드 시세=콜렉토리 한국 실거래(🇯🇵 일본 비교), 밸류카드 <b>번개</b>=번개장터 중고 단품 최저가(대략·매입/박스 제외). 전체 표는 SR·AR·RR급까지, 커먼(500원↓)만 생략.</div>
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
.full{border-top:1px solid var(--line)}
.full summary{padding:12px 20px;font-size:13px;font-weight:700;color:var(--muted);cursor:pointer;user-select:none}
.full summary:hover{color:var(--text)}
.tblwrap{overflow-x:auto;padding:0 20px 18px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;color:var(--faint);font-weight:600;padding:6px 8px;border-bottom:1px solid var(--border);font-size:11px;text-transform:uppercase;letter-spacing:.04em}
td{padding:6px 8px;border-bottom:1px solid var(--line)}
td a{color:inherit;text-decoration:none}td a:hover{color:var(--sar)}
.tn,.tp,.tj{font-variant-numeric:tabular-nums}.tp{font-weight:700}.tj{color:var(--faint)}
.note{margin-top:24px;background:var(--surface);border:1px solid var(--border);border-radius:11px;padding:13px 16px;font-size:13px;color:var(--muted)}.note b{color:var(--text)}
footer{margin-top:22px;color:var(--faint);font-size:12.5px}'''


if __name__ == "__main__":
    main()
