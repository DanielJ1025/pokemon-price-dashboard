#!/usr/bin/env python
"""포켓몬 개별 카드 시세 감시 — 저평가 유망주 추적 → 매수기회·상승시작 텔레그램 알림.

팩(밀봉박스) 감시(pokemon_deal_watch.py)와 별개. 개별 카드를 사기로 한 사용자를 위해,
콜렉토리 한국 실거래로 관심카드 시세를 주기적으로 기록 → 의미있게 떨어지면 '매수 기회',
오르기 시작하면 '상승 시작(유망주 발화)' 알림. 순수 파이썬, 크레딧 0.

.env(같은 폴더): TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
사용: python card_watch.py [--dry-run] [--backfill]  (스케줄러로 N분마다)
"""
from __future__ import annotations
import argparse
import gzip
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
STATE = HERE / "card_watch_state.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

# ── 관심 카드 (여기만 고치면 됨) ─────────────────────────────
# (표시명, 콜렉토리 검색어=팩명, 카드번호). 번호로 정확히 특정(이름 충돌 방지).
# 저평가 유망주(인기 캐릭터인데 저가) + 보유팩 대장카드 시드.
WATCHLIST = [
    ("메가 다크라이 ex (RR)",   "어비스아이",   "046/081"),   # ₩1,000 슬리퍼
    ("메가레쿠쟈 ex (RR)",     "스톰에메랄다", "058/076"),   # ₩1,000
    ("피카츄 ex (RR)",         "초전브레이커", "033/106"),   # ₩1,000
    ("이상해꽃 ex (RR)",       "포켓몬카드 151", "003/165"),  # ₩5,000
    ("거북왕 ex (RR)",         "포켓몬카드 151", "009/165"),  # ₩5,500
    ("가이오가 (AR)",          "스톰에메랄다", "080/076"),   # ₩12,000
    ("메가레쿠쟈 ex (SR)",     "스톰에메랄다", "095/076"),   # ₩20,000
    ("피카츄 ex (SR)",         "초전브레이커", "122/106"),   # ₩25,000
    ("메가다크라이 ex (SAR)",  "어비스아이",   "114/081"),   # 보유팩 대장
    ("메가지가르데 ex (MUR)",  "니힐제로",     "117/080"),   # 보유팩 대장
]
DROP_PCT = 12          # 이만큼(%) 떨어지면 🟢 매수기회
RISE_PCT = 18          # 이만큼(%) 오르면 🔺 상승 시작(유망주 발화)
# ─────────────────────────────────────────────────────────


def log(m): print(f"[card-watch] {m}")


def load_env():
    p = HERE / ".env"
    if p.is_file():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_state() -> dict:
    if STATE.is_file():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return {"prices": {}}


def save_state(s):
    try:
        STATE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        log(f"상태 저장 실패(무시): {e}")


def collectory(query):
    url = ("https://collectory.cc/api/cards/search?q="
           + urllib.parse.quote(query) + "&limit=500")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json", "Referer": "https://collectory.cc/"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
        return (json.loads(raw.decode("utf-8")).get("results", {}) or {}).get("cards") or []
    except Exception as e:
        log(f"콜렉토리 실패({query!r}): {e}")
        return []


def find_card(query, num):
    for c in collectory(query):
        if c.get("region") == "kr" and c.get("cardNumber") == num and c.get("price"):
            return c
    return None


def tg(token, chat, text):
    data = urllib.parse.urlencode({
        "chat_id": chat, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": "false"}).encode()
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15) as r:
            return json.loads(r.read().decode("utf-8")).get("ok")
    except Exception as e:
        log(f"텔레그램 실패: {e}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--backfill", action="store_true", help="현재가만 기록(알림 없음)")
    args = ap.parse_args()
    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")

    state = load_state()
    prices = state.get("prices", {})
    alerts = []
    for label, query, num in WATCHLIST:
        c = find_card(query, num)
        if not c:
            continue
        key = f"{query}:{num}"
        cur = c["price"]
        prev = prices.get(key)
        link = f"https://collectory.cc/cards/{c.get('id')}"
        if prev and not args.backfill:
            chg = (cur - prev) / prev * 100
            if chg <= -DROP_PCT:
                alerts.append(f"🟢 <b>매수 기회 — {label}</b>\n"
                              f"₩{prev:,} → <b>₩{cur:,}</b> ({chg:+.0f}%)\n{link}")
            elif chg >= RISE_PCT:
                alerts.append(f"🔺 <b>상승 시작 — {label}</b>\n"
                              f"₩{prev:,} → <b>₩{cur:,}</b> ({chg:+.0f}%)\n{link}")
        prices[key] = cur
    state["prices"] = prices
    save_state(state)

    if args.backfill:
        log(f"backfill 완료 — {len(prices)}종 현재가 기록.")
        return 0
    if not alerts:
        log("변동 없음")
        return 0
    for a in alerts:
        if args.dry_run or not (token and chat):
            print("─" * 40); print(a)
        else:
            tg(token, chat, a)
    log(f"{len(alerts)}건 {'미리보기' if args.dry_run else '발송'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        log(f"예외 삼킴: {e}")
        raise SystemExit(0)
