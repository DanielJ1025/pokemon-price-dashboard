#!/usr/bin/env python
"""Orca 세션 시작 시 백그라운드로 도는 포켓몬 감시 루프(단일 인스턴스).

가정용 공유 PC 배려: 상시 Windows 스케줄러 대신 '내가 Orca 켜면' 시작.
- SessionStart 훅이 이 스크립트를 pythonw로 detached 실행(창 없음).
- 락파일 heartbeat 로 중복 실행 방지(세션 여러 개 열어도 1개만 감시).
- INTERVAL 마다 pokemon_deal_watch.py 실행, MAX_HOURS 후 자동 종료.
- 순수 파이썬(클로드 API 안 부름) → 크레딧 0.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WATCH = HERE / "pokemon_deal_watch.py"
LOCK = Path(os.environ.get("TEMP") or "/tmp") / "pokemon_watch_loop.lock"
INTERVAL = 180          # 3분마다
MAX_HOURS = 6           # 세션당 최대 감시(그 후 자동 종료 — 공유 PC 배려)
CREATE_NO_WINDOW = 0x08000000


def lock_fresh() -> bool:
    """다른 인스턴스가 감시 중인지(락 heartbeat 신선도)."""
    try:
        return LOCK.is_file() and (time.time() - LOCK.stat().st_mtime) < INTERVAL * 2.5
    except OSError:
        return False


def main() -> int:
    if lock_fresh():
        return 0                        # 이미 감시 중 — 중복 실행 안 함
    deadline = time.time() + MAX_HOURS * 3600
    try:
        while time.time() < deadline:
            try:
                LOCK.write_text(str(os.getpid()), encoding="utf-8")   # heartbeat
            except OSError:
                pass
            try:
                subprocess.run([sys.executable, str(WATCH)],
                               timeout=120, creationflags=CREATE_NO_WINDOW)
            except Exception:
                pass                    # 한 번 실패해도 루프 유지
            time.sleep(INTERVAL)
    finally:
        try:
            LOCK.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
