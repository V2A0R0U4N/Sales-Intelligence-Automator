"""
Playwright Scraper — Strategy 2 & 3: Headless browser with stealth and optional proxy.
"""
import re
import structlog
from typing import Optional

logger = structlog.get_logger("scraping.playwright")


class PlaywrightScraper:
    """Async Playwright scraper with stealth patches and lazy-content loading."""

    def __init__(self, timeout: float = 30000):
        self.timeout = timeout  # milliseconds

    async def fetch(self, url: str, proxy: Optional[str] = None) -> dict:
        """
        Fetch URL with headless Chromium + stealth.
        If proxy is provided, routes traffic through it (Strategy 3).
        Returns: {html, status_code, method, error, error_code}
        """
        result = {
            "html": None,
            "status_code": None,
            "method": "playwright" + ("_proxy" if proxy else ""),
            "error": None,
            "error_code": None,
        }

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            result["error"] = "Playwright not installed"
            result["error_code"] = "dependency_missing"
            return result

        try:
            async with async_playwright() as p:
                launch_args = {
                    "headless": True,
                    "args": [
                        "--no-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ],
                }

                if proxy:
                    launch_args["proxy"] = {"server": proxy}

                browser = await p.chromium.launch(**launch_args)

                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1366, "height": 768},
                    locale="en-US",
                    timezone_id="America/New_York",
                    ignore_https_errors=True,
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                        "sec-ch-ua-mobile": "?0",
                        "sec-ch-ua-platform": '"Windows"',
                    },
                )

                page = await context.new_page()

                # Apply stealth patches
                try:
                    from playwright_stealth import stealth_async
                    await stealth_async(page)
                    logger.debug("stealth_applied", url=url)
                except ImportError:
                    logger.debug("stealth_not_available")

                # Block heavy resources
                await page.route(
                    re.compile(r"\.(png|jpg|jpeg|gif|webp|svg|woff2?|ttf|mp4|mp3|avi)$"),
                    lambda route: route.abort(),
                )

                # Navigate
                response = await page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=self.timeout,
                )

                if response:
                    result["status_code"] = response.status

                # Scroll to bottom to trigger lazy-loaded content
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

                # Dismiss popups
                try:
                    await page.keyboard.press("Escape")
                except Exception:
                    pass

                # Get final HTML
                html = await page.content()
                await browser.close()

                if not html or len(html) < 200:
                    result["error"] = "Page returned minimal content"
                    result["error_code"] = "empty_content"
                    result["html"] = html
                    return result

                result["html"] = html
                logger.info(
                    "playwright_fetch_success",
                    url=url,
                    method=result["method"],
                    body_length=len(html),
                )
                return result

        except Exception as e:
            error_str = str(e).lower()
            logger.warning("playwright_fetch_error", url=url, error=str(e))

            if "timeout" in error_str:
                result["error"] = f"Playwright timeout: {e}"
                result["error_code"] = "connection_timeout"
            elif "net::err_name_not_resolved" in error_str:
                result["error"] = "DNS resolution failed"
                result["error_code"] = "dns_failure"
            else:
                result["error"] = str(e)
                result["error_code"] = "playwright_error"

            return result
