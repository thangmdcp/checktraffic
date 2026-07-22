#!/bin/bash
# Kích đúp vào file này trên Mac để khởi động giao diện CheckTraffic cục bộ lập tức.

cd "$(dirname "$0")"
echo "====================================================="
echo "⚡ KHỞI ĐỘNG SAAS CHECKTRAFFIC TRÊN MÁY CÁ NHÂN LOCAL ⚡"
echo "====================================================="

if [ ! -d ".venv" ]; then
    echo "⚠️ Không tìm thấy môi trường ảo .venv. Đang tạo..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    playwright install chromium
else
    source .venv/bin/activate
fi

# Tự động mở trình duyệt và chạy app
streamlit run app.py --server.port=8501
