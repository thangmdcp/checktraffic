#!/bin/bash
# Bấm đúp vào file này để chạy app. Lần đầu sẽ tự cài đặt (hơi lâu), các lần sau chạy ngay.

cd "$(dirname "$0")" || exit 1

echo "================================================"
echo "   📊  Check Traffic hàng loạt - traffic.cv"
echo "================================================"

# 1) Tạo môi trường ảo + cài đặt nếu chưa có
if [ ! -x ".venv/bin/streamlit" ]; then
  echo "⏳ Lần đầu chạy: đang cài đặt thư viện (có thể mất vài phút)..."
  if [ ! -d ".venv" ]; then
    python3 -m venv .venv || { echo "❌ Không tạo được môi trường. Cần cài Python 3."; read -r; exit 1; }
  fi
  ".venv/bin/pip" install --quiet --upgrade pip
  ".venv/bin/pip" install --quiet -r requirements.txt || { echo "❌ Cài thư viện thất bại."; read -r; exit 1; }
  echo "⏳ Đang tải trình duyệt cho Playwright..."
  ".venv/bin/playwright" install chromium
fi

# 2) Chạy app (Streamlit sẽ tự mở trình duyệt)
echo "🚀 Đang khởi động... trình duyệt sẽ tự mở tại http://localhost:8501"
echo "   (Đóng cửa sổ Terminal này để tắt app.)"
echo
".venv/bin/streamlit" run app.py

# Giữ cửa sổ mở nếu có lỗi
echo
echo "App đã dừng. Nhấn Enter để đóng."
read -r
