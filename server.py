"""Entrypoint for CheckTraffic: Mounts FastAPI REST API on Streamlit Starlette Server natively.

Lắng nghe tại cổng chính (8501 hoặc $PORT):
- Mọi route /api/* -> Xử lý trực tiếp bởi FastAPI (REST API & Swagger Docs tại /api/docs)
- Mọi route khác (UI, WebSockets) -> Chạy trực tiếp trên Streamlit Starlette native engine.
"""

from __future__ import annotations

import os
import sys

PORT = int(os.getenv("PORT", "8501"))

# Monkeypatch Streamlit internal Starlette app factory
try:
    import streamlit.web.server.starlette as st_starlette
    from api import api_app

    orig_create_app = st_starlette.create_starlette_app

    def custom_create_starlette_app(runtime):
        app = orig_create_app(runtime)
        # Mount FastAPI REST API app at /api prefix
        app.mount("/api", api_app)
        return app

    st_starlette.create_starlette_app = custom_create_starlette_app
    print("🚀 Successfully integrated FastAPI REST API (/api) into Streamlit Starlette engine.")
except Exception as exc:
    print(f"⚠️ Warning: Could not patch Starlette app: {exc}")

if __name__ == "__main__":
    import streamlit.web.cli as stcli

    sys.argv = [
        "streamlit", "run", "app.py",
        f"--server.port={PORT}",
        "--server.address=0.0.0.0",
        "--server.headless=true",
        "--browser.gatherUsageStats=false"
    ]
    sys.exit(stcli.main())
