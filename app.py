#!/usr/bin/env python
"""포켓몬 카드 밸류 시세 대시보드 — Render 라이브 웹앱.

콜렉토리 공개 API를 요청 시 조회(1시간 캐시)해 항상 최신 한국/일본 시세를 보여준다.
서버 렌더라 이미지는 콜렉토리 CDN URL 직접 사용(임베드 불필요). 어디서나 접속 가능.

로컬 실행:  pip install flask ; python app.py  → http://localhost:5000
Render 배포: render.yaml 참고(무료 Web Service).
"""
import gzip
import html as H
import json
import time
import urllib.parse
import urllib.request

from flask import Flask, Response

app = Flask(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
PACKS = [
    ("어비스아이", "어비스아이", True), ("니힐제로", "니힐제로", True),
    ("스톰에메랄다", "스톰에메랄다", True), ("사이버저지", "사이버저지", False),
    ("메가심포니아", "메가심포니아", False), ("초전브레이커", "초전브레이커", False),
    ("블랙볼트", "블랙볼트", False), ("화이트플레어", "화이트플레어", False),
    ("낙원드래고나", "낙원드래고나", False), ("포켓몬 카드 151", "포켓몬카드 151", False),
]
MIN_KR, TOPN = 3000, 15
RCLASS = {"MUR": "MUR", "HR": "MUR", "SAR": "SAR", "UR": "UR",
          "SR": "SR", "AR": "AR", "RR": "ex", "R": "ex"}
RORDER = {"MUR": 0, "HR": 0, "UR": 1, "SAR": 2, "SR": 3, "AR": 4, "RR": 5, "R": 6}
_cache = {"t": 0, "html": ""}
CACHE_TTL = 3600  # 1시간


def pull(query):
    url = ("https://collectory.cc/api/cards/search?q="
           + urllib.parse.quote(query) + "&limit=500")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json",
        "Referer": "https://collectory.cc/"})
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    j = json.loads(raw.decode("utf-8"))
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
            g.update(name=c.get("name"), rarity=c.get("rarity"),
                     img=c.get("imageUrl"), id=c.get("id"))
        if not g["img"]:
            g["img"] = c.get("imageUrl")
    out = [g for g in by.values() if g["kr"] and g["name"]]
    out.sort(key=lambda x: -(x["kr"] or 0))
    return out


def won(v):
    return f"₩{v:,}" if v else "-"


def card_html(g):
    rc = RCLASS.get(g["rarity"], "ex")
    img = g.get("img")
    imgtag = (f'<img class="thumb" src="{H.escape(img)}" alt="" loading="lazy"/>'
              if img else '<div class="thumb noimg">🎴</div>')
    link = f"https://collectory.cc/cards/{g['id']}" if g.get("id") else "#"
    cmp = f'<span class="cmp">日 {won(g["jp"])}</span>' if g.get("jp") else ""
    top = " top" if g["kr"] >= 100000 else ""
    return (f'<a class="card" href="{link}" target="_blank" rel="noopener">{imgtag}'
            f'<div class="cbody"><div class="card-top"><span class="chip {rc}">'
            f'{H.escape(g["rarity"] or "-")}</span><span class="num">'
            f'{H.escape(g["num"])}</span></div><div class="cname">'
            f'{H.escape(g["name"])}</div><div class="price{top}">🇰🇷 {won(g["kr"])}'
            f'</div>{cmp}</div></a>')


TOP_TIER = {"MUR", "HR", "UR", "SAR"}      # 최상위 등급 = 한 그룹으로 병합
TOP_KEY = "MUR·UR·SAR"


def _tr(g, show_rarity=False, pack=""):
    link = f"https://collectory.cc/cards/{g['id']}" if g.get("id") else "#"
    im = g.get("img")
    imgtag = (f'<img class="tth" src="{H.escape(im)}" loading="lazy" alt=""/>' if im
              else '<span class="tth noimg">🎴</span>')
    rar = g.get("rarity") or "-"
    tag = f'<span class="rtag {RCLASS.get(rar, "ex")}">[{H.escape(rar)}]</span>'
    qc = (f'<span class="qty" data-id="{H.escape(str(g["id"]))}" data-kr="{g["kr"] or 0}">'
          f'<button class="qm" type="button" tabindex="-1">−</button>'
          f'<b class="qn">0</b>'
          f'<button class="qp" type="button" tabindex="-1">+</button></span>'
          if g.get("id") else "")
    wb = (f'<button class="wish" data-id="{H.escape(str(g["id"]))}" title="위시리스트" tabindex="-1">★</button>'
          if g.get("id") else "")
    pk = f'<span class="pk">{H.escape(pack)}</span>' if pack else ""
    return (f'<tr><td class="tn">{H.escape(g["num"])}</td>'
            f'<td><div class="cardcell">{qc}{wb}{imgtag}<span class="cc-txt">{tag} '
            f'<a href="{link}" target="_blank" rel="noopener">{H.escape(g["name"])}</a>{pk}'
            f'</span></div></td>'
            f'<td class="tp">{won(g["kr"])}</td><td class="tj">{won(g.get("jp"))}</td></tr>')


def table_html(rows, pack=""):
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
            + "".join(_tr(g, merged, pack) for g in gs) + '</tbody></table></div></details>')
    return (f'<div class="full"><div class="full-hd">전체 카드 시세 · {len(rows)}장 · 등급별 '
            f'(MUR·UR·SAR 병합 · 최고 등급 기본 펼침 · 머리글로 가격정렬)</div>'
            + "".join(blocks) + '</div>')


def _base_count(rows):
    from collections import Counter
    dens = Counter()
    for g in rows:
        num = g.get("num", "")
        if "/" in num:
            d = num.split("/", 1)[1].strip()
            if d.isdigit():
                dens[d] += 1
    return dens.most_common(1)[0][0] if dens else "?"


def build():
    secs = []
    for disp, query, owned in PACKS:
        try:
            allrows = pull(query)
        except Exception:
            allrows = []
        if not allrows:
            continue
        base = _base_count(allrows)
        own = '<span class="own-badge">보유</span>' if owned else ""
        meta = f"{len(allrows)}장 · 정규 /{base} · 최고 🇰🇷 ₩{allrows[0]['kr']:,}"
        secs.append(f'<section class="pack" data-base="{base}"><div class="pack-head"><h2>'
                    f'{H.escape(disp)}</h2>{own}<span class="pack-meta">{meta}'
                    f'<span class="own-cnt"></span></span><div class="pack-prog"></div></div>'
                    f'{table_html(allrows, disp)}</section>')
    upd = time.strftime("%Y-%m-%d %H:%M", time.localtime())
    tabs = (f'<script>const DEALS={json.dumps(DEALS, ensure_ascii=False)};'
            f'{_TABS_JS}</script>')
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"/>'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"/>'
            f'<title>내 포켓몬 카드 시세판</title><style>{_CSS}{_TABS_CSS}</style></head><body>'
            f'<div class="wrap">{_HEADER}{"".join(secs)}'
            f'<div class="note"><b>다중소스.</b> 콜렉토리 한국 실거래 기준(🇯🇵 일본 비교). '
            f'1시간마다 갱신 · 갱신 {upd}. 시세는 변동됩니다.</div>'
            f'<footer>출처: collectory.cc · Daniel 개인 참고용.</footer></div>{tabs}</body></html>')


@app.route("/")
def index():
    now = time.time()
    if now - _cache["t"] > CACHE_TTL or not _cache["html"]:
        _cache["html"] = build()
        _cache["t"] = now
    return Response(_cache["html"], mimetype="text/html")


@app.route("/healthz")
def health():
    return "ok"


_HEADER = ('<header class="top"><h1>내 포켓몬 카드 시세판</h1>'
           '<p class="sub">한국 실거래(콜렉토리) · 일본 비교 · 1시간마다 갱신. 팩을 골라 보세요.</p>'
           '<p class="own-total"></p></header>')

_CSS = (':root{--bg:#f6f5f2;--surface:#fff;--surface-2:#f0eee9;--border:#e2ded6;--line:#ebe8e1;'
        '--text:#1c1e26;--muted:#6b6f7d;--faint:#9a9eac;--gold:#b8860b;--mur:#d1258a;--ur:#b8860b;'
        '--sar:#7c5cd6;--ar:#12a594;--sr:#2f7ae0;--ex:#7a8394;--own:#12a594;'
        '--shadow:0 1px 2px rgba(20,22,30,.06),0 8px 24px rgba(20,22,30,.05);'
        '--sans:"Pretendard",-apple-system,"Segoe UI","Malgun Gothic",system-ui,sans-serif}'
        '@media(prefers-color-scheme:dark){:root{--bg:#0e0f15;--surface:#171922;--surface-2:#1e2130;'
        '--border:#2a2e3c;--line:#23262f;--text:#e7e9f0;--muted:#9aa0b2;--faint:#6a7080;--gold:#e6b23c;'
        '--mur:#ff5db1;--ur:#e6b23c;--sar:#a78bfa;--ar:#34d3b0;--sr:#5b9bff;--ex:#8892a6;--own:#34d3b0}}'
        '*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);'
        'font-family:var(--sans);line-height:1.5}.wrap{max-width:1100px;margin:0 auto;padding:40px 22px 72px}'
        '.eyebrow{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--gold);font-weight:700;margin:0 0 10px}'
        'h1{font-size:clamp(28px,5vw,40px);line-height:1.1;margin:0 0 8px;letter-spacing:-.02em;font-weight:800}'
        '.sub{color:var(--muted);font-size:15px;margin:0;max-width:64ch}'
        '.legend{display:flex;flex-wrap:wrap;gap:8px 14px;margin:20px 0 6px;align-items:center}'
        '.legend .lg-lbl{font-size:12px;color:var(--faint);text-transform:uppercase;letter-spacing:.08em}'
        '.rk{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);font-weight:600}'
        '.dot{width:9px;height:9px;border-radius:3px}'
        '.pack{margin-top:26px;background:var(--surface);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow);overflow:hidden}'
        '.pack-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 12px;padding:18px 20px;border-bottom:1px solid var(--line);background:var(--surface-2)}'
        '.pack-head h2{font-size:19px;margin:0;font-weight:800}'
        '.own-badge{font-size:11px;font-weight:800;color:var(--own);border:1.5px solid var(--own);border-radius:999px;padding:2px 9px}'
        '.pack-meta{margin-left:auto;font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums}'
        '.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px;padding:18px 20px}'
        '.card{background:var(--surface-2);border:1px solid var(--border);border-radius:12px;overflow:hidden;display:flex;flex-direction:column;text-decoration:none;color:inherit;transition:transform .12s,box-shadow .12s}'
        '.card:hover{transform:translateY(-2px);box-shadow:var(--shadow)}'
        '.thumb{width:100%;aspect-ratio:5/7;object-fit:cover;display:block;background:var(--line)}'
        '.thumb.noimg{display:flex;align-items:center;justify-content:center;font-size:38px;opacity:.5}'
        '.cbody{padding:9px 11px 11px;display:flex;flex-direction:column;gap:4px}'
        '.card-top{display:flex;align-items:center;justify-content:space-between;gap:6px}'
        '.chip{font-size:10px;font-weight:800;padding:1px 6px;border-radius:5px;color:#fff;white-space:nowrap}'
        '.chip.MUR{background:var(--mur)}.chip.UR{background:var(--ur)}.chip.SAR{background:var(--sar)}'
        '.chip.AR{background:var(--ar)}.chip.SR{background:var(--sr)}.chip.ex{background:var(--ex)}'
        '.num{font-size:10.5px;color:var(--faint);font-variant-numeric:tabular-nums}'
        '.cname{font-size:13px;font-weight:700;line-height:1.25;min-height:2.4em}'
        '.price{font-size:15.5px;font-weight:800;font-variant-numeric:tabular-nums}.price.top{color:var(--gold)}'
        '.cmp{font-size:11px;color:var(--faint)}'
        '.chip.sm{font-size:9.5px;padding:0 5px}'
        '.full{border-top:1px solid var(--line);padding:2px 20px 14px}'
        '.full-hd{font-size:12.5px;font-weight:700;color:var(--muted);padding:11px 0 3px}'
        '.rgrp{border-bottom:1px solid var(--line)}.rgrp:last-child{border-bottom:0}'
        '.rgrp>summary{list-style:none;padding:9px 2px;font-size:13px;font-weight:700;color:var(--text);cursor:pointer;user-select:none;display:flex;align-items:center;gap:9px}'
        '.rgrp>summary::-webkit-details-marker{display:none}.rgrp>summary:hover{color:var(--sar)}'
        '.rgrp-n{color:var(--faint);font-weight:600;font-size:12px}'
        '.rgrp-top{margin-left:auto;color:var(--faint);font-weight:600;font-size:12px}'
        '.tblwrap{overflow-x:auto;padding:0 0 10px}'
        'th.sortable{cursor:pointer;user-select:none;white-space:nowrap}th.sortable:hover{color:var(--text)}'
        'th.sorted{color:var(--sar)}th.sorted[data-dir="down"]::after{content:" ▾"}'
        'th.sorted[data-dir="up"]::after{content:" ▴"}.osort .odir{background:var(--surface);border-color:var(--own);color:var(--own)}'
        'table{width:100%;border-collapse:collapse;font-size:12.5px}'
        'th{text-align:left;color:var(--faint);font-weight:600;padding:6px 8px;border-bottom:1px solid var(--border);font-size:11px;text-transform:uppercase}'
        'td{padding:6px 8px;border-bottom:1px solid var(--line)}'
        'td a{color:inherit;text-decoration:none}td a:hover{color:var(--sar)}'
        '.tn,.tp,.tj{font-variant-numeric:tabular-nums}.tp{font-weight:700}.tj{color:var(--faint)}'
        'td{vertical-align:middle}.cardcell{display:flex;align-items:center;gap:10px}'
        '.tth{width:40px;height:56px;object-fit:cover;border-radius:5px;background:var(--line);flex:0 0 auto}'
        '.tth.noimg{display:inline-flex;align-items:center;justify-content:center;font-size:18px;opacity:.5}'
        '.cc-txt{display:flex;align-items:center;gap:7px;flex-wrap:wrap;min-width:0}'
        '.note{margin-top:24px;background:var(--surface);border:1px solid var(--border);border-radius:11px;padding:13px 16px;font-size:13px;color:var(--muted)}.note b{color:var(--text)}'
        'footer{margin-top:22px;color:var(--faint);font-size:12.5px}')

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

_TABS_CSS = ('.wrap{max-width:1240px;margin:0 auto;padding:36px 24px 72px;display:flex;gap:34px;align-items:flex-start}'
             '.sidebar{position:sticky;top:22px;width:214px;flex:0 0 214px}'
             '.sidebar .brand{margin:0 0 20px}'
             '.sidebar .brand h1{font-size:21px;line-height:1.15;margin:0 0 6px;letter-spacing:-.02em;font-weight:800}'
             '.sidebar .brand .sub{font-size:12px;color:var(--muted);margin:0;max-width:none;line-height:1.5}'
             '.search{width:100%;margin:0 0 14px;padding:8px 11px;font:inherit;font-size:13px;color:var(--text);background:var(--surface);border:1px solid var(--border);border-radius:9px;outline:none}'
             '.search:focus{border-color:var(--sar)}.search::placeholder{color:var(--faint)}'
             '.no-res{padding:22px 2px;color:var(--faint);font-size:13.5px}'
             '.filters{display:flex;flex-wrap:wrap;gap:5px;margin:0 0 14px}'
             '.chip{font:inherit;font-size:11.5px;font-weight:700;color:var(--muted);background:var(--surface-2);border:1px solid var(--border);border-radius:999px;padding:4px 10px;cursor:pointer}'
             '.chip:hover{color:var(--text)}.chip.on{background:var(--sar);color:#fff;border-color:var(--sar)}'
             '.wish{border:0;background:transparent;color:var(--faint);font-size:15px;line-height:1;cursor:pointer;flex:0 0 auto;padding:0 1px}'
             '.wish:hover{color:var(--gold)}.wish.on{color:var(--gold)}'
             '.pk{display:none;font-size:10.5px;color:var(--faint);font-weight:600;background:var(--surface-2);border:1px solid var(--border);border-radius:5px;padding:1px 6px;margin-left:5px;white-space:nowrap}'
             '.content.qmode .pk,#owned-panel .pk{display:inline-block}'
             '.pack-prog{flex-basis:100%;display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted);font-weight:600;margin-top:6px}'
             '.pbar{display:inline-block;width:130px;height:7px;border-radius:4px;background:var(--surface);overflow:hidden;flex:0 0 auto;border:1px solid var(--border)}'
             '.pbar i{display:block;height:100%;background:var(--own)}'
             '.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));gap:10px;margin:8px 0 16px}'
             '.st{background:var(--surface-2);border:1px solid var(--border);border-radius:10px;padding:10px 12px;text-align:center}'
             '.st b{display:block;font-size:16px;font-weight:800}.st span{font-size:11px;color:var(--muted)}'
             '.backup{margin:18px 0 8px;padding:14px;background:var(--surface-2);border:1px solid var(--border);border-radius:11px}'
             '.backup>b{font-size:13px}'
             '.bkrow{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:10px 0 0}'
             '.bkrow button{font:inherit;font-size:12px;font-weight:700;color:var(--text);background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:6px 11px;cursor:pointer}'
             '.bkrow button:hover{border-color:var(--own)}.bkmsg{font-size:12px;color:var(--own);font-weight:700}'
             '.bkpaste{margin-top:8px;display:flex;gap:6px}'
             '.bkpaste textarea{flex:1;height:54px;font:inherit;font-size:11px;padding:7px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text);resize:vertical}'
             '.bkpaste button{align-self:flex-start;font:inherit;font-size:12px;font-weight:700;padding:6px 11px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text);cursor:pointer}'
             '.bknote{font-size:11px;margin:10px 0 0;line-height:1.6}'
             '.bkbar{display:flex;gap:6px;margin-top:14px}'
             '.bkbar button{flex:1;font:inherit;font-size:12px;font-weight:700;color:var(--text);background:var(--surface-2);border:1px solid var(--border);border-radius:9px;padding:8px 6px;cursor:pointer}'
             '.bkbar button:hover{border-color:var(--own);color:var(--own)}'
             '.toast{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:120;background:var(--text);color:var(--bg);font-size:13px;font-weight:700;padding:10px 18px;border-radius:999px;box-shadow:0 8px 30px rgba(0,0,0,.35)}'
             '.toast[hidden]{display:none}'
             '.osort{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:0 0 14px}'
             '.osort>span{font-size:11.5px;color:var(--faint);font-weight:700;margin-right:2px}'
             '.osort button{font:inherit;font-size:12px;font-weight:700;color:var(--muted);background:var(--surface-2);border:1px solid var(--border);border-radius:999px;padding:5px 11px;cursor:pointer}'
             '.osort button:hover{color:var(--text)}.osort button.on{background:var(--sar);color:#fff;border-color:var(--sar)}'
             '.oview{display:flex;gap:6px;margin:0 0 12px}'
             '.oview button{font:inherit;font-size:12px;font-weight:700;color:var(--muted);background:var(--surface-2);border:1px solid var(--border);border-radius:999px;padding:5px 12px;cursor:pointer}'
             '.oview button:hover{color:var(--text)}.oview button.on{background:var(--own);color:#fff;border-color:var(--own)}'
             '.agrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:14px;padding:4px 0 2px}'
             '.acard{background:var(--surface-2);border:1px solid var(--border);border-radius:12px;overflow:hidden;display:flex;flex-direction:column;box-shadow:var(--shadow)}'
             '.ath{width:100%;aspect-ratio:5/7;object-fit:cover;display:block;background:var(--line);cursor:zoom-in}'
             '.ath.noimg{display:flex;align-items:center;justify-content:center;font-size:34px;opacity:.5}'
             '.ainfo{padding:8px 10px 10px;display:flex;flex-direction:column;gap:3px}'
             '.atop{display:flex;align-items:center;justify-content:space-between;gap:6px}'
             '.aq{font-size:12px;font-weight:800;color:var(--own)}'
             '.aname{font-size:12.5px;font-weight:700;line-height:1.25;min-height:2.4em}'
             '.aname a{color:inherit;text-decoration:none}.aname a:hover{color:var(--sar)}'
             '.aprice{font-size:13.5px;font-weight:800;font-variant-numeric:tabular-nums}'
             '.anum{font-size:10.5px;color:var(--faint);font-weight:600;margin-left:5px}'
             '.tth{cursor:zoom-in}'
             '.lb{position:fixed;inset:0;background:rgba(0,0,0,.82);display:flex;align-items:center;justify-content:center;z-index:100;padding:24px;cursor:zoom-out}'
             '.lb[hidden]{display:none}'
             '.lb img{width:min(90vw,380px);height:auto;max-height:92vh;border-radius:12px;box-shadow:0 12px 48px rgba(0,0,0,.6)}'
             '.tablist{display:flex;flex-direction:column;gap:2px}'
             '.tablist button{font:inherit;font-size:13.5px;font-weight:600;color:var(--muted);text-align:left;'
             'background:transparent;border:0;border-radius:9px;padding:8px 12px;cursor:pointer;width:100%;'
             'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:background .12s,color .12s}'
             '.tablist button:hover{background:var(--surface-2);color:var(--text)}'
             '.tablist button.active{background:var(--sar);color:#fff;font-weight:700}'
             '.tablist button.deal{color:var(--gold)}'
             '.tablist button.deal.active{background:var(--gold);color:#1c1e26}'
             '.tablist .sep{height:1px;background:var(--border);margin:8px 6px}'
             '.content{flex:1;min-width:0}.content section.pack{margin-top:0}'
             'section.pack[hidden],#deals-panel[hidden],#owned-panel[hidden]{display:none!important}'
             '.tablist button.own{color:var(--own)}.tablist button.own.active{background:var(--own);color:#fff}'
             '.qty{display:inline-flex;align-items:center;flex:0 0 auto;border:1px solid var(--border);border-radius:7px;background:var(--surface);overflow:hidden}'
             '.qty button{border:0;background:transparent;color:var(--muted);font-size:14px;font-weight:800;width:22px;height:24px;cursor:pointer;line-height:1;padding:0}'
             '.qty button:hover{background:var(--surface-2);color:var(--text)}'
             '.qty .qn{min-width:17px;text-align:center;font-size:12.5px;font-weight:800;font-variant-numeric:tabular-nums}'
             '.qty.has{border-color:var(--own)}.qty.has .qn{color:var(--own)}'
             '.xq{font-weight:800;color:var(--own);font-size:12.5px;flex:0 0 auto}'
             '.rtag{font-weight:800;font-size:11px;flex:0 0 auto}'
             '.rtag.MUR{color:var(--mur)}.rtag.UR{color:var(--ur)}.rtag.SAR{color:var(--sar)}.rtag.AR{color:var(--ar)}.rtag.SR{color:var(--sr)}.rtag.ex{color:var(--ex)}'
             '.own-cnt{color:var(--own);font-weight:700}.rgrp-own{color:var(--own);font-weight:700;font-size:12px}'
             '.own-total{color:var(--own);font-weight:800;font-size:12.5px;margin:9px 0 0}'
             '#owned-panel h2{margin:0 0 2px}#owned-panel .sub2{color:var(--muted);font-size:13px;margin:0 0 16px}'
             '#owned-panel .dim{color:var(--faint)}.owned-grp{margin:0 0 16px}'
             '.owned-h{font-size:13.5px;font-weight:800;padding:9px 2px 7px;border-bottom:1px solid var(--line)}'
             '@media(max-width:860px){.wrap{flex-direction:column;gap:14px;padding:24px 16px 60px}'
             '.sidebar{position:static;width:auto;flex:none}.sidebar .brand{margin-bottom:12px}'
             '.tablist{flex-direction:row;flex-wrap:wrap;gap:6px}'
             '.tablist button{width:auto;background:var(--surface-2);border:1px solid var(--border);'
             'border-radius:999px;padding:6px 12px;font-size:12.5px;font-weight:700}.tablist .sep{display:none}}'
             '#deals-panel{margin:2px 0 24px}#deals-panel h2{margin:0 0 2px}'
             '#deals-panel .sub2{color:var(--muted);font-size:12.5px;margin:0 0 14px;line-height:1.6}'
             '#deals-panel .tblwrap{overflow-x:auto}'
             '#deals-panel table{width:100%;border-collapse:collapse;font-size:13px;min-width:560px}'
             '#deals-panel th,#deals-panel td{padding:9px 11px;border-bottom:1px solid var(--line);'
             'text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}'
             '#deals-panel th{color:var(--faint);font-weight:700;font-size:10.5px;text-transform:uppercase}'
             '#deals-panel td.name,#deals-panel th.name{text-align:left;font-weight:800}'
             '#deals-panel td.top,#deals-panel th.top{text-align:left;color:var(--muted);font-weight:600;white-space:normal}'
             '#deals-panel tr.under td{background:color-mix(in srgb,var(--own) 13%,transparent)}'
             '#deals-panel .ratio{font-weight:800;color:var(--gold)}#deals-panel .dim{color:var(--faint)}'
             '#deals-panel .badge{display:inline-block;font-size:10px;font-weight:800;padding:2px 7px;'
             'border-radius:6px;background:var(--own);color:#fff;margin-left:6px}'
             '#deals-panel .note2{color:var(--faint);font-size:11.5px;margin-top:14px;line-height:1.7}')

_TABS_JS = '''(function(){
 const won=n=>n==null?"—":"₩"+n.toLocaleString();
 const numOf=s=>{const d=(s||"").replace(/[^0-9]/g,"");return d?+d:-1;};
 const DBKEY="pkm_db";
 let DB;try{DB=JSON.parse(localStorage.getItem(DBKEY)||"null");}catch(e){DB=null;}
 if(!DB||typeof DB!=="object"){DB={qty:{},wish:{}};try{const oq=JSON.parse(localStorage.getItem("pkm_qty")||"null");if(oq&&typeof oq==="object")DB.qty=oq;else{const oo=JSON.parse(localStorage.getItem("pkm_owned")||"[]");if(Array.isArray(oo))oo.forEach(id=>{DB.qty[id]=1;});}}catch(e){}}
 DB.qty=DB.qty||{};DB.wish=DB.wish||{};
 const saveDB=()=>{try{localStorage.setItem(DBKEY,JSON.stringify(DB));}catch(e){}};
 const qOf=el=>DB.qty[el.dataset.id]||0;
 function renderDeals(){
  const rows=DEALS.rows.map(r=>{
   const price=r.price==null?'<span class="dim">품절/왜곡</span>':won(r.price);
   const ratio=r.ratio==null?'<span class="dim">—</span>':'<span class="ratio">'+r.ratio+'x</span>';
   const badge=r.under?'<span class="badge">정가이하</span>':'';
   const note=r.note?'<div class="dim" style="font-size:11px;margin-top:3px">⚠️ '+r.note+'</div>':'';
   return '<tr class="'+(r.under?'under':'')+'"><td class="name">'+r.pack+badge+'</td><td>'+won(r.list)+'</td><td>'+price+'</td><td>'+(r.malls||'—')+'</td><td>'+ratio+'</td><td class="top">'+r.top+note+'</td></tr>';
  }).join('');
  return '<h2>💰 매물 · 고점대비 가성비</h2><p class="sub2">감시기 <b>다나와 실구매가</b>(배송포함, 쿠팡 품절유령 제외) · <b>'+DEALS.updated+'</b><br><b>배수</b> = 고점카드 천장 ÷ 박스가(확률 미반영). <b>초록=정가 이하 구매 가능</b>.</p><div class="tblwrap"><table><thead><tr><th class="name">팩</th><th>정가</th><th>현재 실구매가</th><th>판매처</th><th>배수</th><th class="top">고점 천장 카드</th></tr></thead><tbody>'+rows+'</tbody></table></div>';
 }
 const wrap=document.querySelector('.wrap');
 const packs=[...wrap.querySelectorAll('section.pack')];
 if(!packs.length)return;
 const header=wrap.querySelector('header.top');
 const note=wrap.querySelector('.note');
 const footer=wrap.querySelector('footer');
 const dp=document.createElement('div');dp.id='deals-panel';dp.innerHTML=renderDeals();
 const opn=document.createElement('div');opn.id='owned-panel';
 const side=document.createElement('aside');side.className='sidebar';
 const brand=document.createElement('div');brand.className='brand';
 brand.innerHTML=header?header.innerHTML:'<h1>내 포켓몬 카드 시세판</h1>';
 const nav=document.createElement('nav');nav.className='tablist';
 const search=document.createElement('input');search.type='search';search.className='search';search.placeholder='🔍 카드 검색 (이름·번호)';
 const filters=document.createElement('div');filters.className='filters';
 const FIL=[['all','전체'],['own','보유'],['miss','미보유'],['dupe','여분2+'],['wish','★위시']];
 const chips={};let filterMode='all';
 FIL.forEach(([k,lbl])=>{const c=document.createElement('button');c.className='chip'+(k==='all'?' on':'');c.textContent=lbl;c.onclick=()=>{filterMode=k;refresh();};filters.appendChild(c);chips[k]=c;});
 const toastEl=document.createElement('div');toastEl.className='toast';toastEl.hidden=true;document.body.appendChild(toastEl);
 let toastT;function toast(m){toastEl.textContent=m;toastEl.hidden=false;clearTimeout(toastT);toastT=setTimeout(()=>{toastEl.hidden=true;},1800);}
 function exportDB(){const blob=new Blob([JSON.stringify(DB)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);const d=new Date();a.download='pokemon-collection-'+d.getFullYear()+('0'+(d.getMonth()+1)).slice(-2)+('0'+d.getDate()).slice(-2)+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);toast('💾 백업 저장됨');}
 const bkbar=document.createElement('div');bkbar.className='bkbar';
 const saveBtn=document.createElement('button');saveBtn.textContent='💾 저장';saveBtn.title='컬렉션을 파일로 다운로드';saveBtn.onclick=exportDB;
 const loadBtn=document.createElement('button');loadBtn.textContent='📂 불러오기';loadBtn.title='백업 파일 업로드(병합)';
 const fileIn=document.createElement('input');fileIn.type='file';fileIn.accept='application/json';fileIn.hidden=true;
 loadBtn.onclick=()=>fileIn.click();
 fileIn.onchange=e=>{const f=e.target.files[0];if(!f)return;const rd=new FileReader();rd.onload=()=>{try{if(mergeIn(JSON.parse(rd.result))){syncUI();if(!opn.hidden)renderOwned();toast('📂 불러옴(병합)');}}catch(err){toast('파일 오류');}fileIn.value='';};rd.readAsText(f);};
 bkbar.appendChild(saveBtn);bkbar.appendChild(loadBtn);bkbar.appendChild(fileIn);
 side.appendChild(brand);side.appendChild(search);side.appendChild(filters);side.appendChild(nav);side.appendChild(bkbar);
 const content=document.createElement('main');content.className='content';
 content.appendChild(dp);content.appendChild(opn);
 packs.forEach(p=>content.appendChild(p));
 if(note)content.appendChild(note);
 if(footer)content.appendChild(footer);
 wrap.innerHTML='';wrap.appendChild(side);wrap.appendChild(content);
 const noRes=document.createElement('p');noRes.className='no-res';noRes.textContent='해당하는 카드가 없습니다.';noRes.hidden=true;content.appendChild(noRes);
 let searchQ='',curTab=2,ownedSort='kr',ownedView='album',ownedDir=-1;const btns=[];
 const pct=(a,b)=>b?Math.round(a/b*100):0;
 const RANK={MUR:0,HR:0,UR:1,SAR:2,SR:3,AR:4,RR:5,R:6,ACE:7,U:8,C:9};
 const rrank=tr=>{const t=tr.querySelector('.rtag');const r=t?t.textContent.replace(/[\\[\\]]/g,'').trim():'';return RANK[r]==null?10:RANK[r];};
 const cellNum=(tr,sel)=>{const c=tr.querySelector(sel);return c?(parseInt(c.textContent.replace(/[^0-9]/g,''))||0):0;};
 const cardName=tr=>{const a=tr.querySelector('.cc-txt a');return a?a.textContent.trim():'';};
 const cardNum=tr=>parseInt(((tr.querySelector('.tn')||{textContent:''}).textContent||'').trim())||0;
 function sortItems(items){items.sort((ea,eb)=>{const a=ea.closest('tr'),b=eb.closest('tr');let ka,kb;
  if(ownedSort==='rarity'){ka=rrank(a);kb=rrank(b);}
  else if(ownedSort==='name'){ka=cardName(a);kb=cardName(b);}
  else if(ownedSort==='num'){ka=cardNum(a);kb=cardNum(b);}
  else if(ownedSort==='jp'){ka=cellNum(a,'.tj');kb=cellNum(b,'.tj');}
  else{ka=cellNum(a,'.tp');kb=cellNum(b,'.tp');}
  return (typeof ka==='string'?ka.localeCompare(kb,'ko'):ka-kb)*ownedDir;});}
 function ownedHead(){return '<tr>'+[['num','번호'],['name','카드'],['kr','🇰🇷한국'],['jp','🇯🇵일본']].map(x=>{const on=ownedSort===x[0];return '<th class="sortable'+(on?' sorted':'')+'" data-k="'+x[0]+'"'+(on?' data-dir="'+(ownedDir>0?'up':'down')+'"':'')+'>'+x[1]+'</th>';}).join('')+'</tr>';}
 function packStat(sec){
  const base=parseInt(sec.dataset.base)||0;const seen=new Set();let cards=0,val=0,dupes=0,uniq=0,topKr=0,topName='';
  sec.querySelectorAll('tbody tr').forEach(tr=>{const el=tr.querySelector('.qty');if(!el)return;const q=DB.qty[el.dataset.id]||0;if(q>0){cards+=q;uniq++;const kr=+el.dataset.kr||0;val+=q*kr;if(q>=2)dupes++;if(kr>topKr){topKr=kr;const a=tr.querySelector('.cc-txt a');topName=a?a.textContent:'';}const t=tr.querySelector('.tn');const n=t?parseInt(t.textContent):NaN;if(!isNaN(n)&&base&&n<=base)seen.add(n);}});
  return {base,ownedBase:seen.size,cards,uniq,val,dupes,topKr,topName};
 }
 function updateCounts(){
  let total=0,val=0;const wishN=Object.keys(DB.wish).length;
  packs.forEach(sec=>{const st=packStat(sec);total+=st.cards;val+=st.val;
   const e=sec.querySelector('.own-cnt');if(e)e.textContent=st.cards?(' · 보유 '+st.cards+'장'):'';
   const pg=sec.querySelector('.pack-prog');if(pg)pg.innerHTML=st.base?('<span class="pbar"><i style="width:'+pct(st.ownedBase,st.base)+'%"></i></span> 정규 '+st.ownedBase+'/'+st.base+' ('+pct(st.ownedBase,st.base)+'%)'):'';
   sec.querySelectorAll('.rgrp').forEach(gr=>{let gn=0;gr.querySelectorAll('.qty').forEach(el=>{gn+=DB.qty[el.dataset.id]||0;});const s=gr.querySelector('.rgrp-own');if(s)s.textContent=gn?('보유 '+gn):'';});
  });
  const t=brand.querySelector('.own-total');if(t)t.textContent=(total||wishN)?('🎴 보유 '+total+'장 · 추정 '+won(val)+(wishN?(' · ★'+wishN):'')):'';
  chips['wish'].textContent='★위시'+(wishN?(' '+wishN):'');
 }
 function rowVisible(tr){const el=tr.querySelector('.qty');const id=el?el.dataset.id:'';const q=DB.qty[id]||0;const w=!!DB.wish[id];
  if(filterMode==='own'&&!(q>0))return false;if(filterMode==='miss'&&!(q<=0))return false;if(filterMode==='dupe'&&!(q>=2))return false;if(filterMode==='wish'&&!w)return false;
  if(searchQ&&tr.textContent.toLowerCase().indexOf(searchQ)<0)return false;return true;}
 function syncChips(){FIL.forEach(([k])=>chips[k].classList.toggle('on',k===filterMode));}
 function refresh(){
  const query=!!searchQ||filterMode!=='all';
  if(query){
   content.classList.add('qmode');
   dp.hidden=true;opn.hidden=true;btns.forEach(b=>b.classList.remove('active'));
   let any=false;
   packs.forEach(sec=>{let ph=false;sec.querySelectorAll('.rgrp').forEach(gr=>{let gh=false;gr.querySelectorAll('tbody tr').forEach(tr=>{const v=rowVisible(tr);tr.style.display=v?'':'none';if(v)gh=true;});gr.style.display=gh?'':'none';gr.open=gh;if(gh)ph=true;});sec.hidden=!ph;if(ph)any=true;});
   noRes.hidden=any;
  }else{
   content.classList.remove('qmode');
   packs.forEach(sec=>{sec.querySelectorAll('tbody tr').forEach(tr=>tr.style.display='');sec.querySelectorAll('.rgrp').forEach((gr,i)=>{gr.style.display='';gr.open=(i===0);});});
   noRes.hidden=true;dp.hidden=(curTab!==0);opn.hidden=(curTab!==1);packs.forEach((p,j)=>p.hidden=(curTab!==j+2));btns.forEach((b,j)=>b.classList.toggle('active',j===curTab));if(curTab===1)renderOwned();
  }
  syncChips();
 }
 function select(i){searchQ='';search.value='';filterMode='all';curTab=i;refresh();try{localStorage.setItem('pkm_tab',i)}catch(e){}}
 search.addEventListener('input',()=>{searchQ=search.value.trim().toLowerCase();refresh();});
 function setQ(el,q){q=Math.max(0,q|0);const id=el.dataset.id;if(q)DB.qty[id]=q;else delete DB.qty[id];el.querySelector('.qn').textContent=q;el.classList.toggle('has',q>0);saveDB();updateCounts();if(!opn.hidden)renderOwned();if(filterMode!=='all')refresh();}
 document.querySelectorAll('.qty').forEach(el=>{const q0=qOf(el);el.querySelector('.qn').textContent=q0;el.classList.toggle('has',q0>0);el.querySelector('.qm').addEventListener('click',()=>setQ(el,qOf(el)-1));el.querySelector('.qp').addEventListener('click',()=>setQ(el,qOf(el)+1));});
 document.querySelectorAll('.wish').forEach(b=>{const id=b.dataset.id;if(DB.wish[id])b.classList.add('on');b.addEventListener('click',()=>{if(DB.wish[id]){delete DB.wish[id];b.classList.remove('on');}else{DB.wish[id]=1;b.classList.add('on');}saveDB();updateCounts();if(filterMode==='wish')refresh();});});
 function bkMsg(m){const s=opn.querySelector('.bkmsg');if(s){s.textContent=m;setTimeout(()=>{if(s)s.textContent='';},2500);}}
 function syncUI(){updateCounts();document.querySelectorAll('.qty').forEach(el=>{const v=DB.qty[el.dataset.id]||0;el.querySelector('.qn').textContent=v;el.classList.toggle('has',v>0);});document.querySelectorAll('.wish').forEach(b=>b.classList.toggle('on',!!DB.wish[b.dataset.id]));}
 function mergeIn(obj){if(!obj||typeof obj!=='object')return false;const q=obj.qty||{},w=obj.wish||{};Object.keys(q).forEach(id=>{const v=Math.max(DB.qty[id]||0,+q[id]||0);if(v)DB.qty[id]=v;});Object.keys(w).forEach(id=>{if(w[id])DB.wish[id]=1;});saveDB();return true;}
 function renderOwned(){
  opn.innerHTML='';
  let total=0,val=0,uniq=0,dupes=0,ownedBase=0,base=0,topKr=0,topName='';const blocks=[];
  packs.forEach(sec=>{const st=packStat(sec);total+=st.cards;val+=st.val;uniq+=st.uniq;dupes+=st.dupes;ownedBase+=st.ownedBase;base+=st.base;if(st.topKr>topKr){topKr=st.topKr;topName=st.topName;}
   const items=[...sec.querySelectorAll('.qty')].filter(el=>(DB.qty[el.dataset.id]||0)>0);
   if(!items.length)return;
   sortItems(items);
   const pack=(sec.querySelector('h2')||{textContent:''}).textContent.trim();
   let sub=0,cnt=0;const alb=ownedView==='album';
   const body=alb?document.createElement('div'):document.createElement('tbody');if(alb)body.className='agrid';
   items.forEach(el=>{const tr=el.closest('tr');if(!tr)return;const q=DB.qty[el.dataset.id]||0,kr=+el.dataset.kr||0;sub+=q*kr;cnt+=q;
    if(alb){const img=tr.querySelector('img.tth');const src=img?img.getAttribute('src'):'';const na=tr.querySelector('.cc-txt a');const name=na?na.textContent:'';const link=na?na.getAttribute('href'):'#';const rtag=tr.querySelector('.rtag');const rt=rtag?rtag.outerHTML:'';const pr=tr.querySelector('.tp');const prt=pr?pr.textContent:'';const nm=tr.querySelector('.tn');const numt=nm?nm.textContent:'';const tile=document.createElement('div');tile.className='acard';tile.innerHTML=(src?'<img class="ath" src="'+src+'" alt=""/>':'<div class="ath noimg">🎴</div>')+'<div class="ainfo"><div class="atop">'+rt+'<span class="aq">×'+q+'</span></div><div class="aname"><a href="'+link+'" target="_blank" rel="noopener">'+name+'</a></div><div class="aprice">'+prt+'<span class="anum">'+numt+'</span></div></div>';body.appendChild(tile);}
    else{const c=tr.cloneNode(true);const qc=c.querySelector('.qty');if(qc){const s=document.createElement('span');s.className='xq';s.textContent='×'+q;qc.replaceWith(s);}const wb=c.querySelector('.wish');if(wb)wb.remove();body.appendChild(c);}
   });
   const d=document.createElement('div');d.className='owned-grp';d.innerHTML='<div class="owned-h">'+pack+' <span class="dim">'+cnt+'장 · '+won(sub)+'</span></div>';
   if(alb){d.appendChild(body);}else{const tbl=document.createElement('table');const thd=document.createElement('thead');thd.innerHTML=ownedHead();tbl.appendChild(thd);tbl.appendChild(body);const w=document.createElement('div');w.className='tblwrap';w.appendChild(tbl);d.appendChild(w);}
   blocks.push(d);
  });
  const wishN=Object.keys(DB.wish).length;const head=document.createElement('div');
  head.innerHTML='<h2>💼 내 보유카드</h2>'
   +'<div class="stats"><div class="st"><b>'+total+'</b><span>총 장수</span></div>'
   +'<div class="st"><b>'+uniq+'</b><span>고유 종수</span></div>'
   +'<div class="st"><b>'+won(val)+'</b><span>추정 가치</span></div>'
   +'<div class="st"><b>'+ownedBase+'/'+base+'</b><span>정규 완성 '+pct(ownedBase,base)+'%</span></div>'
   +'<div class="st"><b>'+dupes+'</b><span>여분 종(2+)</span></div>'
   +'<div class="st"><b>'+wishN+'</b><span>★ 위시</span></div></div>'
   +(topName?'<p class="sub2">최고가 보유: <b>'+topName+'</b> '+won(topKr)+'</p>':'')
   +'<div class="backup"><b>💾 백업 코드</b> <span class="dim">— 컬렉션을 글자로 복사해 다른 기기·브라우저에 붙여넣어 옮기기 (파일 저장/불러오기는 ← 사이드바)</span>'
   +'<div class="bkrow"><button id="bkCopy">📋 코드 복사</button><button id="bkPaste">📥 붙여넣기</button><span class="bkmsg"></span></div>'
   +'<div class="bkpaste" hidden><textarea placeholder="복사한 코드를 붙여넣고 적용"></textarea><button id="bkApply">적용</button></div></div>'
   +'<div class="oview"><button data-v="album">🖼 도감</button><button data-v="list">☰ 목록</button></div>'
   +'<div class="osort"><span>정렬</span><button data-s="kr">💰 금액</button><button data-s="rarity">⭐ 등급</button><button data-s="jp">🇯🇵 일본가</button><button class="odir" id="odir">⬇ 내림</button><span class="dim" style="font-size:11px">· 목록뷰는 표 머리글 클릭</span></div>';
  opn.appendChild(head);
  if(!total){const e=document.createElement('p');e.className='dim';e.style.padding='6px 2px 14px';e.textContent='보유 카드가 없습니다. 각 팩에서 + 로 수량을 올리세요.';opn.appendChild(e);}
  blocks.forEach(b=>opn.appendChild(b));
  const Q=s=>opn.querySelector(s);
  Q('#bkCopy').onclick=()=>{const s=JSON.stringify(DB);(navigator.clipboard?navigator.clipboard.writeText(s):Promise.reject()).then(()=>bkMsg('코드 복사됨')).catch(()=>{const p=Q('.bkpaste');p.hidden=false;p.querySelector('textarea').value=s;bkMsg('아래 코드를 복사하세요');});};
  Q('#bkPaste').onclick=()=>{const p=Q('.bkpaste');p.hidden=!p.hidden;};
  Q('#bkApply').onclick=()=>{try{if(mergeIn(JSON.parse(Q('.bkpaste textarea').value))){syncUI();renderOwned();bkMsg('적용됨');}}catch(e){bkMsg('코드 오류');}};
  opn.querySelectorAll('.osort button[data-s]').forEach(b=>{b.classList.toggle('on',b.dataset.s===ownedSort);b.onclick=()=>{if(ownedSort===b.dataset.s)ownedDir=-ownedDir;else{ownedSort=b.dataset.s;ownedDir=(b.dataset.s==='name'?1:-1);}renderOwned();};});
  const od=opn.querySelector('#odir');if(od){od.textContent=ownedDir>0?'⬆ 오름':'⬇ 내림';od.onclick=()=>{ownedDir=-ownedDir;renderOwned();};}
  opn.querySelectorAll('.owned-grp thead th[data-k]').forEach(t=>{t.onclick=()=>{const k=t.dataset.k;if(ownedSort===k)ownedDir=-ownedDir;else{ownedSort=k;ownedDir=(k==='name'?1:-1);}renderOwned();};});
  opn.querySelectorAll('.oview button').forEach(b=>{b.classList.toggle('on',b.dataset.v===ownedView);b.onclick=()=>{ownedView=b.dataset.v;renderOwned();};});
 }
 function addBtn(label,cls,onclick){const b=document.createElement('button');b.textContent=label;if(cls)b.className=cls;b.title=label;b.onclick=onclick;nav.appendChild(b);btns.push(b);return b;}
 addBtn('💰 매물·가성비','deal',()=>select(0));
 addBtn('💼 내 보유카드','own',()=>select(1));
 const sep=document.createElement('div');sep.className='sep';nav.appendChild(sep);
 packs.forEach((p,j)=>{const nm=(p.querySelector('h2')||{}).textContent||('팩'+(j+1));const bs=p.dataset.base;addBtn(nm.trim()+(bs&&bs!=='?'?(' ['+bs+']'):''),'',()=>select(j+2));});
 updateCounts();
 let start=2;try{const s=parseInt(localStorage.getItem('pkm_tab'));if(!isNaN(s)&&s>=0&&s<packs.length+2)start=s;}catch(e){}
 curTab=start;refresh();
 const lb=document.createElement('div');lb.className='lb';lb.hidden=true;lb.innerHTML='<img alt=""/>';document.body.appendChild(lb);
 const lbimg=lb.querySelector('img');
 lb.addEventListener('click',()=>{lb.hidden=true;lbimg.removeAttribute('src');});
 content.addEventListener('click',e=>{const im=e.target.closest('img.tth,img.ath');if(!im)return;lbimg.src=im.src;lb.hidden=false;});
 const colKey=(tr,i)=>{if(i===1){const a=tr.querySelector('.cc-txt a');return a?a.textContent.trim():'';}if(i===0)return parseInt((tr.children[0].textContent||'').trim())||0;return numOf(tr.children[i].textContent);};
 document.querySelectorAll(".full table").forEach(tb=>{
  const tbody=tb.querySelector("tbody"),ths=tb.querySelectorAll("th");
  const rws=[...tbody.querySelectorAll("tr")];let last={i:null,dir:-1};
  function sort(i){const dir=last.i===i?-last.dir:(i===1?1:-1);last={i,dir};rws.sort((a,b)=>{const ka=colKey(a,i),kb=colKey(b,i);return (typeof ka==='string'?ka.localeCompare(kb,'ko'):ka-kb)*dir;});rws.forEach(r=>tbody.appendChild(r));ths.forEach((t,j)=>{const on=j===i;t.classList.toggle("sorted",on);t.dataset.dir=on?(dir>0?"up":"down"):"";});}
  ths.forEach((t,i)=>{t.classList.add("sortable");t.title="클릭: 정렬(재클릭=방향)";t.addEventListener("click",()=>sort(i));});
 });
})();'''


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
