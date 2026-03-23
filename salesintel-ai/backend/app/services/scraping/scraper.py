"""
Main Scraper Orchestrator — 5-Strategy Waterfall.

Strategy 1: Fast HTTP (httpx)
Strategy 2: Playwright Headless
Strategy 3: Playwright + Rotating Proxy
Strategy 4: Google Cache Fallback
Strategy 5: Manual Flag

Each strategy has exponential backoff (2s → 4s → 8s) before escalating.
Total timeout: 120s per company.
"""
import asyncio
import time
import structlog
from urllib.parse import urlparse
from typing import Optional

from app.services.scraping.http_scraper import HTTPScraper
from app.services.scraping.playwright_scraper import PlaywrightScraper
from app.services.scraping.proxy_manager import ProxyManager
from app.services.scraping.content_extractor import ContentExtractor
from app.services.scraping.page_crawler import PageCrawler

logger = structlog.get_logger("scraping.orchestrator")

# Minimum body content length to consider a successful scrape
MIN_CONTENT_LENGTH = 2000


class ScrapeResult:
    """Result of a scraping operation."""

    def __init__(self):
        self.success: bool = False
        self.html: Optional[str] = None
        self.text: str = ""
        self.combined_text: str = ""
        self.word_count: int = 0
        self.pages_scraped: int = 0
        self.strategy_used: str = ""
        self.strategy_log: list[dict] = []
        self.error: Optional[str] = None
        self.error_code: Optional[str] = None
        self.duration_seconds: float = 0.0
        self.flags: dict = {}

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "text": self.text,
            "combined_text": self.combined_text,
            "word_count": self.word_count,
            "pages_scraped": self.pages_scraped,
            "strategy_used": self.strategy_used,
            "strategy_log": self.strategy_log,
            "error": self.error,
            "error_code": self.error_code,
            "duration_seconds": self.duration_seconds,
            "flags": self.flags,
        }


class ScraperOrchestrator:
    """
    5-strategy waterfall scraper with exponential backoff.
    Designed to handle EVERY type of website.
    """

    def __init__(self):
        self.http_scraper = HTTPScraper(timeout=30.0)
        self.playwright_scraper = PlaywrightScraper(timeout=30000)
        self.proxy_manager = ProxyManager()
        self.extractor = ContentExtractor()
        self.page_crawler = PageCrawler()

    async def scrape_company(
        self,
        url: str,
        company_name: str = "",
        on_progress: Optional[callable] = None,
    ) -> ScrapeResult:
        """
        Scrape a company website using the 5-strategy waterfall.

        Args:
            url: The website URL to scrape
            company_name: Company name for logging
            on_progress: Optional callback for progress updates

        Returns: ScrapeResult with all scrape data
        """
        result = ScrapeResult()
        start_time = time.time()
        total_timeout = 120.0  # 2 minutes max per company

        domain = urlparse(url).netloc

        strategies = [
            ("httpx", self._strategy_httpx),
            ("playwright", self._strategy_playwright),
            ("playwright_proxy", self._strategy_playwright_proxy),
            ("google_cache", self._strategy_google_cache),
            ("manual_flag", self._strategy_manual_flag),
        ]

        html = None

        for strategy_name, strategy_fn in strategies:
            elapsed = time.time() - start_time
            if elapsed > total_timeout:
                logger.warning("total_timeout_exceeded", url=url, elapsed=elapsed)
                break

            if on_progress:
                await on_progress(f"Trying {strategy_name} for {company_name}...")

            logger.info(
                "trying_strategy",
                strategy=strategy_name,
                url=url,
                company=company_name,
            )

            strategy_start = time.time()
            strategy_result = await self._try_with_backoff(
                strategy_fn, url, domain, max_retries=3
            )
            strategy_duration = time.time() - strategy_start

            # Log strategy attempt
            result.strategy_log.append({
                "strategy": strategy_name,
                "success": strategy_result.get("success", False),
                "status_code": strategy_result.get("status_code"),
                "body_length": len(strategy_result.get("html", "") or ""),
                "error": strategy_result.get("error"),
                "error_code": strategy_result.get("error_code"),
                "duration_seconds": round(strategy_duration, 2),
            })

            if strategy_result.get("html"):
                # Check if content is substantial enough
                extracted = self.extractor.extract(strategy_result["html"], url)

                if extracted.get("flags", {}).get("parked_domain"):
                    result.error = "Domain is parked or for sale"
                    result.error_code = "domain_parked"
                    result.flags["parked_domain"] = True
                    result.duration_seconds = time.time() - start_time
                    return result

                if extracted["word_count"] >= 50:
                    html = strategy_result["html"]
                    result.strategy_used = strategy_name
                    result.text = extracted["text"]
                    result.word_count = extracted["word_count"]
                    result.flags = extracted.get("flags", {})
                    logger.info(
                        "strategy_success",
                        strategy=strategy_name,
                        url=url,
                        word_count=extracted["word_count"],
                    )
                    break

            # If we get a terminal error, don't try other strategies
            error_code = strategy_result.get("error_code", "")
            if error_code in ("dns_failure", "domain_parked"):
                result.error = strategy_result.get("error")
                result.error_code = error_code
                result.duration_seconds = time.time() - start_time
                return result

        if not html:
            result.error = result.strategy_log[-1].get("error") if result.strategy_log else "All strategies failed"
            result.error_code = result.strategy_log[-1].get("error_code") if result.strategy_log else "all_failed"
            result.duration_seconds = time.time() - start_time
            return result

        # Multi-page crawling
        if on_progress:
            await on_progress(f"Crawling internal pages for {company_name}...")

        try:
            crawl_result = await self.page_crawler.crawl(url, html, max_pages=8)
            result.combined_text = crawl_result["combined_text"]
            result.word_count = crawl_result["total_words"]
            result.pages_scraped = len(crawl_result["pages"])
        except Exception as e:
            logger.warning("crawl_error", url=url, error=str(e))
            # Fall back to homepage-only content
            result.combined_text = result.text
            result.pages_scraped = 1

        result.success = True
        result.duration_seconds = time.time() - start_time

        logger.info(
            "scrape_complete",
            url=url,
            company=company_name,
            strategy=result.strategy_used,
            word_count=result.word_count,
            pages=result.pages_scraped,
            duration=round(result.duration_seconds, 2),
        )

        return result

    async def _try_with_backoff(
        self, strategy_fn, url: str, domain: str, max_retries: int = 3
    ) -> dict:
        """Try a strategy with exponential backoff."""
        backoff_delays = [2, 4, 8]

        for attempt in range(max_retries):
            result = await strategy_fn(url, domain)
            if result.get("html") or result.get("error_code") in ("dns_failure", "domain_parked"):
                return result

            if attempt < max_retries - 1:
                delay = backoff_delays[min(attempt, len(backoff_delays) - 1)]
                logger.debug(
                    "backoff_retry",
                    strategy=strategy_fn.__name__,
                    attempt=attempt + 1,
                    delay=delay,
                )
                await asyncio.sleep(delay)

        return result

    # ─── Strategy Implementations ───

    async def _strategy_httpx(self, url: str, domain: str) -> dict:
        """Strategy 1: Fast HTTP with httpx."""
        result = await self.http_scraper.fetch(url)
        html = result.get("html", "")
        return {
            "html": html if html and len(html) > MIN_CONTENT_LENGTH else None,
            "status_code": result.get("status_code"),
            "error": result.get("error"),
            "error_code": result.get("error_code"),
            "success": bool(html and len(html) > MIN_CONTENT_LENGTH),
        }

    async def _strategy_playwright(self, url: str, domain: str) -> dict:
        """Strategy 2: Playwright headless with stealth."""
        result = await self.playwright_scraper.fetch(url)
        return {
            "html": result.get("html"),
            "status_code": result.get("status_code"),
            "error": result.get("error"),
            "error_code": result.get("error_code"),
            "success": bool(result.get("html")),
        }

    async def _strategy_playwright_proxy(self, url: str, domain: str) -> dict:
        """Strategy 3: Playwright with rotating proxy."""
        if not self.proxy_manager.has_proxies():
            return {
                "html": None,
                "error": "No proxies configured",
                "error_code": "no_proxy",
                "success": False,
            }

        proxy = self.proxy_manager.get_proxy(domain)
        if not proxy:
            return {
                "html": None,
                "error": "No available proxy",
                "error_code": "no_proxy",
                "success": False,
            }

        # Add randomized delay for anti-bot
        import random
        await asyncio.sleep(random.uniform(2, 5))

        result = await self.playwright_scraper.fetch(url, proxy=proxy)
        return {
            "html": result.get("html"),
            "status_code": result.get("status_code"),
            "error": result.get("error"),
            "error_code": result.get("error_code"),
            "success": bool(result.get("html")),
        }

    async def _strategy_google_cache(self, url: str, domain: str) -> dict:
        """Strategy 4: Google Cache fallback."""
        cache_url = f"https://webcache.googleusercontent.com/search?q=cache:{url}"
        result = await self.http_scraper.fetch(cache_url)
        return {
            "html": result.get("html"),
            "status_code": result.get("status_code"),
            "error": result.get("error"),
            "error_code": result.get("error_code"),
            "success": bool(result.get("html")),
        }

    async def _strategy_manual_flag(self, url: str, domain: str) -> dict:
        """Strategy 5: Flag for manual input — always returns failure with manual flag."""
        logger.warning("manual_flag", url=url, domain=domain)
        return {
            "html": None,
            "error": "All automated strategies failed. Requires manual input.",
            "error_code": "manual_required",
            "success": False,
        }


async def scrape_batch(
    companies: list[dict],
    on_progress: Optional[callable] = None,
    max_concurrent: int = 5,
) -> list[ScrapeResult]:
    """
    Scrape multiple companies concurrently with semaphore control.
    companies: list of {url, name}
    """
    orchestrator = ScraperOrchestrator()
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _scrape_one(company: dict) -> ScrapeResult:
        async with semaphore:
            return await orchestrator.scrape_company(
                url=company["url"],
                company_name=company.get("name", ""),
                on_progress=on_progress,
            )

    tasks = [_scrape_one(c) for c in companies]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            sr = ScrapeResult()
            sr.error = str(r)
            sr.error_code = "exception"
            output.append(sr)
        else:
            output.append(r)
    return output
