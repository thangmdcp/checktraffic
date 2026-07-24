"""Cache kết quả traffic vào SQLite để khỏi check lại domain đã có (giảm tải, lịch sự)."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

import json
import httpx
from .scraper import TrafficResult

DEFAULT_DB = os.getenv(
    "TRAFFICCV_CACHE_DB",
    str(Path(__file__).resolve().parent.parent / "cache.db"),
)
DEFAULT_TTL = 3650 * 24 * 3600  # 10 năm (vô thời hạn trừ khi force_refresh)

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://kwwrzoouitcknzwlcttc.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt3d3J6b291aXRja256d2xjdHRjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODI3NTI2MzAsImV4cCI6MjA5ODMyODYzMH0.N6O0_RcA_OzyPDQOOqmDRkm0nIRa_uwZK9L59mXswDw")

# Các cột dữ liệu (khớp tên field của TrafficResult), không gồm domain/status/fetched_at.
_FIELDS = ("monthly_visits", "monthly_visits_raw", "change", "trend",
           "pages_per_visit", "avg_duration", "bounce_rate", "registration",
           "top_regions", "top_keywords")


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
                top_regions TEXT,
                top_keywords TEXT,
                status TEXT,
                fetched_at REAL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                name TEXT PRIMARY KEY,
                updated_at REAL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_domains (
                project_name TEXT,
                domain TEXT,
                PRIMARY KEY (project_name, domain)
            )
            """
        )
        self._migrate()
        self.conn.commit()

        self.sb_headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        } if SUPABASE_URL and SUPABASE_KEY else None

    # ----- cache brand -> domain -----
    def get_brand(self, brand: str) -> Optional[str]:
        """Domain đã tra cho brand (còn hạn), hoặc None."""
        brand_clean = brand.lower()
        row = self.conn.execute(
            "SELECT domain, fetched_at FROM brand_site WHERE brand = ?", (brand_clean,)
        ).fetchone()
        if row:
            domain, fetched_at = row
            if domain and (time.time() - fetched_at) <= self.ttl:
                return domain

        # Thử đọc từ Supabase Cloud
        if self.sb_headers:
            try:
                url = f"{SUPABASE_URL}/rest/v1/brand_site_cache?brand=eq.{brand_clean}&select=domain,fetched_at"
                r = httpx.get(url, headers=self.sb_headers, timeout=3.0)
                if r.status_code == 200 and r.json():
                    data = r.json()[0]
                    dom = data.get("domain")
                    fat = data.get("fetched_at", 0)
                    if dom and (time.time() - fat) <= self.ttl:
                        # Lưu ngược lại SQLite
                        self.conn.execute(
                            "INSERT OR REPLACE INTO brand_site (brand, domain, fetched_at) VALUES (?, ?, ?)",
                            (brand_clean, dom, fat),
                        )
                        self.conn.commit()
                        return dom
            except Exception:
                pass

        return None

    def put_brand(self, brand: str, domain: str, now: Optional[float] = None) -> None:
        if not domain:
            return  # chỉ cache brand tìm được web
        brand_clean = brand.lower()
        ts = now if now is not None else time.time()
        self.conn.execute(
            "INSERT OR REPLACE INTO brand_site (brand, domain, fetched_at) VALUES (?, ?, ?)",
            (brand_clean, domain, ts),
        )
        self.conn.commit()

        # Đẩy lên Supabase Cloud
        if self.sb_headers:
            try:
                url = f"{SUPABASE_URL}/rest/v1/brand_site_cache"
                payload = {"brand": brand_clean, "domain": domain, "fetched_at": ts}
                httpx.post(url, headers=self.sb_headers, json=payload, timeout=3.0)
            except Exception:
                pass

    def _migrate(self) -> None:
        """Thêm cột còn thiếu cho cache.db cũ (giữ nguyên dữ liệu đã có)."""
        existing = {r[1] for r in self.conn.execute("PRAGMA table_info(traffic)")}
        for col in _FIELDS:
            if col not in existing:
                coltype = "INTEGER" if col == "monthly_visits" else "TEXT"
                self.conn.execute(f"ALTER TABLE traffic ADD COLUMN {col} {coltype}")
        # Xóa tự động tất cả các bản ghi cache cũ bị lỗi hoặc rỗng số liệu
        try:
            self.conn.execute("DELETE FROM traffic WHERE status != 'ok' OR monthly_visits_raw IS NULL OR monthly_visits_raw = 'N/A' OR monthly_visits_raw = 'TRAFFIC'")
            self.conn.commit()
        except Exception:
            pass

    def get_many(self, domains: list[str]) -> dict[str, TrafficResult]:
        """Lấy toàn bộ kết quả 'ok' còn hạn cho danh sách domains (SQLite + Supabase bulk query)."""
        if not domains:
            return {}

        now = time.time()
        out: dict[str, TrafficResult] = {}
        missing: list[str] = []

        # 1. Tra cứu hàng loạt từ SQLite local (1 query SQL duy nhất)
        cols = ", ".join(_FIELDS)
        placeholders = ", ".join("?" for _ in domains)
        try:
            rows = self.conn.execute(
                f"SELECT domain, {cols}, status, fetched_at FROM traffic WHERE domain IN ({placeholders})",
                tuple(domains),
            ).fetchall()

            for row in rows:
                dom, *vals, status, fetched_at = row
                if status == "ok" and (now - fetched_at) <= self.ttl:
                    data = dict(zip(_FIELDS, vals))
                    if data.get("monthly_visits_raw") and data.get("monthly_visits_raw") not in ("N/A", "TRAFFIC"):
                        for k in ("top_regions", "top_keywords"):
                            if isinstance(data.get(k), str):
                                try:
                                    data[k] = json.loads(data[k])
                                except Exception:
                                    data[k] = None
                        out[dom] = TrafficResult(dom, status="ok", cache_hit=True, **data)
        except Exception:
            pass

        for d in domains:
            if d not in out:
                missing.append(d)

        # 2. Tra cứu hàng loạt từ Supabase Cloud (chỉ 1 HTTP GET request duy nhất)
        if missing and self.sb_headers:
            from .scraper import chunked
            try:
                for chunk in chunked(missing, 50):
                    in_clause = ",".join(chunk)
                    url = f"{SUPABASE_URL}/rest/v1/traffic_cache?domain=in.({in_clause})&select=*"
                    r = httpx.get(url, headers=self.sb_headers, timeout=5.0)
                    if r.status_code == 200 and r.json():
                        for sb_row in r.json():
                            dom = sb_row.get("domain")
                            if dom and sb_row.get("status") == "ok" and (now - sb_row.get("fetched_at", 0)) <= self.ttl:
                                data = {f: sb_row.get(f) for f in _FIELDS}
                                if data.get("monthly_visits_raw") and data.get("monthly_visits_raw") not in ("N/A", "TRAFFIC"):
                                    row_vals = []
                                    for f in _FIELDS:
                                        v = data.get(f)
                                        if f in ("top_regions", "top_keywords") and isinstance(v, (list, dict)):
                                            v = json.dumps(v, ensure_ascii=False)
                                        row_vals.append(v)
                                    p_holders = ", ".join("?" for _ in _FIELDS)
                                    self.conn.execute(
                                        f"INSERT OR REPLACE INTO traffic (domain, {cols}, status, fetched_at) "
                                        f"VALUES (?, {p_holders}, ?, ?)",
                                        (dom, *row_vals, "ok", sb_row.get("fetched_at")),
                                    )
                                    out[dom] = TrafficResult(dom, status="ok", cache_hit=True, **data)
                        self.conn.commit()
            except Exception:
                pass

        return out

    def get(self, domain: str) -> Optional[TrafficResult]:
        """Kết quả 'ok' còn hạn cho domain, hoặc None. Không cache lỗi/blocked."""
        cols = ", ".join(_FIELDS)
        row = self.conn.execute(
            f"SELECT {cols}, status, fetched_at FROM traffic WHERE domain = ?",
            (domain,),
        ).fetchone()
        
        if row:
            *vals, status, fetched_at = row
            if status == "ok" and (time.time() - fetched_at) <= self.ttl:
                data = dict(zip(_FIELDS, vals))
                if data.get("monthly_visits_raw") and data.get("monthly_visits_raw") != "N/A":
                    if data.get("top_regions") and isinstance(data["top_regions"], str):
                        try:
                            data["top_regions"] = json.loads(data["top_regions"])
                        except Exception:
                            data["top_regions"] = None
                    if data.get("top_keywords") and isinstance(data["top_keywords"], str):
                        try:
                            data["top_keywords"] = json.loads(data["top_keywords"])
                        except Exception:
                            data["top_keywords"] = None
                    return TrafficResult(domain, status="ok", cache_hit=True, **data)

        # Thử đọc từ Supabase Cloud nếu SQLite không có
        if self.sb_headers:
            try:
                url = f"{SUPABASE_URL}/rest/v1/traffic_cache?domain=eq.{domain}&select=*"
                r = httpx.get(url, headers=self.sb_headers, timeout=3.0)
                if r.status_code == 200 and r.json():
                    sb_row = r.json()[0]
                    if sb_row.get("status") == "ok" and (time.time() - sb_row.get("fetched_at", 0)) <= self.ttl:
                        data = {f: sb_row.get(f) for f in _FIELDS}
                        if data.get("monthly_visits_raw") and data.get("monthly_visits_raw") != "N/A":
                            # Lưu vào SQLite local
                            row_vals = []
                            for f in _FIELDS:
                                v = data.get(f)
                                if f in ("top_regions", "top_keywords") and isinstance(v, (list, dict)):
                                    v = json.dumps(v, ensure_ascii=False)
                                row_vals.append(v)
                            placeholders = ", ".join("?" for _ in _FIELDS)
                            self.conn.execute(
                                f"INSERT OR REPLACE INTO traffic (domain, {cols}, status, fetched_at) "
                                f"VALUES (?, {placeholders}, ?, ?)",
                                (domain, *row_vals, "ok", sb_row.get("fetched_at")),
                            )
                            self.conn.commit()
                            return TrafficResult(domain, status="ok", cache_hit=True, **data)
            except Exception:
                pass

        return None

    def put(self, result: TrafficResult, now: Optional[float] = None) -> None:
        if result.status != "ok":
            return  # chỉ lưu kết quả thành công
        cols = ", ".join(_FIELDS)
        placeholders = ", ".join("?" for _ in _FIELDS)

        val_dict = result.as_row()
        row_vals = []
        for f in _FIELDS:
            v = val_dict.get(f)
            if f in ("top_regions", "top_keywords") and isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False)
            row_vals.append(v)

        ts = now if now is not None else time.time()
        self.conn.execute(
            f"INSERT OR REPLACE INTO traffic (domain, {cols}, status, fetched_at) "
            f"VALUES (?, {placeholders}, ?, ?)",
            (result.domain, *row_vals, result.status, ts),
        )
        self.conn.commit()

        # Đồng bộ lên Supabase Cloud
        if self.sb_headers:
            try:
                url = f"{SUPABASE_URL}/rest/v1/traffic_cache"
                payload = {
                    "domain": result.domain,
                    "monthly_visits": result.monthly_visits,
                    "monthly_visits_raw": result.monthly_visits_raw,
                    "change": result.change,
                    "trend": result.trend,
                    "pages_per_visit": result.pages_per_visit,
                    "avg_duration": result.avg_duration,
                    "bounce_rate": result.bounce_rate,
                    "registration": result.registration,
                    "top_regions": result.top_regions,
                    "top_keywords": result.top_keywords,
                    "status": result.status,
                    "fetched_at": ts,
                }
                httpx.post(url, headers=self.sb_headers, json=payload, timeout=3.0)
            except Exception:
                pass

    def save_project(self, name: str, domains: list[str]) -> float:
        """Lưu danh sách dự án với danh sách tên miền và trả về thời gian cập nhật."""
        name_clean = name.strip()
        if not name_clean:
            return time.time()
        ts = time.time()
        self.conn.execute("INSERT OR REPLACE INTO projects (name, updated_at) VALUES (?, ?)", (name_clean, ts))
        for d in domains:
            if d:
                self.conn.execute("INSERT OR REPLACE INTO project_domains (project_name, domain) VALUES (?, ?)", (name_clean, d.lower()))
        self.conn.commit()

        if self.sb_headers:
            try:
                url_p = f"{SUPABASE_URL}/rest/v1/projects"
                httpx.post(url_p, headers=self.sb_headers, json={"name": name_clean, "updated_at": ts}, timeout=3.0)
                url_pd = f"{SUPABASE_URL}/rest/v1/project_domains"
                pd_payload = [{"project_name": name_clean, "domain": d.lower()} for d in domains if d]
                if pd_payload:
                    httpx.post(url_pd, headers=self.sb_headers, json=pd_payload, timeout=3.0)
            except Exception:
                pass
        return ts

    def get_projects(self) -> list[dict]:
        """Lấy danh sách tất cả các dự án đã lưu kèm thời gian cập nhật."""
        out = []
        try:
            rows = self.conn.execute("SELECT name, updated_at FROM projects ORDER BY updated_at DESC").fetchall()
            for r in rows:
                out.append({"name": r[0], "updated_at": r[1]})
        except Exception:
            pass

        if self.sb_headers:
            try:
                url = f"{SUPABASE_URL}/rest/v1/projects?select=name,updated_at&order=updated_at.desc"
                r = httpx.get(url, headers=self.sb_headers, timeout=3.0)
                if r.status_code == 200 and r.json():
                    sb_projects = r.json()
                    existing_names = {x["name"] for x in out}
                    for item in sb_projects:
                        if item.get("name") not in existing_names:
                            out.append({"name": item.get("name"), "updated_at": item.get("updated_at", 0)})
            except Exception:
                pass

        return out

    def get_project_domains(self, name: str) -> list[str]:
        """Lấy toàn bộ domain thuộc về một dự án."""
        name_clean = name.strip()
        doms = []
        try:
            rows = self.conn.execute("SELECT domain FROM project_domains WHERE project_name = ?", (name_clean,)).fetchall()
            doms = [r[0] for r in rows if r[0]]
        except Exception:
            pass

        if self.sb_headers:
            try:
                url = f"{SUPABASE_URL}/rest/v1/project_domains?project_name=eq.{name_clean}&select=domain"
                r = httpx.get(url, headers=self.sb_headers, timeout=3.0)
                if r.status_code == 200 and r.json():
                    sb_doms = [x.get("domain") for x in r.json() if x.get("domain")]
                    for d in sb_doms:
                        if d not in doms:
                            doms.append(d)
            except Exception:
                pass

        return doms

    def get_all_saved_domains(self) -> list[str]:
        """Lấy toàn bộ danh sách các domain có sẵn trong Supabase/Cache."""
        doms = []
        try:
            rows = self.conn.execute("SELECT domain FROM traffic WHERE status = 'ok' ORDER BY fetched_at DESC").fetchall()
            doms = [r[0] for r in rows if r[0]]
        except Exception:
            pass

        if self.sb_headers:
            try:
                url = f"{SUPABASE_URL}/rest/v1/traffic_cache?select=domain&status=eq.ok&order=fetched_at.desc&limit=1000"
                r = httpx.get(url, headers=self.sb_headers, timeout=3.0)
                if r.status_code == 200 and r.json():
                    sb_doms = [x.get("domain") for x in r.json() if x.get("domain")]
                    for d in sb_doms:
                        if d not in doms:
                            doms.append(d)
            except Exception:
                pass

        return doms

    def rename_project(self, old_name: str, new_name: str) -> None:
        """Đổi tên một dự án đã có."""
        old_clean = old_name.strip()
        new_clean = new_name.strip()
        if not old_clean or not new_clean or old_clean == new_clean:
            return
        
        self.conn.execute("UPDATE projects SET name = ? WHERE name = ?", (new_clean, old_clean))
        self.conn.execute("UPDATE project_domains SET project_name = ? WHERE project_name = ?", (new_clean, old_clean))
        self.conn.commit()

        if self.sb_headers:
            try:
                httpx.patch(f"{SUPABASE_URL}/rest/v1/projects?name=eq.{old_clean}", headers=self.sb_headers, json={"name": new_clean}, timeout=3.0)
                httpx.patch(f"{SUPABASE_URL}/rest/v1/project_domains?project_name=eq.{old_clean}", headers=self.sb_headers, json={"project_name": new_clean}, timeout=3.0)
            except Exception:
                pass

    def delete_project(self, name: str) -> None:
        """Xóa một dự án đã lưu."""
        name_clean = name.strip()
        if not name_clean:
            return
        
        self.conn.execute("DELETE FROM projects WHERE name = ?", (name_clean,))
        self.conn.execute("DELETE FROM project_domains WHERE project_name = ?", (name_clean,))
        self.conn.commit()

        if self.sb_headers:
            try:
                httpx.delete(f"{SUPABASE_URL}/rest/v1/projects?name=eq.{name_clean}", headers=self.sb_headers, timeout=3.0)
                httpx.delete(f"{SUPABASE_URL}/rest/v1/project_domains?project_name=eq.{name_clean}", headers=self.sb_headers, timeout=3.0)
            except Exception:
                pass

    def delete_domains(self, domains: list[str]) -> int:
        """Xóa danh sách domains khỏi SQLite và Supabase Cloud."""
        clean_doms = list({d.lower().strip() for d in domains if d and d.strip()})
        if not clean_doms:
            return 0
        
        from .scraper import chunked
        # 1. Xóa trong SQLite local
        placeholders = ", ".join("?" for _ in clean_doms)
        try:
            self.conn.execute(f"DELETE FROM traffic WHERE domain IN ({placeholders})", tuple(clean_doms))
            self.conn.execute(f"DELETE FROM project_domains WHERE domain IN ({placeholders})", tuple(clean_doms))
            self.conn.commit()
        except Exception:
            pass

        # 2. Xóa trong Supabase Cloud (theo lô 50 domain/lần)
        if self.sb_headers:
            try:
                for chunk in chunked(clean_doms, 50):
                    in_clause = ",".join(chunk)
                    httpx.delete(f"{SUPABASE_URL}/rest/v1/traffic_cache?domain=in.({in_clause})", headers=self.sb_headers, timeout=5.0)
                    httpx.delete(f"{SUPABASE_URL}/rest/v1/project_domains?domain=in.({in_clause})", headers=self.sb_headers, timeout=5.0)
            except Exception:
                pass

        return len(clean_doms)

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
