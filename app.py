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
    ("스톰에메랄다", "스톰에메랄다", True), ("초전브레이커", "초전브레이커", False),
    ("블랙볼트", "블랙볼트", False), ("화이트플레어", "화이트플레어", False),
    ("낙원드래고나", "낙원드래고나", False), ("포켓몬 카드 151", "포켓몬카드 151", False),
]
MIN_KR, TOPN = 3000, 15
RCLASS = {"MUR": "MUR", "HR": "MUR", "SAR": "SAR", "UR": "UR",
          "SR": "SR", "AR": "AR", "RR": "ex", "R": "ex"}
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


def build():
    secs = []
    for disp, query, owned in PACKS:
        try:
            rows = [g for g in pull(query) if g["kr"] >= MIN_KR]
        except Exception:
            rows = []
        total = len(rows)
        rows = rows[:TOPN]
        if not rows:
            continue
        own = '<span class="own-badge">보유</span>' if owned else ""
        meta = f"밸류 {total}장 · 최고 🇰🇷 ₩{rows[0]['kr']:,}"
        body = "".join(card_html(g) for g in rows)
        secs.append(f'<section class="pack"><div class="pack-head"><h2>'
                    f'{H.escape(disp)}</h2>{own}<span class="pack-meta">{meta}'
                    f'</span></div><div class="grid">{body}</div></section>')
    upd = time.strftime("%Y-%m-%d %H:%M", time.localtime())
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"/>'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"/>'
            f'<title>내 포켓몬 카드 시세판</title><style>{_CSS}</style></head><body>'
            f'<div class="wrap">{_HEADER}{"".join(secs)}'
            f'<div class="note"><b>다중소스.</b> 콜렉토리 한국 실거래 기준(🇯🇵 일본 비교). '
            f'1시간마다 갱신 · 갱신 {upd}. 시세는 변동됩니다.</div>'
            f'<footer>출처: collectory.cc · Daniel 개인 참고용.</footer></div></body></html>')


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


_HEADER = ('<header class="top"><p class="eyebrow">Pokémon TCG · 팩별 밸류카드 · 한국 실거래'
           '</p><h1>내 포켓몬 카드 시세판</h1><p class="sub">감시 8팩의 밸류카드를 '
           '<b>한국 실거래(콜렉토리)</b>로 — 이미지·등급·한국 시세 + <b>일본 비교</b>. '
           '카드를 누르면 콜렉토리 가격 이력으로.</p><div class="legend">'
           '<span class="lg-lbl">등급</span>'
           '<span class="rk"><span class="dot" style="background:var(--mur)"></span>MUR</span>'
           '<span class="rk"><span class="dot" style="background:var(--sar)"></span>SAR</span>'
           '<span class="rk"><span class="dot" style="background:var(--ur)"></span>UR</span>'
           '<span class="rk"><span class="dot" style="background:var(--sr)"></span>SR</span>'
           '<span class="rk"><span class="dot" style="background:var(--ar)"></span>AR</span>'
           '<span class="rk"><span class="dot" style="background:var(--ex)"></span>RR</span>'
           '</div></header>')

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
        '.note{margin-top:24px;background:var(--surface);border:1px solid var(--border);border-radius:11px;padding:13px 16px;font-size:13px;color:var(--muted)}.note b{color:var(--text)}'
        'footer{margin-top:22px;color:var(--faint);font-size:12.5px}')

if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
