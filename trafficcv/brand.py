"""Tìm website chính thức của một brand qua Serper.dev (Google Search API).

Dịch sát logic Google Apps Script `TIM_WEB_TOI_UU` của người dùng:
- Quét tối đa 6 kết quả organic đầu tiên.
- Bỏ social/marketplace/review/streaming/báo-tổng-hợp (BLACKLIST).
- Lấy ROOT domain của link sạch đầu tiên (cắt từ dấu / thứ 3) → domain trần.
- Xoay vòng nhiều API key; key nào hết lượt/unauthorized thì sang key kế tiếp.
"""

from __future__ import annotations

import difflib
import os
import re
from pathlib import Path
from typing import Optional

import httpx

from .scraper import normalize_domain
from urllib.parse import urlparse

SERPER_URL = "https://google.serper.dev/search"
DEFAULT_KEYS_FILE = str(Path(__file__).resolve().parent.parent / "serper_keys.txt")

# Lấy phần "https://host" (đến dấu / thứ 3) như script gốc.
_ROOT_RE = re.compile(r"^(https?://[^/]+)", re.I)

# DANH SÁCH LOẠI TRỪ (bê nguyên từ script TIM_WEB_TOI_UU).
BLACKLIST = [
    # Mạng xã hội
    "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "youtube.com", "pinterest.com", "reddit.com", "tiktok.com", "vimeo.com",
    # Sàn TMĐT & kho ứng dụng
    "shopee.vn", "lazada.vn", "tiki.vn", "amazon.com", "ebay.com",
    "apple.com/app-store", "play.google.com", "apkpure.com",
    # Trang đánh giá & tín nhiệm
    "trustpilot.com", "reviews.io", "sitejabber.com", "yelp.com",
    "tripadvisor.com", "g2.com", "capterra.com", "trustradius.com",
    # Streaming & âm nhạc
    "spotify.com", "apple.com/apple-music", "music.apple.com",
    "soundcloud.com", "deezer.com", "tidal.com", "pandora.com",
    # Báo chí & tổng hợp
    "wikipedia.org", "quora.com", "medium.com", "google.com", "fandom.com",
]


class SerperExhausted(RuntimeError):
    """Tất cả API key đều hết lượt / unauthorized."""


def load_serper_keys(path: str = DEFAULT_KEYS_FILE) -> list[str]:
    """Đọc list key từ file (mỗi dòng 1 key, bỏ dòng trống/#); fallback env SERPER_API_KEYS."""
    keys: list[str] = []
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                keys.append(line)
    if not keys:
        env = os.getenv("SERPER_API_KEYS", "")
        keys = [k.strip() for k in re.split(r"[\s,]+", env) if k.strip()]
    return keys


# Tách blacklist: entry có "/" là theo ĐƯỜNG DẪN (vd apple.com/app-store),
# còn lại là theo TÊN MIỀN (so khớp host có ranh giới, tránh loại oan netflix.com vì "x.com").
_HOST_BLACK = frozenset(e for e in BLACKLIST if "/" not in e)
_PATH_BLACK = tuple(e for e in BLACKLIST if "/" in e)


def _host_of(link: str) -> str:
    try:
        netloc = urlparse(link if "//" in link else "http://" + link).netloc.lower()
    except Exception:
        return ""
    host = netloc.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _is_trash(link: str) -> bool:
    low = (link or "").lower()
    if any(p in low for p in _PATH_BLACK):       # social/store theo đường dẫn cụ thể
        return True
    host = _host_of(link)
    if not host:
        return False
    # chỉ loại khi host ĐÚNG là domain đen hoặc là subdomain của nó
    return any(host == b or host.endswith("." + b) for b in _HOST_BLACK)


# Token chung chung, không tính là "giống tên brand".
_STOP = {"shop", "store", "official", "online", "home", "shoes", "brand",
         "group", "company", "the", "www", "app", "store"}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _domain_core(domain: str) -> str:
    """Phần chính của domain (bỏ TLD cuối): 'snogaathletics.com' -> 'snogaathletics'."""
    parts = (domain or "").split(".")
    return _slug("".join(parts[:-1]) if len(parts) > 1 else domain)


def _is_similar(brand: str, domain: str) -> bool:
    """Domain có 'giống' tên brand không (để chọn khi kết quả đầu là mạng xã hội)."""
    bs = _slug(brand)
    dc = _domain_core(domain)
    if not bs or not dc:
        return False
    if bs in dc or dc in bs:
        return True
    toks = [t for t in re.findall(r"[a-z0-9]+", (brand or "").lower())
            if len(t) >= 4 and t not in _STOP]
    if any(t in dc for t in toks):
        return True
    return difflib.SequenceMatcher(None, bs, dc).ratio() >= 0.6


def _root_domain(link: str) -> Optional[str]:
    """Lấy root domain (cắt bỏ path + phần sau dấu ?), trả domain trần."""
    m = _ROOT_RE.match(link or "")
    return normalize_domain(m.group(1)) if m else None


def _pick_clean_domain(organic: list[dict], brand: str = "", limit: int = 10) -> Optional[str]:
    """Chọn website chính thức (đã bỏ social/rác, cắt ?query/path).

    Ưu tiên domain có tên GIỐNG tên brand — tránh trường hợp kết quả đầu là QUẢNG CÁO
    (Google Shopping, param srsltid) của một shop khác đang chạy ads trên từ khoá brand.
    Nếu không domain nào giống tên brand → lấy kết quả sạch đầu tiên.
    """
    clean: list[str] = []
    for item in organic[:limit]:
        link = item.get("link") or ""
        dom = _root_domain(link)
        if dom and not _is_trash(link) and dom not in clean:
            clean.append(dom)
    if not clean:
        return None
    if brand:
        for dom in clean:
            if _is_similar(brand, dom):
                return dom
    return clean[0]


def find_website(
    brand: str,
    keys: list[str],
    num: int = 10,
    timeout: float = 15.0,
    client: Optional[httpx.Client] = None,
) -> Optional[str]:
    """Trả về domain trần của website chính thức, hoặc None nếu không tìm thấy.

    Ném :class:`SerperExhausted` nếu tất cả key đều lỗi/hết lượt.
    """
    brand = (brand or "").strip()
    if not brand:
        return None
    if not keys:
        raise SerperExhausted("Chưa có Serper API key")

    payload = {"q": brand, "num": num}
    own_client = client is None
    cl = client or httpx.Client(timeout=timeout)
    try:
        for key in keys:
            try:
                resp = cl.post(SERPER_URL, json=payload, headers={"X-API-KEY": key})
            except Exception:
                continue  # lỗi mạng tạm thời → thử key khác
            try:
                data = resp.json()
            except Exception:
                data = {}
            msg = str(data.get("message", "")).lower()
            if resp.status_code != 200 or "unauthorized" in msg:
                continue  # key hỏng/hết lượt → key kế tiếp
            organic = data.get("organic") or []
            if organic:
                return _pick_clean_domain(organic, brand=brand, limit=num)
            return None  # truy vấn OK nhưng không có kết quả sạch
        # không key nào trả 200
        raise SerperExhausted("Hết lượt / sai tất cả Serper API key")
    finally:
        if own_client:
            cl.close()


if __name__ == "__main__":
    import sys
    ks = load_serper_keys()
    print(f"{len(ks)} key.")
    for b in sys.argv[1:] or ["Atoms shoes"]:
        print(f"{b!r} -> {find_website(b, ks)}")
