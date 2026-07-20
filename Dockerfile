# Ảnh Playwright đã kèm sẵn Chromium + thư viện hệ thống → deploy online dễ dàng.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV TRAFFICCV_HEADLESS=1
EXPOSE 8501
CMD ["python", "server.py"]
