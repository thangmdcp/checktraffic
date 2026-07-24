"""Xuất danh sách kết quả traffic ra file Excel (.xlsx) trong bộ nhớ."""

from __future__ import annotations

import io
from typing import Iterable

import pandas as pd

from .scraper import TrafficResult

# Cột hiển thị (tiếng Việt) ánh xạ từ field của TrafficResult.
# Cột traffic dùng GIÁ TRỊ GỐC của traffic.cv (vd "92.012K") để giữ nguyên độ chính xác.
_COLUMNS = [
    ("domain", "Website"),
    ("monthly_visits_raw", "Lượt truy cập/tháng"),
    ("trend", "Xu hướng"),
    ("change", "Thay đổi"),
    ("pages_per_visit", "Trang/lượt"),
    ("avg_duration", "Thời lượng TB"),
    ("bounce_rate", "Tỷ lệ thoát"),
    ("registration", "Ngày đăng ký"),
    ("status", "Trạng thái"),
]


def results_to_dataframe(results: Iterable[TrafficResult]) -> pd.DataFrame:
    rows = [r.as_row() for r in results]
    df = pd.DataFrame(rows, columns=[k for k, _ in _COLUMNS if k in (rows[0] if rows else {}) or True])
    return df.rename(columns=dict(_COLUMNS))


def results_to_xlsx_bytes(results: Iterable[TrafficResult]) -> bytes:
    """Trả về nội dung file .xlsx dưới dạng bytes (để Streamlit download)."""
    df = results_to_dataframe(results)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Traffic")
    return buf.getvalue()


def results_to_csv_bytes(results: Iterable[TrafficResult]) -> bytes:
    return results_to_dataframe(results).to_csv(index=False).encode("utf-8-sig")


def save_results(results: Iterable[TrafficResult], path: str) -> None:
    """Ghi kết quả ra file .xlsx hoặc .csv tùy đuôi."""
    results = list(results)
    if path.lower().endswith(".csv"):
        with open(path, "wb") as f:
            f.write(results_to_csv_bytes(results))
    else:
        with open(path, "wb") as f:
            f.write(results_to_xlsx_bytes(results))
