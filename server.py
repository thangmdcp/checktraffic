"""Entrypoint for CheckTraffic: Mounts FastAPI REST API on Streamlit Starlette Server natively.

Lắng nghe tại cổng chính (8501 hoặc $PORT):
- Mọi route /api/* -> Xử lý trực tiếp bởi FastAPI (REST API & Swagger Docs tại /api/docs)
- Mọi route khác (UI, WebSockets) -> Chạy trực tiếp trên Streamlit Starlette native engine.
"""

from __future__ import annotations

import os
import sys
from starlette.routing import Mount

PORT = int(os.getenv("PORT", "8501"))

# Patch Streamlit Starlette app creation modules BEFORE server starts
try:
    import streamlit.web.server.starlette.starlette_server as st_ss
    import streamlit.web.server.starlette.starlette_app as st_app_mod
    import streamlit.web.server.starlette as st_starlette
    from api import api_app

    orig_create_app = st_ss.create_starlette_app

    def custom_create_starlette_app(runtime):
        app = orig_create_app(runtime)
        # Insert /api Mount at index 0 BEFORE Streamlit SPA catch-all routes!
        app.routes.insert(0, Mount("/api", app=api_app))
        sys.__stdout__.write("\n🚀 Successfully mounted FastAPI REST API (/api) at index 0 of Starlette routes.\n")
        sys.__stdout__.flush()
        return app

    st_ss.create_starlette_app = custom_create_starlette_app
    st_app_mod.create_starlette_app = custom_create_starlette_app
    st_starlette.create_starlette_app = custom_create_starlette_app

except Exception as exc:
    print(f"⚠️ Warning: Could not patch Starlette app: {exc}")

if __name__ == "__main__":
    import streamlit.web.bootstrap as bootstrap

    flag_options = {
        "server_port": PORT,
        "server_address": "0.0.0.0",
        "server_headless": True,
        "browser_gatherUsageStats": False,
    }
    bootstrap.run("app.py", False, [], flag_options)
