"""로컬 실행: app.py(라이브 시세 + ☁️ 시트로 전송)를 이 PC에서 띄운다.

루트 .env(gitignore)에서 GOOGLE_SERVICE_ACCOUNT_JSON(키 파일 경로)·POKEMON_SHEET_ID 를 읽는다.
localhost 전용(127.0.0.1). 포트 고정 8765 — 바뀌면 브라우저 저장소(보유 기록)가 갈린다.
실행: python run_local.py  (브라우저 안 열기: --no-browser · 오늘 시세만 기록: --record)
"""
import os
import sys
import threading
import webbrowser
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
PORT = 8765

env = HERE / ".env"
if env.exists():
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

os.environ.setdefault("LOCAL_NO_TOKEN", "1")  # 127.0.0.1 전용이라 키 불필요
sys.path.insert(0, str(HERE))
from app import app  # noqa: E402

if __name__ == "__main__":
    if "--record" in sys.argv:  # 서버 없이 오늘 시세만 시트(_카드시세)에 기록하고 종료 — 스케줄러용
        import app as _a
        _a.build()
        print("기록:", _a._PH["day"], len(_a._PH["done"] or ()), "장")
        sys.exit(0)
    url = f"http://127.0.0.1:{PORT}/"
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print("대시보드:", url, "(종료: Ctrl+C)")
    app.run(host="127.0.0.1", port=PORT)
