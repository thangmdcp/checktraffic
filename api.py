"""FastAPI REST API cho CheckTraffic.

Cung cấp các API endpoint để các Web App khác có thể gọi sang lấy dữ liệu traffic
trực tiếp dưới dạng JSON (hỗ trợ CORS cho trình duyệt).
"""

from __future__ import annotations

import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from trafficcv.cache import Cache
from trafficcv.runner import run_auto_batch, RunSettings, load_proxies
from trafficcv.brand import load_serper_keys
from trafficcv.scraper import TrafficResult

api_app = FastAPI(
    title="CheckTraffic REST API",
    description="REST API tự động lấy dữ liệu lượt truy cập/tháng từ traffic.cv cho website & thương hiệu.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS Middleware để các Web App khác có thể gọi AJAX/Fetch trực tiếp từ trình duyệt
api_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CheckRequest(BaseModel):
    inputs: List[str] = Field(
        ...,
        description="Danh sách website hoặc tên brand (ví dụ: ['google.com', 'Nike', 'atoms.com'])",
        json_schema_extra={"example": ["google.com", "vnexpress.net", "Nike"]}
    )
    use_cache: bool = Field(default=True, description="Sử dụng dữ liệu cache gần đây nếu có")
    force_refresh: bool = Field(default=False, description="Nếu True, bắt buộc quét mới 100% và ghi đè dữ liệu cũ trong Supabase")
    speed: str = Field(default="Vừa", description="Tốc độ quét: 'An toàn', 'Vừa', 'Nhanh'")
    serper_api_keys: Optional[List[str]] = Field(default=None, description="Danh sách Serper API key tùy chọn cho tên brand")
    concurrency: int = Field(default=3, description="Số luồng chạy song song (1-5)")


class TrafficItem(BaseModel):
    input: str
    brand_name: str
    domain: str
    total_visits: str
    monthly_visits_raw: str
    change: str
    trend: str
    pages_per_visit: str
    avg_duration: str
    bounce_rate: str
    top_regions: Optional[List[dict]] = Field(default=None, description="Top 5 quốc gia có lượng traffic lớn nhất (country, share)")
    top_keywords: Optional[List[dict]] = Field(default=None, description="Top 5 từ khóa mang lại traffic (keyword, traffic, volume, cpc)")
    status: str
    cache_hit: bool


class CheckResponse(BaseModel):
    status: str
    total_inputs: int
    data: List[TrafficItem]


@api_app.get("/health", summary="Kiểm tra trạng thái API")
def health_check():
    return {"status": "ok", "service": "CheckTraffic API", "version": "1.1.0"}


@api_app.get("/cache", summary="Tra cứu dữ liệu nhanh từ Cache")
def get_cached_domain(domain: str = Query(..., description="Root domain (ví dụ: google.com) cần tra cứu trong cache")):
    cache = Cache()
    res = cache.get(domain)
    if not res:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy dữ liệu cache cho domain '{domain}'")
    return {
        "status": "success",
        "domain": domain,
        "data": {
            "domain": res.domain,
            "total_visits": res.monthly_visits_raw,
            "change": res.change,
            "trend": res.trend,
            "pages_per_visit": res.pages_per_visit,
            "avg_duration": res.avg_duration,
            "bounce_rate": res.bounce_rate,
            "top_regions": res.top_regions,
            "top_keywords": res.top_keywords,
            "status": res.status,
            "cache_hit": True
        }
    }


@api_app.post("/check", response_model=CheckResponse, summary="Check traffic cho danh sách website / brand")
def check_traffic(req: CheckRequest):
    if not req.inputs:
        raise HTTPException(status_code=400, detail="Danh sách inputs không được để trống.")
    if len(req.inputs) > 500:
        raise HTTPException(status_code=400, detail="Vui lòng gửi tối đa 500 mục mỗi lần gọi API.")

    raw_items = [str(x).strip() for x in req.inputs if str(x).strip()]
    if not raw_items:
        raise HTTPException(status_code=400, detail="Không có item hợp lệ nào.")

    speed_map = {
        "An toàn": (6.0, 12.0),
        "Vừa": (3.0, 8.0),
        "Nhanh": (1.5, 4.0)
    }
    min_delay, max_delay = speed_map.get(req.speed, (3.0, 8.0))

    server_serper = load_serper_keys()
    serper_keys = req.serper_api_keys or server_serper
    server_proxies = load_proxies()

    settings = RunSettings(
        min_delay=min_delay,
        max_delay=max_delay,
        use_cache=False if req.force_refresh else req.use_cache,
        headless=True,
        proxies=server_proxies,
        concurrency=max(1, min(5, req.concurrency)),
    )

    results: list[TrafficResult] = []

    def on_progress(done: int, total: int, res: TrafficResult):
        results.append(res)

    run_auto_batch(
        raw_items,
        serper_keys,
        settings=settings,
        progress_cb=on_progress,
    )

    output_data = []
    for r in results:
        b_name = r.brand or r.domain
        output_data.append(TrafficItem(
            input=b_name,
            brand_name=b_name,
            domain=r.domain,
            total_visits=r.monthly_visits_raw or "N/A",
            monthly_visits_raw=r.monthly_visits_raw or "N/A",
            change=r.change or "N/A",
            trend=r.trend or "N/A",
            pages_per_visit=r.pages_per_visit or "N/A",
            avg_duration=r.avg_duration or "N/A",
            bounce_rate=r.bounce_rate or "N/A",
            top_regions=r.top_regions,
            top_keywords=r.top_keywords,
            status=r.status,
            cache_hit=r.cache_hit
        ))

    return CheckResponse(
        status="success",
        total_inputs=len(output_data),
        data=output_data
    )
