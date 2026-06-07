"""Chuẩn hóa input + parse kết quả từ trang bulk của traffic.cv.

Bố cục text mỗi card kết quả (sau khi render):

    <domain>
    ... (mô tả/quảng cáo) ...
    Total Visits
    84.75B-2.42%          <- lượt truy cập/tháng (kèm % thay đổi)
    Avg. Duration
    00:10:13
    Pages per Visit
    8.72
    Bounce Rate
    28.22%
    ...

Parser bám vào các NHÃN tiếng Anh (ổn định) thay vì class CSS (bị hash, hay đổi).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Optional
from urllib.parse import urlparse

_NUM_SUFFIX = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
_NUM_RE = re.compile(r"([0-9][0-9.,]*)\s*([kmb])?", re.I)
# Tách "146.46K-7.47%" -> ("146.46K", "-7.47%")
_RAW_RE = re.compile(r"\s*([0-9][0-9.,]*\s*[kmb]?)\s*([+-]\s*[0-9.,]+%)?", re.I)


def split_visits_raw(raw: str) -> tuple[str, Optional[str]]:
    """Tách chuỗi Visits gốc thành (phần hiển thị, phần % thay đổi)."""
    m = _RAW_RE.match(raw or "")
    if not m:
        return (raw or ""), None
    visits = m.group(1).strip()
    change = (m.group(2) or "").replace(" ", "") or None
    return visits, change


def format_compact(n: Optional[int]) -> Optional[str]:
    """100000 -> '100K', 146460 -> '146.46K', 2510000000 -> '2.51B'."""
    if n is None or n != n:  # None hoặc NaN
        return None
    val = float(n)
    for suffix, scale in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(val) >= scale:
            s = f"{val / scale:.2f}".rstrip("0").rstrip(".")
            return s + suffix
    return str(int(val))


def trend_label(change: Optional[str]) -> str:
    """'+...' -> Tăng, '-...' -> Giảm, còn lại -> ''."""
    if not change:
        return ""
    if change.startswith("+"):
        return "Tăng"
    if change.startswith("-"):
        return "Giảm"
    return ""


@dataclass
class TrafficResult:
    domain: str
    brand: Optional[str] = None                # tên brand (chỉ ở chế độ tìm web từ brand)
    monthly_visits: Optional[int] = None
    monthly_visits_raw: Optional[str] = None   # phần hiển thị, vd "146.46K"
    change: Optional[str] = None               # % thay đổi, vd "-7.47%" / "+13.47%"
    trend: Optional[str] = None                # "Tăng" | "Giảm" | ""
    pages_per_visit: Optional[str] = None
    avg_duration: Optional[str] = None
    bounce_rate: Optional[str] = None
    registration: Optional[str] = None         # ngày đăng ký domain, vd "1999-11-9"
    status: str = "ok"                           # ok | not_found | blocked | error
    error: Optional[str] = None

    def as_row(self) -> dict:
        return asdict(self)


# ---------- chuẩn hóa input ----------
def normalize_domain(raw: str) -> Optional[str]:
    s = (raw or "").strip()
    if not s:
        return None
    if "//" not in s:
        s = "http://" + s
    host = urlparse(s).netloc or urlparse(s).path
    host = host.split("/")[0].split("@")[-1].split(":")[0].strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host if host and "." in host else None


def normalize_list(text: str) -> list[str]:
    parts = re.split(r"[\s,;]+", text or "")
    seen, out = set(), []
    for p in parts:
        d = normalize_domain(p)
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out


_DOMAIN_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,24}$")


def looks_like_domain(line: str) -> bool:
    """True nếu dòng là DOMAIN/URL (vd abc.com, https://abc.com/x); False nếu là TÊN BRAND."""
    s = (line or "").strip().lower()
    if not s:
        return False
    if "://" in s:
        return True
    if any(c.isspace() for c in s):   # tên brand thường có khoảng trắng
        return False
    host = s.split("/")[0].split("?")[0]
    return bool(_DOMAIN_RE.match(host))


def parse_brand_list(text: str) -> list[str]:
    """Tách danh sách (mỗi dòng 1 mục: domain HOẶC tên brand), GIỮ NGUYÊN chữ, bỏ trùng/blank."""
    seen, out = set(), []
    for line in (text or "").splitlines():
        name = line.strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


def chunked(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def filter_results(
    results: list["TrafficResult"],
    min_visits: Optional[int] = None,
    max_visits: Optional[int] = None,
    keep_unknown: bool = True,
    require_website: bool = False,
) -> list["TrafficResult"]:
    """Lọc kết quả theo lượt truy cập/tháng.

    LƯU Ý: chỉ lọc ĐẦU RA, không tăng tốc lần quét (vì phải check mới biết số liệu).

    - ``min_visits`` / ``max_visits``: ngưỡng (None = không giới hạn).
    - ``keep_unknown``: giữ hay bỏ web không có số liệu (not_found / lỗi).
    - ``require_website``: True → bỏ các brand không tìm thấy website (status no_website / domain rỗng).
    """
    out = []
    for r in results:
        if require_website and (r.status == "no_website" or not r.domain):
            continue
        v = r.monthly_visits
        if v is None:
            if keep_unknown:
                out.append(r)
            continue
        if min_visits is not None and v < min_visits:
            continue
        if max_visits is not None and v > max_visits:
            continue
        out.append(r)
    return out


# ---------- chuyển chuỗi số -> int ----------
def parse_number(text: str) -> Optional[int]:
    m = _NUM_RE.search(text or "")
    if not m:
        return None
    num = m.group(1).replace(",", "")
    suffix = (m.group(2) or "").lower()
    try:
        val = float(num)
    except ValueError:
        return None
    if suffix in _NUM_SUFFIX:
        val *= _NUM_SUFFIX[suffix]
    return int(round(val))


# ---------- parse trang bulk ----------
def _value_after(seg: list[str], label: str) -> Optional[str]:
    """Trả về dòng giá trị (không rỗng) ngay sau ``label`` trong đoạn text của card."""
    for j, line in enumerate(seg):
        if line == label:
            for k in range(j + 1, len(seg)):
                if seg[k]:
                    return seg[k]
            return None
    return None


def parse_bulk(body_text: str, requested: list[str]) -> dict[str, TrafficResult]:
    """Bóc kết quả cho từng domain được yêu cầu từ text của trang bulk.

    Domain không xuất hiện trong kết quả (traffic.cv không có dữ liệu) → not_found.
    """
    lines = [l.strip() for l in (body_text or "").splitlines()]
    req_lower = {d.lower(): d for d in requested}

    # Mốc bắt đầu mỗi card = dòng khớp ĐÚNG một domain được yêu cầu (mỗi domain lấy lần đầu).
    cards: list[tuple[int, str]] = []
    seen: set[str] = set()
    for i, line in enumerate(lines):
        dom = req_lower.get(line.lower())
        if dom and dom not in seen:
            seen.add(dom)
            cards.append((i, dom))

    out: dict[str, TrafficResult] = {}
    for idx, (start, dom) in enumerate(cards):
        end = cards[idx + 1][0] if idx + 1 < len(cards) else len(lines)
        seg = lines[start:end]
        raw = _value_after(seg, "Total Visits")
        if raw is None:
            out[dom] = TrafficResult(dom, status="not_found",
                                     error="Không thấy 'Total Visits' trong kết quả")
            continue
        visits_str, change = split_visits_raw(raw)
        out[dom] = TrafficResult(
            domain=dom,
            monthly_visits=parse_number(raw),
            monthly_visits_raw=visits_str,
            change=change,
            trend=trend_label(change),
            pages_per_visit=_value_after(seg, "Pages per Visit"),
            avg_duration=_value_after(seg, "Avg. Duration"),
            bounce_rate=_value_after(seg, "Bounce Rate"),
            registration=_value_after(seg, "Registration"),
        )

    # Domain được yêu cầu nhưng không có card nào.
    for dom in requested:
        out.setdefault(dom, TrafficResult(dom, status="not_found",
                                          error="Không có trong kết quả trả về"))
    return out


def get_traffic_bulk(session, domains_chunk: list[str]) -> dict[str, TrafficResult]:
    """Lấy traffic cho tối đa 10 domain qua một lần mở trang bulk."""
    from .browser import ChallengeBlocked
    try:
        text = session.fetch_bulk(domains_chunk)
    except ChallengeBlocked as e:
        return {d: TrafficResult(d, status="blocked", error=str(e)) for d in domains_chunk}
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"
        return {d: TrafficResult(d, status="error", error=msg) for d in domains_chunk}
    return parse_bulk(text, domains_chunk)


if __name__ == "__main__":
    # python -m trafficcv.scraper google.com youtube.com vnexpress.net
    import sys
    from .browser import BrowserSession

    doms = [d for d in (normalize_domain(a) for a in sys.argv[1:]) if d] or ["google.com"]
    with BrowserSession(headless=True) as s:
        for chunk in chunked(doms, 10):
            for d, r in get_traffic_bulk(s, chunk).items():
                print(r.as_row())
