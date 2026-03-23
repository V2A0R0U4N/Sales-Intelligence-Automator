"""
Page Crawler — Multi-page internal crawler with explicit paths and HEAD check.
"""
import asyncio
import structlog
from urllib.parse import urljoin, urlparse

from app.services.scraping.http_scraper import HTTPScraper
from app.services.scraping.content_extractor import ContentExtractor

logger = structlog.get_logger("scraping.crawler")

# Explicit paths to always try (from spec)
PRIORITY_PATHS = [
    "/about", "/about-us", "/who-we-are", "/our-story", "/our-company",
    "/services", "/solutions", "/products", "/what-we-do",
    "/offerings", "/expertise",
    "/industries", "/clients", "/portfolio", "/case-studies",
    "/technology", "/platform",
]


class PageCrawler:
    """Crawl internal pages of a website for comprehensive content."""

    def __init__(self):
        self.http_scraper = HTTPScraper(timeout=15.0)
        self.extractor = ContentExtractor()

    async def crawl(
        self,
        base_url: str,
        homepage_html: str,
        max_pages: int = 8,
    ) -> dict:
        """
        Crawl a website's internal pages.
        Returns: {pages: [{url, text, word_count, page_type}], combined_text, total_words}
        """
        parsed = urlparse(base_url)
        base = f"{parsed.scheme}://{parsed.netloc}"

        # Extract homepage content
        homepage_content = self.extractor.extract(homepage_html, base_url)
        pages = [{
            "url": base_url,
            "text": homepage_content["text"],
            "word_count": homepage_content["word_count"],
            "page_type": "homepage",
        }]

        # Check which priority paths exist via HEAD requests
        valid_paths = await self._check_paths(base, PRIORITY_PATHS)
        logger.info("valid_paths_found", base=base, count=len(valid_paths), paths=valid_paths[:5])

        # Fetch valid pages (limit to max_pages)
        fetch_tasks = []
        for path in valid_paths[:max_pages]:
            url = base.rstrip("/") + path
            fetch_tasks.append(self._fetch_page(url, path))

        if fetch_tasks:
            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, dict) and result.get("text"):
                    pages.append(result)

        # Combine all text with source tracking
        combined_parts = []
        for page in pages:
            if page["text"]:
                combined_parts.append(
                    f"--- [Source: {page['url']}] ---\n{page['text']}"
                )

        combined_text = "\n\n".join(combined_parts)
        # Deduplicate across pages
        combined_text = self._cross_page_deduplicate(combined_text)
        total_words = len(combined_text.split()) if combined_text else 0

        logger.info(
            "crawl_complete",
            base=base,
            pages_scraped=len(pages),
            total_words=total_words,
        )

        return {
            "pages": pages,
            "combined_text": combined_text,
            "total_words": total_words,
        }

    async def _check_paths(self, base: str, paths: list[str]) -> list[str]:
        """Check which paths exist via HEAD requests (async parallel)."""
        async def check(path: str) -> str | None:
            url = base.rstrip("/") + path
            status = await self.http_scraper.fetch_head(url)
            if status and 200 <= status < 400:
                return path
            return None

        tasks = [check(p) for p in paths]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if isinstance(r, str)]

    async def _fetch_page(self, url: str, path: str) -> dict:
        """Fetch and extract content from a single internal page."""
        try:
            result = await self.http_scraper.fetch(url)
            if not result.get("html"):
                return {"url": url, "text": "", "word_count": 0, "page_type": path.strip("/")}

            content = self.extractor.extract(result["html"], url)
            return {
                "url": url,
                "text": content["text"],
                "word_count": content["word_count"],
                "page_type": path.strip("/"),
            }
        except Exception as e:
            logger.warning("page_fetch_error", url=url, error=str(e))
            return {"url": url, "text": "", "word_count": 0, "page_type": path.strip("/")}

    def _cross_page_deduplicate(self, text: str) -> str:
        """Remove duplicate content that appears across multiple pages."""
        import hashlib
        seen = set()
        output = []
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("--- [Source:"):
                output.append(line)
                continue
            import re
            normalized = re.sub(r"[^\w\s]", "", stripped.lower())
            normalized = re.sub(r"\s+", " ", normalized).strip()
            if len(normalized) < 10:
                output.append(line)
                continue
            key = hashlib.md5(normalized[:100].encode()).hexdigest()
            if key not in seen:
                seen.add(key)
                output.append(line)
        return "\n".join(output)
