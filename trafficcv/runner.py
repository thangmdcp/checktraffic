"""Quét cả danh sách domain qua trang bulk: chia lô 10, cache, giới hạn tốc độ.

Tối ưu cho list lớn (10k+):
- Lọc trước domain đã có trong cache (còn hạn) → chỉ gọi mạng phần còn lại.
- Chia lô 10, nghỉ ngẫu nhiên giữa các lô.
- **Auto-backoff**: nếu liên tiếp gặp lô bị chặn → nghỉ dài (cooldown) và đổi proxy.
- **Khởi động lại trình duyệt định kỳ** (restart_every) để tránh rò bộ nhớ khi chạy nhiều giờ.
- **Xoay vòng proxy** nếu có (mỗi lô một IP); không có proxy thì dùng IP mạng nhà.
- Kết quả lưu cache sau mỗi lô → tắt giữa chừng rồi chạy lại sẽ tự bỏ qua phần đã xong.
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import httpx

from .browser import BrowserSession, BULK_MAX
from .cache import Cache
from .scraper import (TrafficResult, get_traffic_bulk, normalize_list, normalize_domain,
                      parse_brand_list, parse_domain_details, looks_like_domain, chunked)
from .brand import find_website, SerperExhausted

ProgressCb = Callable[[int, int, TrafficResult], None]
# resolve_cb(done, total, brand, domain_or_None)
ResolveCb = Callable[[int, int, str, Optional[str]], None]
BatchCb = Callable[[int, int, list], None]  # (batch_done, batch_total, batch_results)

DEFAULT_PROXIES_FILE = str(Path(__file__).resolve().parent.parent / "proxies.txt")


def load_proxies(path: str = DEFAULT_PROXIES_FILE) -> list[str]:
    """Đọc danh sách proxy từ file (mỗi dòng một proxy, bỏ dòng trống/#).

    Nếu không có file thì thử biến môi trường TRAFFICCV_PROXY (một proxy).
    """
    proxies: list[str] = []
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                proxies.append(line)
    if not proxies:
        env = os.getenv("TRAFFICCV_PROXY")
        if env:
            proxies.append(env)
    return proxies


@dataclass
class RunSettings:
    min_delay: float = 3.0          # nghỉ giữa các lô (giây)
    max_delay: float = 8.0
    use_cache: bool = True
    ttl: int = 90 * 24 * 3600
    headless: bool = True
    proxies: Optional[list[str]] = None   # None/[] = không dùng proxy
    restart_every: int = 40               # khởi động lại trình duyệt sau mỗi N lô
    backoff_after: int = 2                # số lô-bị-chặn liên tiếp trước khi nghỉ dài
    cooldown: float = 90.0                # thời gian nghỉ dài khi nghi bị chặn (giây)


@dataclass
class BatchOutcome:
    results: list[TrafficResult] = field(default_factory=list)
    cancelled: bool = False
    aborted_reason: Optional[str] = None
    from_cache: int = 0
    fetched: int = 0
    blocked_batches: int = 0


def _is_bad_batch(results: list[TrafficResult]) -> bool:
    """Lô 'xấu' = có dấu hiệu bị chặn (status blocked) hoặc toàn bộ lỗi."""
    if not results:
        return True
    if any(r.status == "blocked" for r in results):
        return True
    return all(r.status == "error" for r in results)


def run_batch(
    domains_or_text,
    settings: Optional[RunSettings] = None,
    progress_cb: Optional[ProgressCb] = None,
    batch_cb: Optional[BatchCb] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    seed: Optional[int] = None,
) -> BatchOutcome:
    settings = settings or RunSettings()
    rng = random.Random(seed)
    proxies = settings.proxies or []

    domains = (normalize_list(domains_or_text)
               if isinstance(domains_or_text, str) else list(domains_or_text))
    outcome = BatchOutcome()
    total = len(domains)
    if total == 0:
        return outcome

    cache = Cache(ttl=settings.ttl)
    done = 0

    def emit(res: TrafficResult):
        nonlocal done
        done += 1
        outcome.results.append(res)
        if progress_cb:
            progress_cb(done, total, res)

    session: Optional[BrowserSession] = None
    current_proxy = object()  # sentinel khác mọi proxy thật

    def close_session():
        nonlocal session
        if session is not None:
            try:
                session.__exit__(None, None, None)
            except Exception:
                pass
            session = None

    try:
        # 1) Lấy trước từ cache.
        to_fetch: list[str] = []
        for d in domains:
            cached = cache.get(d) if settings.use_cache else None
            if cached is not None:
                outcome.from_cache += 1
                emit(cached)
            else:
                to_fetch.append(d)

        if not to_fetch:
            return outcome

        # 2) Gọi traffic.cv theo lô 10.
        batches = chunked(to_fetch, BULK_MAX)
        proxy_idx = 0
        consecutive_bad = 0

        for bi, chunk in enumerate(batches):
            if should_stop and should_stop():
                outcome.cancelled = True
                break

            try:
                # chọn proxy cho lô này (xoay vòng nếu có nhiều)
                proxy = proxies[proxy_idx % len(proxies)] if proxies else None
                need_new = (
                    session is None
                    or proxy != current_proxy
                    or (bi > 0 and settings.restart_every and bi % settings.restart_every == 0)
                )
                if need_new:
                    close_session()
                    session = BrowserSession(headless=settings.headless, proxy=proxy)
                    session.__enter__()
                    current_proxy = proxy

                results_map = get_traffic_bulk(session, chunk)
                batch_results = [results_map.get(
                    d, TrafficResult(d, status="error", error="Thiếu kết quả")) for d in chunk]

                # Emit và lưu cache ngay lập tức để UI không bị chờ
                for res in batch_results:
                    cache.put(res)
                    outcome.fetched += 1
                    emit(res)
                if batch_cb:
                    batch_cb(bi + 1, len(batches), batch_results)

                # Chỉ cào thêm Top Regions & Keywords khi người dùng check ĐÚNG 1 LINK DUY NHẤT
                if session and len(domains) == 1:
                    for res in batch_results:
                        if res.status == "ok" and not res.top_regions:
                            try:
                                dt_text = session.fetch_domain_details(res.domain)
                                if dt_text:
                                    regs, kws = parse_domain_details(dt_text)
                                    if regs:
                                        res.top_regions = regs
                                    if kws:
                                        res.top_keywords = kws
                                    cache.put(res)
                            except Exception:
                                pass
            except Exception as b_err:
                batch_results = [TrafficResult(d, status="error", error=f"Lỗi: {b_err}") for d in chunk]
                for res in batch_results:
                    outcome.fetched += 1
                    emit(res)
                if batch_cb:
                    batch_cb(bi + 1, len(batches), batch_results)

            # 3) auto-backoff khi nghi bị chặn
            if _is_bad_batch(batch_results):
                consecutive_bad += 1
                outcome.blocked_batches += 1
                if consecutive_bad >= settings.backoff_after:
                    proxy_idx += 1  # đổi proxy (nếu có) cho lần sau
                    close_session()  # buộc mở phiên mới
                    time.sleep(settings.cooldown + rng.uniform(0, 10))
                    consecutive_bad = 0
            else:
                consecutive_bad = 0

            if bi < len(batches) - 1:  # nghỉ ngẫu nhiên giữa các lô
                time.sleep(rng.uniform(settings.min_delay, settings.max_delay))

        return outcome
    finally:
        close_session()
        cache.close()


# Ánh xạ nhãn tốc độ -> (min_delay, max_delay) dùng chung cho app & CLI.
SPEED_PRESETS = {
    "safe": (6.0, 12.0),
    "normal": (3.0, 8.0),
    "fast": (1.5, 4.0),
}


def run_auto_batch(
    lines_or_text,
    serper_keys: list[str],
    settings: Optional[RunSettings] = None,
    resolve_cb: Optional[ResolveCb] = None,
    progress_cb: Optional[ProgressCb] = None,
    batch_cb: Optional[BatchCb] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    resolve_workers: int = 4,
) -> BatchOutcome:
    """Tự nhận diện mỗi dòng là DOMAIN hay TÊN BRAND.

    - Dòng domain (abc.com / URL): Brand = domain, Website = domain (không gọi Serper).
    - Dòng tên brand: tìm website qua Serper → Brand = tên brand, Website = domain tìm được.
    Pha 2: check traffic cho các domain. Mỗi result có .brand (luôn có).
    """
    settings = settings or RunSettings()
    lines = (parse_brand_list(lines_or_text)
             if isinstance(lines_or_text, str) else list(lines_or_text))
    outcome = BatchOutcome()
    if not lines:
        return outcome

    cache = Cache(ttl=settings.ttl)
    exhausted = False

    def resolve_one(line: str) -> tuple[str, Optional[str]]:
        # (label hiển thị ở cột Brand, domain | None)
        if looks_like_domain(line):
            d = normalize_domain(line)
            return (d or line), d
        cached = cache.get_brand(line) if settings.use_cache else None
        if cached:
            return line, cached
        with httpx.Client(timeout=15.0) as cl:
            dom = find_website(line, serper_keys, client=cl)
        if dom:
            cache.put_brand(line, dom)
        return line, dom

    try:
        # ----- Pha 1: nhận diện + resolve (song song nhẹ) -----
        done = 0
        total = len(lines)
        labels: dict[str, str] = {}     # line gốc -> label (Brand)
        result_map: dict[str, Optional[str]] = {}   # line gốc -> domain
        with ThreadPoolExecutor(max_workers=max(1, resolve_workers)) as ex:
            futures = {ex.submit(resolve_one, ln): ln for ln in lines}
            for fut in futures:
                if should_stop and should_stop():
                    outcome.cancelled = True
                    break
                line = futures[fut]
                try:
                    label, dom = fut.result()
                except SerperExhausted:
                    exhausted = True
                    label, dom = line, None
                except Exception:
                    label, dom = line, None
                labels[line] = label
                result_map[line] = dom
                done += 1
                if resolve_cb:
                    resolve_cb(done, total, label, dom)
        pairs = [(labels.get(ln, ln), result_map.get(ln)) for ln in lines]
        if exhausted:
            outcome.aborted_reason = "Hết lượt / sai Serper API key — hãy thêm key mới."

        # ----- Pha 2: check traffic cho các domain tìm được -----
        domains = []
        seen = set()
        for _, dom in pairs:
            if dom and dom not in seen:
                seen.add(dom)
                domains.append(dom)

        by_domain: dict[str, TrafficResult] = {}
        if domains and not (should_stop and should_stop()):
            traffic = run_batch(domains, settings, progress_cb=progress_cb,
                                batch_cb=batch_cb, should_stop=should_stop)
            by_domain = {r.domain: r for r in traffic.results}
            outcome.from_cache = traffic.from_cache
            outcome.fetched = traffic.fetched
            outcome.blocked_batches = traffic.blocked_batches
            outcome.cancelled = outcome.cancelled or traffic.cancelled

        # ----- Ghép kết quả theo thứ tự brand -----
        for brand, dom in pairs:
            if not dom:
                outcome.results.append(TrafficResult(
                    domain="", brand=brand, status="no_website",
                    error="Không tìm thấy website chính thức"))
            else:
                base = by_domain.get(dom)
                if base is not None:
                    outcome.results.append(replace(base, brand=brand))
                else:
                    outcome.results.append(TrafficResult(
                        domain=dom, brand=brand, status="error", error="Thiếu kết quả traffic"))
        return outcome
    finally:
        cache.close()


def count_pending(domains: list[str], ttl: int) -> tuple[int, int]:
    """Trả về (số đã có trong cache còn hạn, số cần gọi mạng)."""
    cache = Cache(ttl=ttl)
    try:
        cached = sum(1 for d in domains if cache.get(d) is not None)
    finally:
        cache.close()
    return cached, len(domains) - cached
