"""
Proxy Manager — Rotating proxy logic for Strategy 3.
Supports Bright Data or custom proxy lists.
"""
import random
import structlog
from typing import Optional
from app.config import get_settings

logger = structlog.get_logger("scraping.proxy")


class ProxyManager:
    """Manage rotating proxies — never reuse the same IP for the same domain."""

    def __init__(self):
        self.settings = get_settings()
        self._used_proxies: dict[str, set[str]] = {}  # domain -> set of used proxy IPs
        self._free_proxies: list[str] = [
            # Free proxy list as fallback (these are examples and may not work)
            # In production, populate from Bright Data or a proxy service
        ]

    def get_proxy(self, domain: str) -> Optional[str]:
        """
        Get a proxy URL for the given domain.
        Returns None if no proxy is available.
        """
        # Priority 1: Bright Data proxy
        if self.settings.bright_data_proxy_url:
            proxy = self.settings.bright_data_proxy_url
            logger.debug("using_bright_data_proxy", domain=domain)
            return proxy

        # Priority 2: Free proxy rotation
        if not self._free_proxies:
            return None

        used = self._used_proxies.get(domain, set())
        available = [p for p in self._free_proxies if p not in used]

        if not available:
            # Reset if all proxies have been used for this domain
            self._used_proxies[domain] = set()
            available = self._free_proxies

        chosen = random.choice(available)
        self._used_proxies.setdefault(domain, set()).add(chosen)
        logger.debug("using_free_proxy", domain=domain, proxy=chosen)
        return chosen

    def add_proxies(self, proxies: list[str]):
        """Add proxies to the free proxy pool."""
        self._free_proxies.extend(proxies)

    def has_proxies(self) -> bool:
        """Check if any proxy source is configured."""
        return bool(self.settings.bright_data_proxy_url or self._free_proxies)
