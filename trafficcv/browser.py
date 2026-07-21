"""Phiên trình duyệt Playwright để lấy dữ liệu từ trang bulk của traffic.cv.

Phát hiện quan trọng: trang https://traffic.cv/bulk KHÔNG bị Cloudflare Turnstile
(khác với route /<domain>). Có thể vào thẳng URL::

    https://traffic.cv/bulk?domains=a.com,b.com,...   (tối đa 10 domain/lần)

và kết quả được render ngay (chạy headless cũng được). Nhờ vậy app chạy **tự động
hoàn toàn, không cần giải tay, deploy online được**.
"""

from __future__ import annotations

import os
from typing import Optional
from urllib.parse import quote

from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout
from playwright_stealth import Stealth

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

BASE_URL = "https://traffic.cv"
BULK_MAX = 10  # traffic.cv chỉ trả tối đa 10 domain mỗi lần

# Dấu hiệu (phòng xa) nếu trang bị Cloudflare chặn.
_CHALLENGE_MARKERS = ("just a moment", "performing security verification",
                      "checking your browser", "attention required")


def is_challenge_page(page: Page) -> bool:
    try:
        title = (page.title() or "").strip().lower()
        if any(m in title for m in _CHALLENGE_MARKERS):
            return True
        body = (page.inner_text("body") or "").strip().lower()[:400]
        return any(m in body for m in _CHALLENGE_MARKERS)
    except Exception:
        return False


class ChallengeBlocked(RuntimeError):
    """Phòng xa: ném ra nếu trang bulk bất ngờ bị Cloudflare chặn."""

    def __init__(self, url: str):
        super().__init__(f"Bị Cloudflare chặn khi mở {url}.")
        self.url = url


class BrowserSession:
    """Một phiên Chromium headless dùng chung cho cả lô.

        with BrowserSession() as s:
            text = s.fetch_bulk(["google.com", "youtube.com"])
    """

    def __init__(
        self,
        headless: Optional[bool] = None,
        proxy: Optional[str] = None,
        user_agent: str = DEFAULT_UA,
        nav_timeout: float = 60.0,
        render_wait_ms: int = 6000,
    ):
        if headless is None:
            headless = os.getenv("TRAFFICCV_HEADLESS", "1") != "0"
        self.headless = headless
        self.proxy = proxy or os.getenv("TRAFFICCV_PROXY") or None
        self.user_agent = user_agent
        self.nav_timeout = nav_timeout * 1000
        self.render_wait_ms = render_wait_ms

        self._stealth_cm = None
        self._pw = None
        self._browser = None
        self._context = None
        self.page: Optional[Page] = None

    def __enter__(self) -> "BrowserSession":
        self._stealth_cm = Stealth().use_sync(sync_playwright())
        self._pw = self._stealth_cm.__enter__()
        launch_args = {
            "headless": self.headless,
            "args": ["--no-sandbox", "--disable-dev-shm-usage",
                     "--disable-blink-features=AutomationControlled"],
        }
        if self.proxy:
            launch_args["proxy"] = {"server": self.proxy}
        self._browser = self._pw.chromium.launch(**launch_args)
        self._context = self._browser.new_context(
            user_agent=self.user_agent, locale="en-US",
            viewport={"width": 1366, "height": 900},
            timezone_id="Asia/Ho_Chi_Minh",
        )
        self._context.set_default_navigation_timeout(self.nav_timeout)
        self.page = self._context.new_page()
        return self

    def __exit__(self, *exc):
        for c in (self._context, self._browser):
            try:
                if c:
                    c.close()
            except Exception:
                pass
        try:
            if self._stealth_cm:
                self._stealth_cm.__exit__(*exc)
        except Exception:
            pass
        return False

    def fetch_bulk(self, domains: list[str]) -> str:
        """Mở /bulk cho tối đa 10 domain, trả về inner_text của body sau khi render."""
        if not domains:
            return ""
        chunk = domains[:BULK_MAX]
        url = f"{BASE_URL}/bulk?domains=" + quote(",".join(chunk), safe=",")
        page = self.page
        assert page is not None
        page.goto(url, wait_until="domcontentloaded")
        if is_challenge_page(page):
            raise ChallengeBlocked(url)
        # Đợi React render xong các card kết quả.
        page.wait_for_timeout(self.render_wait_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except PWTimeout:
            pass
        return page.inner_text("body")

    def fetch_domain_details(self, domain: str) -> str:
        """Mở trang https://traffic.cv/<domain> trên tab tạm thời để lấy Top Regions & Keywords."""
        if not domain or not self._context:
            return ""
        url = f"{BASE_URL}/{quote(domain.strip())}"
        detail_page = None
        try:
            detail_page = self._context.new_page()
            detail_page.goto(url, wait_until="domcontentloaded", timeout=6000)
            if is_challenge_page(detail_page):
                detail_page.close()
                return ""
            detail_page.wait_for_timeout(2000)
            text = detail_page.inner_text("body")
            detail_page.close()
            return text
        except Exception:
            if detail_page:
                try:
                    detail_page.close()
                except Exception:
                    pass
            return ""
