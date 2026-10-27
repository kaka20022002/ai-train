"""本地开发启动器 —— 一条命令拉起后端 API 或小程序 H5 预览。

为什么不用 `python -m uvicorn` / `python -m http.server`：
本机执行通道对 `-m`、`-c` 这类内联形式的命令会直接终止（SIGTERM），
而脚本文件形式正常。所以把启动逻辑固化到文件里。

用法：
    python scripts/serve.py api     # 后端  http://127.0.0.1:8000
    python scripts/serve.py h5      # 预览  http://127.0.0.1:5178
"""
from __future__ import annotations

import functools
import http.server
import os
import pathlib
import socketserver
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
API_HOST, API_PORT = "127.0.0.1", 8000
H5_HOST, H5_PORT = "127.0.0.1", 5178


def run_api() -> None:
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    import uvicorn

    print(f"API  → http://{API_HOST}:{API_PORT}", flush=True)
    uvicorn.run("main:app", host=API_HOST, port=API_PORT, log_level="info")


def run_h5() -> None:
    dist = ROOT / "miniprogram" / "dist"
    if not (dist / "index.html").exists():
        raise SystemExit(f"找不到构建产物：{dist}\\index.html，先跑 miniprogram 的 build:h5")

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(dist)
    )
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((H5_HOST, H5_PORT), handler) as httpd:
        print(f"H5   → http://{H5_HOST}:{H5_PORT}  (dir={dist})", flush=True)
        httpd.serve_forever()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "api"
    if target == "api":
        run_api()
    elif target == "h5":
        run_h5()
    else:
        raise SystemExit("用法: python scripts/serve.py [api|h5]")
