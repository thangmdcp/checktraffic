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
    top_regions: Optional[list[dict]] = None    # Top 5 quốc gia: [{"country": "US", "share": "25.02%"}]
    top_keywords: Optional[list[dict]] = None   # Top 5 từ khóa: [{"keyword": "...", "traffic": "...", "volume": "...", "cpc": "..."}]
    status: str = "ok"                           # ok | not_found | blocked | error
    error: Optional[str] = None
    cache_hit: bool = False

    def as_row(self) -> dict:
        return asdict(self)


def parse_domain_details(text: str) -> tuple[list[dict], list[dict]]:
    """Parse text từ trang đơn https://traffic.cv/<domain> để bóc Top Regions & Top Keywords."""
    regions: list[dict] = []
    keywords: list[dict] = []

    if not text:
        return regions, keywords

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # 1. Parse Top Regions
    try:
        if "TOP REGIONS" in text.upper():
            idx = -1
            for i, line in enumerate(lines):
                if "TOP REGIONS" in line.upper():
                    idx = i
                    break
            if idx != -1:
                curr = idx + 1
                while curr < len(lines) and len(regions) < 5:
                    line = lines[curr]
                    if "TOP KEYWORDS" in line.upper():
                        break
                    if curr + 1 < len(lines) and re.match(r"^[0-9.]+\s*%$", lines[curr + 1]):
                        country = line
                        share = lines[curr + 1]
                        if country.lower() not in ("region", "share", "traffic %", "top regions"):
                            regions.append({"country": country, "share": share})
                        curr += 2
                    else:
                        curr += 1
    except Exception:
        pass

    # 2. Parse Top Keywords
    try:
        if "TOP KEYWORDS" in text.upper():
            idx = -1
            for i, line in enumerate(lines):
                if "TOP KEYWORDS" in line.upper():
                    idx = i
                    break
            if idx != -1:
                curr = idx + 1
                while curr < len(lines) and len(keywords) < 5:
                    line = lines[curr]
                    if line.lower() in ("keyword", "traffic", "volume", "cpc", "top keywords"):
                        curr += 1
                        continue
                    m = re.search(r"^(.*?)\s+([0-9.,]+[KMB]?)\s+([0-9.,]+[KMB]?)\s+(\$?[0-9.,]+)$", line, re.I)
                    if m:
                        keywords.append({
                            "keyword": m.group(1).strip(),
                            "traffic": m.group(2).strip(),
                            "volume": m.group(3).strip(),
                            "cpc": m.group(4).strip()
                        })
                        curr += 1
                    elif curr + 3 < len(lines):
                        kw = line
                        trf = lines[curr + 1]
                        vol = lines[curr + 2]
                        cpc = lines[curr + 3]
                        if re.match(r"^[0-9.,]+[KMB]?$", trf, re.I) and re.match(r"^\$?[0-9.,]+$", cpc, re.I):
                            keywords.append({
                                "keyword": kw,
                                "traffic": trf,
                                "volume": vol,
                                "cpc": cpc
                            })
                            curr += 4
                        else:
                            curr += 1
                    else:
                        curr += 1
    except Exception:
        pass

    return regions, keywords


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
    """Trả về dòng giá trị (không rỗng) ngay sau ``label`` (không phân biệt hoa thường)."""
    lbl_lower = label.lower().strip()
    for j, line in enumerate(seg):
        if lbl_lower in line.lower():
            for k in range(j + 1, len(seg)):
                if seg[k].strip():
                    return seg[k].strip()
            return None
    return None


def extract_visits_and_change(seg: list[str]) -> tuple[Optional[str], Optional[str]]:
    """Tách Total Visits và % thay đổi (cho dù nằm chung dòng hay khác dòng)."""
    for j, line in enumerate(seg):
        l_low = line.lower()
        if "total visits" in l_low or "visits" in l_low or "monthly visits" in l_low:
            if j + 1 < len(seg):
                raw1 = seg[j + 1].strip()
                visits_str, change = split_visits_raw(raw1)
                if not change and j + 2 < len(seg):
                    raw2 = seg[j + 2].strip()
                    if re.match(r"^[+-]?\s*[0-9.,]+%$", raw2):
                        change = raw2.replace(" ", "")
                return visits_str, change
    return None, None


def parse_bulk(body_text: str, requested: list[str]) -> dict[str, TrafficResult]:
    """Bóc kết quả cho từng domain được yêu cầu từ text của trang bulk."""
    lines = [l.strip() for l in (body_text or "").splitlines() if l.strip()]
    req_lower = {d.lower(): d for d in requested}

    cards: list[tuple[int, str]] = []
    seen: set[str] = set()

    for i, line in enumerate(lines):
        line_clean = line.lower()
        matched_dom = None
        if line_clean in req_lower:
            matched_dom = req_lower[line_clean]
        else:
            norm = normalize_domain(line)
            if norm and norm in req_lower:
                matched_dom = req_lower[norm]
            else:
                for rd in req_lower:
                    if rd in line_clean or (len(line_clean) >= 4 and "." in line_clean and line_clean in rd):
                        matched_dom = req_lower[rd]
                        break

        if matched_dom and matched_dom not in seen:
            seen.add(matched_dom)
            cards.append((i, matched_dom))

    out: dict[str, TrafficResult] = {}
    for idx, (start, dom) in enumerate(cards):
        end = cards[idx + 1][0] if idx + 1 < len(cards) else len(lines)
        seg = lines[start:end]

        visits_str, change = extract_visits_and_change(seg)
        if visits_str is None:
            out[dom] = TrafficResult(dom, status="not_found", error="Không thấy Total Visits")
            continue

        raw_num = f"{visits_str}{change or ''}"
        out[dom] = TrafficResult(
            domain=dom,
            monthly_visits=parse_number(visits_str),
            monthly_visits_raw=visits_str,
            change=change,
            trend=trend_label(change),
            pages_per_visit=_value_after(seg, "Pages per Visit"),
            avg_duration=_value_after(seg, "Avg. Duration"),
            bounce_rate=_value_after(seg, "Bounce Rate"),
            registration=_value_after(seg, "Registered") or _value_after(seg, "Registration"),
        )

    for dom in requested:
        out.setdefault(dom, TrafficResult(dom, status="not_found", error="Không có trong kết quả trả về"))

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
