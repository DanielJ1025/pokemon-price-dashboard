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
            + str(len(rows)) + '장, 홀로·커먼까지)</summary>'
            '<div class="tblwrap"><table><thead><tr><th>등급</th><th>번호</th>'
            '<th>카드</th><th>🇰🇷 한국</th><th>🇯🇵 일본</th></tr></thead><tbody>'
            + "".join(trs) + "</tbody></table></div></details>")


def build():
    secs = []
    for disp, query, owned in PACKS:
        try:
            allrows = pull(query)
        except Exception:
            allrows = []
        if not allrows:
            continue
        grid = [g for g in allrows if g["kr"] >= MIN_KR]
        total = len(grid)
        grid = grid[:TOPN]
        table = sorted(allrows, key=lambda x: (RORDER.get(x["rarity"], 9), -(x["kr"] or 0)))
        own = '<span class="own-badge">보유</span>' if owned else ""
        meta = f"밸류 {total}장 · 최고 🇰🇷 ₩{allrows[0]['kr']:,}"
        body = "".join(card_html(g) for g in grid)
        secs.append(f'<section class="pack"><div class="pack-head"><h2>'
                    f'{H.escape(disp)}</h2>{own}<span class="pack-meta">{meta}'
                    f'</span></div><div class="grid">{body}</div>{table_html(table)}</section>')
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
           '<p class="sub">한국 실거래(콜렉토리) · 일본 비교 · 1시간마다 갱신. 팩을 골라 보세요.</p></header>')

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
        '.full{border-top:1px solid var(--line)}'
        '.full summary{padding:12px 20px;font-size:13px;font-weight:700;color:var(--muted);cursor:pointer;user-select:none}'
        '.full summary:hover{color:var(--text)}'
        '.tblwrap{overflow-x:auto;padding:0 20px 18px}'
        'table{width:100%;border-collapse:collapse;font-size:12.5px}'
        'th{text-align:left;color:var(--faint);font-weight:600;padding:6px 8px;border-bottom:1px solid var(--border);font-size:11px;text-transform:uppercase}'
        'td{padding:6px 8px;border-bottom:1px solid var(--line)}'
        'td a{color:inherit;text-decoration:none}td a:hover{color:var(--sar)}'
        '.tn,.tp,.tj{font-variant-numeric:tabular-nums}.tp{font-weight:700}.tj{color:var(--faint)}'
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
             'section.pack[hidden],#deals-panel[hidden]{display:none!important}'
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
 const side=document.createElement('aside');side.className='sidebar';
 const brand=document.createElement('div');brand.className='brand';
 brand.innerHTML=header?header.innerHTML:'<h1>내 포켓몬 카드 시세판</h1>';
 const nav=document.createElement('nav');nav.className='tablist';
 side.appendChild(brand);side.appendChild(nav);
 const content=document.createElement('main');content.className='content';
 content.appendChild(dp);
 packs.forEach(p=>content.appendChild(p));
 if(note)content.appendChild(note);
 if(footer)content.appendChild(footer);
 wrap.innerHTML='';wrap.appendChild(side);wrap.appendChild(content);
 const btns=[];
 function add(label,cls,onclick){const b=document.createElement('button');b.textContent=label;if(cls)b.className=cls;b.title=label;b.onclick=onclick;nav.appendChild(b);btns.push(b);return b;}
 function select(i){btns.forEach((b,j)=>b.classList.toggle('active',j===i));dp.hidden=(i!==0);packs.forEach((p,j)=>p.hidden=(i!==j+1));try{localStorage.setItem('pkm_tab',i)}catch(e){}}
 add('💰 매물·가성비','deal',()=>select(0));
 const sep=document.createElement('div');sep.className='sep';nav.appendChild(sep);
 packs.forEach((p,j)=>{const nm=(p.querySelector('h2')||{}).textContent||('팩'+(j+1));add(nm.trim(),'',()=>select(j+1));});
 let start=1;try{const s=parseInt(localStorage.getItem('pkm_tab'));if(!isNaN(s)&&s>=0&&s<=packs.length)start=s;}catch(e){}
 select(start);
})();'''


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
