"""
Google Custom Search — Discover companies by region and industry.
"""
import httpx
import structlog
from typing import Optional

from app.config import get_settings

logger = structlog.get_logger("discovery.google")


class GoogleSearchClient:
    """Google Custom Search API client for company discovery."""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = "https://www.googleapis.com/customsearch/v1"

    async def search_companies(
        self,
        query: str,
        region: str,
        max_results: int = 30,
    ) -> list[dict]:
        """
        Search for companies by industry + region.

        Returns: list of {
            title, link, snippet, display_link
        }
        """
        if not self.settings.google_custom_search_api_key:
            logger.warning("google_cse_not_configured")
            return await self._fallback_search(query, region, max_results)

        all_results = []
        # CSE returns max 10 per request, paginate
        for start in range(1, min(max_results + 1, 91), 10):
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    params = {
                        "key": self.settings.google_custom_search_api_key,
                        "cx": self.settings.google_custom_search_engine_id,
                        "q": f"{query} companies in {region}",
                        "start": start,
                        "num": min(10, max_results - len(all_results)),
                    }
                    response = await client.get(self.base_url, params=params)
                    response.raise_for_status()
                    data = response.json()

                    items = data.get("items", [])
                    for item in items:
                        all_results.append({
                            "title": item.get("title", ""),
                            "link": item.get("link", ""),
                            "snippet": item.get("snippet", ""),
                            "display_link": item.get("displayLink", ""),
                        })

                    if len(items) < 10:
                        break  # No more results

            except httpx.HTTPStatusError as e:
                logger.error("google_cse_error", status=e.response.status_code)
                break
            except Exception as e:
                logger.error("google_cse_exception", error=str(e))
                break

        logger.info("google_search_complete", query=query, region=region, results=len(all_results))
        return all_results

    async def _fallback_search(
        self, query: str, region: str, max_results: int
    ) -> list[dict]:
        """
        Fallback when Google CSE is not configured.
        Uses DuckDuckGo HTML search.
        """
        logger.info("using_duckduckgo_fallback")
        results = []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": f"{query} companies in {region}"},
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0",
                    },
                )
                resp.raise_for_status()

                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "lxml")

                for result in soup.select(".result"):
                    title_el = result.select_one(".result__title a")
                    snippet_el = result.select_one(".result__snippet")

                    if title_el:
                        href = title_el.get("href", "")
                        # DuckDuckGo wraps URLs
                        if "uddg=" in href:
                            from urllib.parse import unquote, parse_qs, urlparse
                            parsed = urlparse(href)
                            actual_url = parse_qs(parsed.query).get("uddg", [href])[0]
                            href = unquote(actual_url)

                        results.append({
                            "title": title_el.get_text(strip=True),
                            "link": href,
                            "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                            "display_link": href,
                        })

                    if len(results) >= max_results:
                        break

        except Exception as e:
            logger.error("duckduckgo_fallback_error", error=str(e))

        return results
