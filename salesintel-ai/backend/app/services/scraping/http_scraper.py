"""
HTTP Scraper — Strategy 1: Fast async HTTP scraping with httpx.
"""
import httpx
import structlog
from typing import Optional

logger = structlog.get_logger("scraping.http")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


class HTTPScraper:
    """Async HTTP scraper using httpx — fastest strategy."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    async def fetch(self, url: str, proxy: Optional[str] = None) -> dict:
        """
        Fetch a URL via httpx.
        Returns: {html, status_code, method, error, error_code}
        """
        result = {
            "html": None,
            "status_code": None,
            "method": "httpx",
            "error": None,
            "error_code": None,
        }

        for verify_ssl in [True, False]:
            try:
                async with httpx.AsyncClient(
                    headers=HEADERS,
                    timeout=self.timeout,
                    follow_redirects=True,
                    verify=verify_ssl,
                    proxy=proxy,
                ) as client:
                    response = await client.get(url)
                    result["status_code"] = response.status_code

                    if response.status_code >= 500:
                        result["error"] = f"Server error: HTTP {response.status_code}"
                        result["error_code"] = "server_error"
                        return result

                    if response.status_code == 404:
                        result["error"] = "Page not found (404)"
                        result["error_code"] = "not_found"
                        return result

                    if response.status_code in (401, 403):
                        result["error"] = f"Access denied: HTTP {response.status_code}"
                        result["error_code"] = "access_denied"
                        return result

                    content_type = response.headers.get("content-type", "")
                    if "text/html" not in content_type:
                        result["error"] = "Response is not HTML"
                        result["error_code"] = "empty_content"
                        return result

                    html = response.text
                    body_len = len(html) if html else 0

                    if body_len < 500:
                        result["error"] = "Response body too short"
                        result["error_code"] = "empty_content"
                        result["html"] = html  # Still return it — might be a redirect page
                        return result

                    result["html"] = html
                    logger.info(
                        "http_fetch_success",
                        url=url,
                        status=response.status_code,
                        body_length=body_len,
                    )
                    return result

            except httpx.ConnectError as e:
                err_str = str(e).lower()
                if "name or service not known" in err_str or "getaddrinfo" in err_str:
                    result["error"] = "DNS resolution failed"
                    result["error_code"] = "dns_failure"
                    return result
                if not verify_ssl:
                    result["error"] = f"Connection error: {e}"
                    result["error_code"] = "connection_refused"
                    return result
                continue

            except httpx.TimeoutException:
                if not verify_ssl:
                    result["error"] = "Request timed out"
                    result["error_code"] = "connection_timeout"
                    return result
                continue

            except httpx.TooManyRedirects:
                result["error"] = "Too many redirects"
                result["error_code"] = "redirect_loop"
                return result

            except Exception as e:
                logger.warning("http_fetch_error", url=url, error=str(e))
                if not verify_ssl:
                    result["error"] = str(e)
                    result["error_code"] = "connection_refused"
                    return result
                continue

        result["error"] = "SSL verification failed"
        result["error_code"] = "ssl_error"
        return result

    async def fetch_head(self, url: str) -> int | None:
        """HEAD request to check if a page exists. Returns status code or None."""
        try:
            async with httpx.AsyncClient(
                headers=HEADERS, timeout=10.0, follow_redirects=True, verify=False
            ) as client:
                resp = await client.head(url)
                return resp.status_code
        except Exception:
            return None
