"""Cache kết quả traffic vào SQLite để khỏi check lại domain đã có (giảm tải, lịch sự)."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

from .scraper import TrafficResult

DEFAULT_DB = os.getenv(
    "TRAFFICCV_CACHE_DB",
    str(Path(__file__).resolve().parent.parent / "cache.db"),
)
DEFAULT_TTL = 90 * 24 * 3600  # 90 ngày

# Các cột dữ liệu (khớp tên field của TrafficResult), không gồm domain/status/fetched_at.
_FIELDS = ("monthly_visits", "monthly_visits_raw", "change", "trend",
           "pages_per_visit", "avg_duration", "bounce_rate", "registration")


class Cache:
    def __init__(self, db_path: str = DEFAULT_DB, ttl: int = DEFAULT_TTL):
        self.ttl = ttl
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS traffic (
                domain TEXT PRIMARY KEY,
                monthly_visits INTEGER,
                monthly_visits_raw TEXT,
                change TEXT,
                trend TEXT,
                pages_per_visit TEXT,
                avg_duration TEXT,
                bounce_rate TEXT,
                registration TEXT,
                status TEXT,
                fetched_at REAL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS brand_site (
                brand TEXT PRIMARY KEY,
                domain TEXT,
                fetched_at REAL
            )
            """
        )
        self._migrate()
        self.conn.commit()

    # ----- cache brand -> domain -----
    def get_brand(self, brand: str) -> Optional[str]:
        """Domain đã tra cho brand (còn hạn), hoặc None."""
        row = self.conn.execute(
            "SELECT domain, fetched_at FROM brand_site WHERE brand = ?", (brand.lower(),)
        ).fetchone()
        if not row:
            return None
        domain, fetched_at = row
        if not domain or (time.time() - fetched_at) > self.ttl:
            return None
        return domain

    def put_brand(self, brand: str, domain: str, now: Optional[float] = None) -> None:
        if not domain:
            return  # chỉ cache brand tìm được web
        self.conn.execute(
            "INSERT OR REPLACE INTO brand_site (brand, domain, fetched_at) VALUES (?, ?, ?)",
            (brand.lower(), domain, now if now is not None else time.time()),
        )
        self.conn.commit()

    def _migrate(self) -> None:
        """Thêm cột còn thiếu cho cache.db cũ (giữ nguyên dữ liệu đã có)."""
        existing = {r[1] for r in self.conn.execute("PRAGMA table_info(traffic)")}
        for col in _FIELDS:
            if col not in existing:
                coltype = "INTEGER" if col == "monthly_visits" else "TEXT"
                self.conn.execute(f"ALTER TABLE traffic ADD COLUMN {col} {coltype}")

    def get(self, domain: str) -> Optional[TrafficResult]:
        """Kết quả 'ok' còn hạn cho domain, hoặc None. Không cache lỗi/blocked."""
        cols = ", ".join(_FIELDS)
        row = self.conn.execute(
            f"SELECT {cols}, status, fetched_at FROM traffic WHERE domain = ?",
            (domain,),
        ).fetchone()
        if not row:
            return None
        *vals, status, fetched_at = row
        if status != "ok" or (time.time() - fetched_at) > self.ttl:
            return None
        return TrafficResult(domain, **dict(zip(_FIELDS, vals)), status="ok")

    def put(self, result: TrafficResult, now: Optional[float] = None) -> None:
        if result.status != "ok":
            return  # chỉ lưu kết quả thành công
        cols = ", ".join(_FIELDS)
        placeholders = ", ".join("?" for _ in _FIELDS)
        self.conn.execute(
            f"INSERT OR REPLACE INTO traffic (domain, {cols}, status, fetched_at) "
            f"VALUES (?, {placeholders}, ?, ?)",
            (result.domain, *(getattr(result, f) for f in _FIELDS),
             result.status, now if now is not None else time.time()),
        )
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
