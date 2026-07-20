"""Single entrypoint combining Streamlit UI and FastAPI REST API.

Lắng nghe tại cổng chính (8501 hoặc $PORT):
- Mọi route /api/* -> Xử lý bởi FastAPI (REST API & Swagger Docs tại /api/docs)
- Mọi route khác (UI, WebSockets) -> Reverse Proxy tới Streamlit chạy cổng nội bộ 8502.
"""

from __future__ import annotations

import os
import sys
import subprocess
import asyncio
import httpx
from fastapi import FastAPI, Request, Response, WebSocket
import uvicorn
import websockets

from api import api_app

PORT = int(os.getenv("PORT", "8501"))
STREAMLIT_PORT = 8502
STREAMLIT_URL = f"http://127.0.0.1:{STREAMLIT_PORT}"
STREAMLIT_WS_URL = f"ws://127.0.0.1:{STREAMLIT_PORT}"


def start_streamlit():
    env = os.environ.copy()
    env["STREAMLIT_SERVER_PORT"] = str(STREAMLIT_PORT)
    env["STREAMLIT_SERVER_ADDRESS"] = "127.0.0.1"
    env["STREAMLIT_SERVER_HEADLESS"] = "true"
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

    cmd = [
        sys.executable, "-m", "streamlit", "run", "app.py",
        f"--server.port={STREAMLIT_PORT}",
        "--server.address=127.0.0.1",
        "--server.headless=true"
    ]
    return subprocess.Popen(cmd, env=env)


@api_app.websocket("/{path:path}")
async def websocket_proxy(websocket: WebSocket, path: str):
    await websocket.accept()
    query = str(websocket.query_params)
    target_url = f"{STREAMLIT_WS_URL}/{path}" + (f"?{query}" if query else "")

    try:
        async with websockets.connect(target_url) as target_ws:
            async def forward_client():
                try:
                    while True:
                        msg = await websocket.receive()
                        if "text" in msg and msg["text"] is not None:
                            await target_ws.send(msg["text"])
                        elif "bytes" in msg and msg["bytes"] is not None:
                            await target_ws.send(msg["bytes"])
                except Exception:
                    pass

            async def forward_target():
                try:
                    while True:
                        data = await target_ws.recv()
                        if isinstance(data, str):
                            await websocket.send_text(data)
                        else:
                            await websocket.send_bytes(data)
                except Exception:
                    pass

            await asyncio.gather(forward_client(), forward_target())
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


@api_app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
async def http_proxy(request: Request, path: str):
    async with httpx.AsyncClient(base_url=STREAMLIT_URL, timeout=120.0) as client:
        query = str(request.query_params)
        url = f"/{path}" + (f"?{query}" if query else "")

        headers = dict(request.headers)
        headers.pop("host", None)
        headers.pop("content-length", None)

        body = await request.body()

        try:
            resp = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
                follow_redirects=False
            )

            resp_headers = dict(resp.headers)
            resp_headers.pop("content-length", None)
            resp_headers.pop("content-encoding", None)
            resp_headers.pop("transfer-encoding", None)

            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=resp_headers
            )
        except Exception as e:
            return Response(content=f"CheckTraffic Web starting... ({e})", status_code=503)


if __name__ == "__main__":
    st_proc = start_streamlit()
    print(f"🚀 Started Streamlit process on port {STREAMLIT_PORT}")
    print(f"🚀 Starting FastAPI entrypoint on port {PORT}")
    try:
        uvicorn.run(api_app, host="0.0.0.0", port=PORT)
    finally:
        st_proc.terminate()
