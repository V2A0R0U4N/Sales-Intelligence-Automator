"""
Region Discovery — Two-Phase Company Discovery by region + category.

Phase 1: Search DuckDuckGo (accepts directory/listing pages too).
Phase 2: Scrape each result page to extract real company names + URLs.
         If a page itself looks like a direct company site, add it as-is.
         If it's a listing/directory page, extract individual company entries.
"""
from __future__ import annotations

import re
import time
import random
import logging
from urllib.parse import urlparse, unquote, parse_qs, urljoin

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# ─── Categories ───
CATEGORIES = {
    "technology": "Technology & IT",
    "digital": "Digital Marketing & Advertising",
    "design_cad": "Design, CAD & Architecture",
    "manufacturing": "Manufacturing & Industrial",
    "healthcare": "Healthcare & Medical",
    "finance": "Finance & Accounting",
    "consulting": "Business Consulting",
    "education": "Education & Training",
    "retail": "Retail & E-commerce",
}

# ─── Hard blocklist: domains that are NEVER a direct company site ───
# (social media, job boards, etc. — but we DO allow directories on first pass
#  so we can scrape their listings)
ALWAYS_BLOCKED = {
    "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "pinterest.com", "reddit.com", "quora.com", "tiktok.com",
    "google.com", "google.co.in", "google.co.uk", "maps.google.com",
    "monster.com", "shine.com", "naukri.com", "indeed.com", "glassdoor.com",
    "glassdoor.co.in", "wikipedia.org", "medium.com",
    "bloomberg.com", "reuters.com", "forbes.com", "inc.com",
    "entrepreneur.com", "businessinsider.com", "techcrunch.com",
    "internshala.com", "trainings.internshala.com", "blog.internshala.com",
    # Search engines & job boards that appear as results
    "duckduckgo.com", "bing.com", "yahoo.com", "ask.com",
    "jobrapido.com", "foundit.in", "apna.co", "linkedin.com",
    "timesjobs.com", "freshersworld.com", "hirist.tech", "iimjobs.com",
}

# ─── Listing / directory domains we CAN scrape for company entries ───
LISTING_DOMAINS = {
    "clutch.co", "goodfirms.co", "techbehemoths.com", "designrush.com",
    "themanifest.com", "appfutura.com", "sortlist.com", "techreviewer.co",
    "topdevelopers.co", "selectedfirms.co", "softwareworld.co",
    "justdial.com", "indiamart.com", "sulekha.com", "urbanpro.com",
    "yelp.com", "yellowpages.com", "manta.com", "superpages.com",
    "crunchbase.com", "zoominfo.com", "owler.com", "g2.com",
    "tracxn.com", "startuptalky.com", "rocketreach.co",
    "rankexdigital.com", "chamberofcommerce.com", "bbb.org",
    "ambitionbox.com", "comparably.com", "wellfound.com",
    "bark.com", "birdeye.com", "dexknows.com",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

# Patterns that indicate this is a listicle/article URL (not a direct company)
LISTICLE_URL_PATTERNS = re.compile(
    r"(top-\d+|best-\d+|list-of|/blog/|/article/|/news/|/press/|/tag/|"
    r"/category/|/wiki/|/reviews/|/compare/|companies-in-|firms-in-|"
    r"top-companies|best-companies|leading-companies|/search\?|"
    r"startups-in-|agencies-in-|/careers|/jobs)",
    re.IGNORECASE,
)

LISTICLE_TITLE_PATTERNS = re.compile(
    r"(top \d+|best \d+|\d+ best|\d+ top|list of|companies in|firms in|"
    r"agencies in|startups in|leading .* companies|guide to|review of|"
    r"compare|ranking|directory)",
    re.IGNORECASE,
)


# ════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════

GENERIC_NAME_PATTERNS = re.compile(
    r"^(about us|contact us|home|homepage|welcome|official site|services|products|"
    r"read more|learn more|click here|visit website|portfolio|about|contact|"
    r"get quote|login|register|signup|back|overview|locations?|careers?|jobs?|"
    r"our team|privacy policy|terms|conditions|status|tools|trending|news|blog|"
    r"resources|events|press|media|support|help|faq|pricing)$",
    re.IGNORECASE
)

EMAIL_PATTERN = re.compile(r"[\w.-]+@[\w.-]+\.\w+")
PHONE_PATTERN = re.compile(r"^[\+\d\-\(\)\s]{8,20}$")

def _is_valid_company_name(name: str) -> bool:
    """True if name doesn't look like an email, phone number, or generic phrase."""
    if not name or len(name) < 2 or len(name) > 80:
        return False
    # Catch [email protected] or other bracketed email placeholders
    if "email protected" in name.lower() or "[email" in name.lower() or EMAIL_PATTERN.search(name):
        return False
    if PHONE_PATTERN.match(name.strip()):
        return False
    if GENERIC_NAME_PATTERNS.match(name.strip()):
        return False
    return True

def _domain_of(url: str) -> str:
    """Return bare domain (no www.) from a URL."""
    try:
        return urlparse(url).netloc.replace("www.", "").lower()
    except Exception:
        return ""


def _root_url(url: str) -> str:
    """Return scheme://netloc (homepage) for any URL."""
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}"
    except Exception:
        return url


def _is_always_blocked(url: str) -> bool:
    domain = _domain_of(url)
    return any(b in domain for b in ALWAYS_BLOCKED)


def _is_listing_domain(url: str) -> bool:
    domain = _domain_of(url)
    return any(ld in domain for ld in LISTING_DOMAINS)


def _is_direct_company_url(url: str, title: str = "") -> bool:
    """True if this URL looks like an actual company's own website."""
    if not url or _is_always_blocked(url) or _is_listing_domain(url):
        return False
    domain = _domain_of(url)
    if not domain or "." not in domain:
        return False
    
    # Reject obvious non-company subdomains
    if domain.startswith(("status.", "tools.", "news.", "blog.", "docs.", "support.", "help.")):
        return False

    full_path = urlparse(url).path.lower()
    if LISTICLE_URL_PATTERNS.search(full_path):
        return False
    if title and LISTICLE_TITLE_PATTERNS.search(title):
        return False
    return True


def _extract_name_from_url(url: str) -> str:
    try:
        domain = _domain_of(url)
        name = domain.split(".")[0]
        return name.replace("-", " ").replace("_", " ").strip().title()
    except Exception:
        return "Unknown"


def _clean_company_name(title: str, url: str) -> str:
    if not title:
        candidate = _extract_name_from_url(url)
        return candidate if _is_valid_company_name(candidate) else "Unknown"
    
    name = re.split(r"\s*[|–—\-:]\s*", title)[0].strip()
    name = re.sub(
        r"\s*(Home|Official Site|Official Website|Welcome|Homepage|"
        r"Main|About|Contact|Services|Solutions|Products)\s*$",
        "", name, flags=re.IGNORECASE
    ).strip()
    
    if not _is_valid_company_name(name):
        candidate = _extract_name_from_url(url)
        return candidate if _is_valid_company_name(candidate) else "Unknown"
        
    return name


def _extract_url_from_ddg_href(href: str) -> str | None:
    if not href:
        return None
    if "uddg=" in href:
        try:
            parsed = parse_qs(urlparse(href).query)
            if "uddg" in parsed:
                return unquote(parsed["uddg"][0])
        except Exception:
            pass
    if href.startswith("http"):
        return href
    if href.startswith("//"):
        return "https:" + href
    return None


# ════════════════════════════════════════════════════════════════
# DuckDuckGo Search
# ════════════════════════════════════════════════════════════════

def _search_ddg(query: str, max_results: int = 20) -> list[dict]:
    """Search DuckDuckGo HTML and return raw results."""
    results = []
    endpoints = [
        ("https://html.duckduckgo.com/html/", "html"),
        ("https://lite.duckduckgo.com/lite/", "lite"),
    ]

    for endpoint_url, endpoint_type in endpoints:
        try:
            time.sleep(random.uniform(1.0, 2.0))

            if endpoint_type == "lite":
                headers = {**HEADERS, "Content-Type": "application/x-www-form-urlencoded"}
                r = requests.post(endpoint_url, data={"q": query}, headers=headers, timeout=12)
            else:
                r = requests.get(endpoint_url, params={"q": query}, headers=HEADERS, timeout=12)

            r.raise_for_status()

            if "captcha" in r.text.lower() or r.status_code == 202:
                continue

            soup = BeautifulSoup(r.text, "lxml")
            links = (
                soup.select(".result__a") or
                soup.select(".results_links a") or
                soup.select("a.result-url")
            )
            snippets_els = soup.select(".result__snippet")

            for i, link in enumerate(links[:max_results]):
                href = link.get("href", "")
                url = _extract_url_from_ddg_href(href)
                if not url:
                    continue
                title = link.get_text(strip=True)
                snippet = snippets_els[i].get_text(strip=True) if i < len(snippets_els) else ""
                results.append({"url": url, "title": title, "snippet": snippet})

            if results:
                break
        except Exception as e:
            log.warning(f"DDG search failed ({endpoint_type}): {e}")

    return results


# ════════════════════════════════════════════════════════════════
# Phase 1b — Scrape a listing page to extract individual companies
# ════════════════════════════════════════════════════════════════

def _fetch_html(url: str, timeout: int = 10) -> str | None:
    """Fetch raw HTML from a URL, return None on failure."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        return r.text
    except Exception as e:
        log.warning(f"[Listing fetch] Failed {url}: {e}")
        return None


def _extract_companies_from_listing(listing_url: str, region: str) -> list[dict]:
    """
    Scrape a directory / listing page and extract individual company entries.

    Looks for:
      - Anchor tags inside common card / list containers.
      - External links pointing to company websites with nearby text as names.

    Returns list of {name, url} dicts.
    """
    html = _fetch_html(listing_url)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    listing_domain = _domain_of(listing_url)
    found: list[dict] = []
    seen: set[str] = set()

    # ── Strategy 1: Look for company cards / profile links ──
    # Most listing sites wrap each company in an <li>, <article>, or <div>
    # with a class containing "company", "firm", "profile", "card", "result", "listing"
    card_selectors = [
        "li.company", "li.firm", "li.profile", "li.result", "li.listing",
        "div[class*='company']", "div[class*='profile']", "div[class*='card']",
        "div[class*='provider']", "div[class*='vendor']", "div[class*='listing']",
        "article[class*='company']", "article[class*='firm']",
        ".company-item", ".service-provider", ".sp-item", ".agency-item",
    ]

    cards = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            break

    if cards:
        for card in list(cards)[:30]:
            # Try to get the company name from heading inside card
            name_el = card.find(["h2", "h3", "h4", "strong", "b"])
            name = name_el.get_text(strip=True) if name_el else ""

            # Try to get the external company website URL
            company_url = None
            for a in card.find_all("a", href=True):
                href = str(a.get("href", ""))
                # Resolve relative links
                if href.startswith("/"):
                    href = urljoin(listing_url, href)
                href_domain = _domain_of(href)
                if (
                    href.startswith("http")
                    and href_domain
                    and href_domain != listing_domain
                    and not _is_always_blocked(href)
                ):
                    company_url = href
                    if not name:
                        name = a.get_text(strip=True)
                    break

            if not company_url or not name or not _is_valid_company_name(name):
                continue

            # Deduplicate
            key = _domain_of(company_url)
            if key in seen:
                continue
            seen.add(key)

            found.append({"name": name.strip(), "url": _root_url(str(company_url))})

    # ── Strategy 2: Find all external links with meaningful anchor text ──
    if len(found) < 5:
        for a in soup.find_all("a", href=True):
            href = str(a.get("href", ""))
            if href.startswith("/"):
                href = urljoin(listing_url, href)
            if not href.startswith("http"):
                continue

            href_domain = _domain_of(href)
            if not href_domain or href_domain == listing_domain:
                continue
            if _is_always_blocked(href):
                continue

            anchor_text = a.get_text(strip=True)
            if not _is_valid_company_name(anchor_text):
                continue

            # Basic cleanup (the strict checks are handled by _is_valid_company_name)

            key = _domain_of(href)
            if key in seen:
                continue
            seen.add(key)

            found.append({"name": anchor_text.strip(), "url": _root_url(href)})

            if len(found) >= 20:
                break

    log.info(f"[Listing] Extracted {len(found)} companies from {listing_url}")
    return found


# ════════════════════════════════════════════════════════════════
# Main entry point
# ════════════════════════════════════════════════════════════════

def discover_companies(
    region: str,
    category: str = "technology",
    max_results: int = 35,
) -> list[dict]:
    """
    Two-phase discovery:
    1. Search DuckDuckGo for pages related to the region & category.
    2. For each result:
         - If it's a direct company website → add it.
         - If it's a listing/directory page → scrape it to extract embedded companies.
    3. Deduplicate by domain, return up to max_results entries.

    Returns list of {name, url, snippet, category, region} dicts.
    """
    category_label = CATEGORIES.get(category, category)

    queries = [
        f"top {category_label} companies in {region}",
        f"{category_label} companies list {region}",
        f"best {category_label} firms {region}",
        f"{region} {category_label} company website",
        f"{category_label} agencies {region} India",
        f"{region} {category_label} startup companies",
        f"leading {category_label} companies {region}",
    ]

    seen_domains: set[str] = set()
    companies: list[dict] = []

    def _add(name: str, url: str, snippet: str = "") -> bool:
        """Add company if not already seen. Returns True if added."""
        if not url:
            return False
        domain = _domain_of(url)
        if not domain or domain in seen_domains:
            return False
        seen_domains.add(domain)
        companies.append({
            "name": name,
            "url": _root_url(url),
            "snippet": snippet,
            "category": category_label,
            "region": region,
        })
        return True

    for query in queries:
        if len(companies) >= max_results:
            break

        log.info(f"[Discovery] Searching: {query}")
        raw_results = _search_ddg(query, max_results=10)

        for item in raw_results:
            if len(companies) >= max_results:
                break

            url = item["url"]
            title = item.get("title", "")
            snippet = item.get("snippet", "")

            if _is_always_blocked(url):
                continue

            if _is_direct_company_url(url, title):
                # Direct company website — add as-is
                name = _clean_company_name(title, url)
                _add(name, url, snippet)

            elif _is_listing_domain(url) or LISTICLE_URL_PATTERNS.search(urlparse(url).path.lower()):
                # Directory / listing page — scrape its entries
                log.info(f"[Discovery] Scraping listing page: {url}")
                entries = _extract_companies_from_listing(url, region)
                for entry in entries:
                    if len(companies) >= max_results:
                        break
                    _add(entry["name"], entry["url"])
                time.sleep(random.uniform(0.5, 1.0))

            else:
                # Uncertain — try scraping as listing first, fall back to direct add
                entries = _extract_companies_from_listing(url, region)
                if entries:
                    for entry in entries:
                        if len(companies) >= max_results:
                            break
                        _add(entry["name"], entry["url"])
                else:
                    name = _clean_company_name(title, url)
                    _add(name, url, snippet)

        if len(companies) < max_results:
            time.sleep(random.uniform(1.5, 2.5))

    log.info(f"[Discovery] Found {len(companies)} companies in {region} ({category_label})")
    return companies
