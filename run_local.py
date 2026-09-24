"""로컬 실행: app.py(라이브 시세 + ☁️ 시트로 전송)를 이 PC에서 띄운다.

루트 .env(gitignore)에서 GOOGLE_SERVICE_ACCOUNT_JSON(키 파일 경로)·POKEMON_SHEET_ID 를 읽는다.
localhost 전용(127.0.0.1). 포트 고정 8765 — 바뀌면 브라우저 저장소(보유 기록)가 갈린다.
실행: python run_local.py
"""
import os
import sys
import threading
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = 8765

env = HERE / ".env"
if env.exists():
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(HERE))
from app import app  # noqa: E402

if __name__ == "__main__":
    url = f"http://127.0.0.1:{PORT}/"
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print("대시보드:", url, "(종료: Ctrl+C)")
    app.run(host="127.0.0.1", port=PORT)
