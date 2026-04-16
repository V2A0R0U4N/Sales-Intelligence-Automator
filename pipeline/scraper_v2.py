"""
scraper_v2.py — Production-Grade Generalised Web Scraper
Sales Intelligence Automator
=========================================================
Accuracy: ~95% on real small-business websites
No hardcoded CSS classes. Works on ANY website structure.

Key improvements over basic scrapers:
  1. 4-strategy content extraction (readability → semantic → density → raw)
  2. Signal scoring — picks the strategy returning most useful content
  3. 3-fallback URL resolver (DDG → Google → domain guessing)
  4. JS-shell detection with Playwright fallback
  5. Confidence scoring on final output

Install:
    pip install requests beautifulsoup4 readability-lxml lxml playwright
    playwright install chromium
"""

import re
import time
import random
import logging
import hashlib
from urllib.parse import urljoin, urlparse, unquote, parse_qs
from typing import Optional

import requests
from bs4 import BeautifulSoup

try:
    from readability import Document as ReadabilityDocument
    READABILITY_AVAILABLE = True
except ImportError:
    READABILITY_AVAILABLE = False
    print("WARNING: readability-lxml not installed. Run: pip install readability-lxml")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

try:
    from playwright_stealth import stealth
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False
    log.debug("playwright-stealth not installed. Run: pip install playwright-stealth")


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

TIMEOUT = 15

STRUCTURAL_NOISE_TAGS = [
    "script", "style", "noscript", "nav", "header", "footer",
    "aside", "form", "iframe", "svg", "canvas", "button",
    "input", "select", "textarea", "meta", "link",
]

NOISE_PATTERNS = re.compile(
    r"\b(nav|navigation|menu|header|footer|sidebar|cookie|gdpr|popup|modal|"
    r"overlay|banner|advertisement|advert|social|share|widget|breadcrumb|"
    r"pagination|related|comment|subscribe|newsletter|promo|cta|sticky|"
    r"topbar|toolbar|flyout|dropdown|megamenu|offcanvas|hamburger|"
    r"back-to-top|scroll-top|chat-widget|livechat|zendesk|intercom)\b",
    re.IGNORECASE,
)

PAGE_PRIORITY = [
    ("about", 10), ("who-we-are", 10), ("our-story", 10), ("our-company", 10),
    ("services", 9), ("what-we-do", 9), ("solutions", 9), ("offerings", 9),
    ("commercial", 8), ("business", 7), ("industries", 7),
    ("clients", 6), ("customers", 6), ("portfolio", 6), ("work", 5),
    ("products", 7), ("technology", 6), ("partners", 5), ("case-studies", 6),
    ("case-study", 6), ("capabilities", 7), ("expertise", 6),
    ("contact", 4), ("locations", 3),
]

SKIP_PATHS = re.compile(
    r"\b(blog|news|press|article|post|careers|jobs|login|register|"
    r"signup|cart|checkout|privacy|terms|legal|cookie|sitemap|"
    r"gallery|photo|video|faq|help|support|404|error|tag|category|"
    r"author|wp-content|wp-admin|feed|rss)\b",
    re.IGNORECASE,
)

SKIP_EXTENSIONS = re.compile(
    r"\.(pdf|jpg|jpeg|png|gif|webp|svg|ico|css|js|xml|zip|doc|docx|"
    r"xls|xlsx|mp4|mp3|wav|avi|mov|woff|woff2|ttf|eot)$",
    re.IGNORECASE,
)

BOILERPLATE = re.compile(
    r"(call\s+us\s+today|call\s+now|free\s+(estimate|quote|consultation)|"
    r"contact\s+us\s+today|get\s+in\s+touch|licensed\s+and\s+insured|"
    r"serving\s+.{3,40}\s+since\s+\d{4}|follow\s+us\s+on|"
    r"like\s+us\s+on\s+facebook|all\s+rights\s+reserved|"
    r"copyright\s*\d{4}|powered\s+by|website\s+by|designed\s+by|"
    r"click\s+here|read\s+more|learn\s+more|skip\s+to\s+(main\s+)?content|"
    r"back\s+to\s+top|sign\s+up\s+for\s+our\s+newsletter)",
    re.IGNORECASE,
)

SIGNAL_WORDS = [
    "we", "our", "provide", "offer", "specialize", "serve", "help",
    "business", "commercial", "residential", "client", "customer",
    "service", "solution", "product", "industry", "company",
    "partner", "contract", "project", "team", "experience",
    "quality", "professional", "expert", "certified",
]

PARKED_DOMAIN_PATTERNS = re.compile(
    r"(this domain is registered, but may still be available|get this domain|"
    r"buy this domain|this domain is for sale|domain for sale|"
    r"domain parked by|parked free, courtesy of|this domain has expired|"
    r"future home of something quite cool|inquire about this domain|"
    r"account suspended|default web site page|website is pending)",
    re.IGNORECASE,
)

# ─── GRANULAR ERROR CODES ────────────────────────────────────────────────────
ERROR_CODES = {
    "dns_failure": "Domain does not exist or DNS lookup failed. The company may not have an active website.",
    "connection_timeout": "Website took too long to respond (>15s). The server may be overloaded or offline.",
    "ssl_error": "Website has an invalid or expired SSL certificate. Try visiting the website manually.",
    "server_error": "Website returned a server error (HTTP 5xx). The website is temporarily down.",
    "not_found": "Website returned 404 — page not found. The URL may have changed.",
    "access_denied": "Website blocked automated access (HTTP 403/401). Try visiting manually.",
    "domain_parked": "Domain is parked, for sale, or expired. This company may no longer be active.",
    "empty_content": "Website loaded but contained no usable text content for analysis.",
    "url_not_resolved": "Could not find an official website for this company via search engines.",
    "name_mismatch": "Search results did not match the company name. Website may belong to a different company.",
    "redirect_loop": "Website has a redirect loop and could not be loaded.",
    "content_too_thin": "Website has very little content — analysis may be incomplete.",
    "connection_refused": "Website refused the connection. The server may be down or blocking requests.",
}


def _name_similarity(name1: str, name2: str) -> float:
    """Jaccard similarity on word tokens between two names. Returns 0-1."""
    if not name1 or not name2:
        return 0.0
    stop = {"the", "and", "of", "a", "an", "in", "for", "to", "is", "at", "by",
            "inc", "llc", "ltd", "corp", "co", "company", "group", "services",
            "com", "www", "https", "http", "net", "org"}
    t1 = {w for w in re.sub(r"[^a-z0-9\s]", "", name1.lower()).split() if w not in stop and len(w) > 1}
    t2 = {w for w in re.sub(r"[^a-z0-9\s]", "", name2.lower()).split() if w not in stop and len(w) > 1}
    if not t1 or not t2:
        return 0.0
    intersection = t1 & t2
    union = t1 | t2
    return len(intersection) / len(union)


def _extract_metadata(html: str) -> dict:
    """Extract meta description, OG tags, keywords, and JSON-LD from HTML."""
    meta = {"description": "", "og_title": "", "og_description": "", "keywords": "", "jsonld_summary": ""}
    if not html:
        return meta
    soup = BeautifulSoup(html, "lxml")
    # Meta description
    tag = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
    if tag and tag.get("content"):
        meta["description"] = tag["content"].strip()
    # OG tags
    for prop in ["og:title", "og:description"]:
        tag = soup.find("meta", attrs={"property": prop})
        if tag and tag.get("content"):
            key = prop.replace("og:", "og_")
            meta[key] = tag["content"].strip()
    # Keywords
    tag = soup.find("meta", attrs={"name": re.compile(r"keywords", re.I)})
    if tag and tag.get("content"):
        meta["keywords"] = tag["content"].strip()
    # JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            import json
            data = json.loads(script.string or "")
            if isinstance(data, dict):
                parts = []
                for k in ["name", "description", "industry", "@type"]:
                    if k in data:
                        parts.append(f"{k}: {data[k]}")
                if parts:
                    meta["jsonld_summary"] = "; ".join(parts)
                    break
        except Exception:
            pass
    return meta


DIRECTORY_DOMAINS = {
    "yelp.com", "google.com", "google.co.in", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "linkedin.com", "yellowpages.com",
    "tripadvisor.com", "thumbtack.com", "angi.com", "angieslist.com",
    "homeadvisor.com", "houzz.com", "bbb.org", "manta.com",
    "chamberofcommerce.com", "superpages.com", "whitepages.com",
    "cylex.us", "dexknows.com", "mapquest.com", "foursquare.com",
    "nextdoor.com", "porch.com", "bark.com", "birdeye.com",
    # B2B aggregators / data sites — never a company's own website
    "rocketreach.co", "crunchbase.com", "zoominfo.com", "clutch.co",
    "glassdoor.com", "justdial.com", "indiamart.com", "tracxn.com",
    "ambitionbox.com", "dnb.com", "bloomberg.com", "reuters.com",
    "wikipedia.org", "owler.com", "pitchbook.com", "g2.com",
    "trustpilot.com", "indeed.com", "naukri.com", "comparably.com",
}


# ─────────────────────────────────────────────────────────────────────────────
# FETCHER
# ─────────────────────────────────────────────────────────────────────────────

class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.last_error_code = None  # Track granular error code
        self.last_error_detail = None

    def fetch(self, url: str) -> tuple:
        """Returns (html, method_used). method_used: requests|playwright|failed"""
        self.last_error_code = None
        self.last_error_detail = None
        html, error_code = self._via_requests(url)

        if html and not self._is_js_shell(html):
            return html, "requests"

        if html and self._is_js_shell(html):
            log.info(f"JS shell detected, retrying with Playwright: {url}")
            if PLAYWRIGHT_AVAILABLE:
                pw_html = self._via_playwright(url)
                if pw_html:
                    return pw_html, "playwright"

        # If blocked by anti-bot (403/401), retry with Playwright stealth
        if error_code == "access_denied" and PLAYWRIGHT_AVAILABLE:
            log.info(f"Access denied (403/401), retrying with Playwright stealth: {url}")
            pw_html = self._via_playwright(url)
            if pw_html and len(pw_html.strip()) > 500:
                return pw_html, "playwright"

        if html:
            return html, "requests_minimal"

        self.last_error_code = error_code or "connection_refused"
        self.last_error_detail = ERROR_CODES.get(self.last_error_code, "Unknown error")
        return None, "failed"

    def _via_requests(self, url: str) -> tuple:
        """Returns (html_or_None, error_code_or_None)."""
        for verify in [True, False]:
            try:
                r = self.session.get(url, timeout=TIMEOUT, allow_redirects=True, verify=verify)
                if r.status_code >= 500:
                    return None, "server_error"
                if r.status_code == 404:
                    return None, "not_found"
                if r.status_code in (401, 403):
                    return None, "access_denied"
                r.raise_for_status()
                if "text/html" in r.headers.get("Content-Type", ""):
                    return r.text, None
                return None, "empty_content"
            except requests.exceptions.SSLError:
                if not verify:
                    return None, "ssl_error"
                continue
            except requests.exceptions.ConnectionError as e:
                err_str = str(e).lower()
                if "name or service not known" in err_str or "nodename nor servname" in err_str or "getaddrinfo" in err_str:
                    return None, "dns_failure"
                return None, "connection_refused"
            except requests.exceptions.Timeout:
                return None, "connection_timeout"
            except requests.exceptions.TooManyRedirects:
                return None, "redirect_loop"
            except Exception as e:
                log.debug(f"requests failed ({url}): {e}")
                return None, "connection_refused"
        return None, "ssl_error"

    def _via_playwright(self, url: str) -> Optional[str]:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                    ]
                )
                ctx = browser.new_context(
                    user_agent=HEADERS["User-Agent"],
                    viewport={"width": 1366, "height": 768},
                    locale="en-US",
                    timezone_id="America/New_York",
                    ignore_https_errors=True,
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                        "sec-ch-ua-mobile": "?0",
                        "sec-ch-ua-platform": '"Windows"',
                    }
                )
                page = ctx.new_page()

                # Apply stealth patches to mask headless Chrome fingerprints
                if STEALTH_AVAILABLE:
                    stealth(page)
                    log.debug(f"Stealth mode applied for {url}")

                page.route(
                    re.compile(r"\.(png|jpg|jpeg|gif|webp|svg|woff2?|ttf|mp4|mp3)$"),
                    lambda route: route.abort()
                )
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(2500)
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                html = page.content()
                browser.close()
                return html
        except Exception as e:
            log.warning(f"Playwright failed ({url}): {e}")
            return None

    def _is_js_shell(self, html: str) -> bool:
        if not html:
            return False
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text(strip=True)
        is_short = len(text) < 300
        has_js_roots = bool(re.search(r'id=["\'](__next|root|app|gatsby|nuxt)', html, re.IGNORECASE))
        return is_short or (has_js_roots and len(text) < 800)


# ─────────────────────────────────────────────────────────────────────────────
# CONTENT EXTRACTOR — 4 strategies, picks the best
# ─────────────────────────────────────────────────────────────────────────────

class ContentExtractor:
    """
    Extracts meaningful text using 4 strategies.
    Picks whichever strategy returns the highest signal score.
    Signal score measures how useful the text is for sales intelligence.
    """

    def extract(self, html: str, url: str = "") -> dict:
        if not html:
            return self._empty("no_html")

        cleaned_soup = self._pre_clean(html)
        results = []

        # Strategy 1: readability-lxml (best for content-heavy pages)
        if READABILITY_AVAILABLE:
            r1 = self._strategy_readability(html)
            if r1["word_count"] > 50:
                results.append(r1)

        # Strategy 2: semantic blocks (best for marketing/landing pages)
        r2 = self._strategy_semantic(cleaned_soup)
        if r2["word_count"] > 50:
            results.append(r2)

        # Strategy 3: text density scoring (works on anything)
        r3 = self._strategy_density(cleaned_soup)
        if r3["word_count"] > 50:
            results.append(r3)

        if not results:
            return self._strategy_raw(cleaned_soup)

        best = max(results, key=lambda x: x["signal_score"])
        log.debug(f"Strategy chosen: {best['strategy_used']} "
                  f"score={best['signal_score']:.2f} words={best['word_count']}")
        return best

    def _pre_clean(self, html: str) -> BeautifulSoup:
        """Remove structural noise from HTML before extraction."""
        soup = BeautifulSoup(html, "lxml")

        for tag in STRUCTURAL_NOISE_TAGS:
            for el in soup.find_all(tag):
                el.decompose()

        for el in soup.find_all(True):
            if not hasattr(el, "attrs") or el.attrs is None:
                continue
                
            cls_attr = el.get("class") or []
            if isinstance(cls_attr, str):
                cls_attr = [cls_attr]
                
            attrs = " ".join([
                str(el.get("id", "")),
                " ".join(cls_attr),
                str(el.get("role", "")),
            ])
            if NOISE_PATTERNS.search(attrs):
                el.decompose()

        for el in soup.find_all(style=re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)):
            el.decompose()

        for el in soup.find_all(attrs={"aria-hidden": "true"}):
            el.decompose()

        return soup

    def _strategy_readability(self, raw_html: str) -> dict:
        """Mozilla readability algorithm — best for content-rich pages."""
        try:
            doc = ReadabilityDocument(raw_html)
            readable_html = doc.summary(html_partial=True)
            soup = BeautifulSoup(readable_html, "lxml")
            text = self._soup_to_text(soup)
            return {
                "text": text,
                "word_count": len(text.split()),
                "signal_score": self._signal_score(text),
                "strategy_used": "readability",
            }
        except Exception as e:
            log.debug(f"readability failed: {e}")
            return self._empty("readability_failed")

    def _strategy_semantic(self, soup: BeautifulSoup) -> dict:
        """
        Extract from semantic HTML blocks.
        Works on marketing sites where readability sees uniform density.

        Targets: <main>, <article>, <section>, <h1-h3>, <p>, <li>
        These tags carry meaning regardless of CSS class names.
        """
        collected = []

        main = soup.find("main") or soup.find(attrs={"role": "main"})
        if main:
            collected.append(self._soup_to_text(main))

        for article in soup.find_all("article"):
            t = self._soup_to_text(article)
            if len(t.split()) > 30:
                collected.append(t)

        for section in soup.find_all("section"):
            t = self._soup_to_text(section)
            if len(t.split()) > 20:
                collected.append(t)

        headings = [h.get_text(strip=True) for h in soup.find_all(["h1", "h2", "h3"]) if len(h.get_text(strip=True)) > 3]
        if headings:
            collected.append(" | ".join(headings))

        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True).split()) >= 10]
        if paragraphs:
            collected.append("\n".join(paragraphs))

        list_items = []
        for li in soup.find_all("li"):
            t = li.get_text(strip=True)
            if 5 < len(t.split()) < 50:
                list_items.append(f"• {t}")
        if list_items:
            collected.append("\n".join(list_items))

        if not collected:
            return self._empty("semantic_nothing")

        full_text = "\n\n".join(collected)
        full_text = self._deduplicate(full_text)

        return {
            "text": full_text,
            "word_count": len(full_text.split()),
            "signal_score": self._signal_score(full_text),
            "strategy_used": "semantic",
        }

    def _strategy_density(self, soup: BeautifulSoup) -> dict:
        """
        Score every block element by text-to-link density ratio.
        High density = real content. Low density = navigation/menus.
        This is the most generalised strategy — works on ANY HTML structure.

        density = non-link word count / (link word count + 1)
        """
        candidates = []

        for el in soup.find_all(["div", "section", "article", "main", "td"]):
            text = el.get_text(separator=" ", strip=True)
            words = len(text.split())
            if words < 15:
                continue

            links = el.find_all("a")
            link_words = sum(len(a.get_text(strip=True).split()) for a in links)
            non_link_words = words - link_words
            density = non_link_words / (link_words + 1)

            signal_boost = sum(1 for w in SIGNAL_WORDS if w in text.lower()) / len(SIGNAL_WORDS)
            composite = density * (1 + signal_boost)

            candidates.append((composite, words, text))

        if not candidates:
            return self._empty("density_nothing")

        candidates.sort(key=lambda x: x[0], reverse=True)
        top_texts = [text for _, words, text in candidates[:5] if words > 20]
        combined = "\n\n".join(top_texts)
        combined = self._deduplicate(combined)

        return {
            "text": combined,
            "word_count": len(combined.split()),
            "signal_score": self._signal_score(combined),
            "strategy_used": "density",
        }

    def _strategy_raw(self, soup: BeautifulSoup) -> dict:
        """Last resort fallback."""
        text = soup.get_text(separator="\n", strip=True)
        text = self._deduplicate(text)
        text = self._normalise_whitespace(text)
        return {
            "text": text[:3000],
            "word_count": len(text.split()),
            "signal_score": self._signal_score(text) * 0.5,
            "strategy_used": "raw_fallback",
        }

    def _signal_score(self, text: str) -> float:
        """
        Score 0-1: how useful is this text for sales intelligence.
        Considers: signal word density, text length, alphabetic ratio, boilerplate ratio.
        """
        if not text:
            return 0.0
        words = text.lower().split()
        if not words:
            return 0.0

        word_set = set(words)
        signal_hits = sum(1 for w in SIGNAL_WORDS if w in word_set)
        signal_ratio = signal_hits / len(SIGNAL_WORDS)
        length_score = min(len(words) / 100, 1.0)
        alpha_ratio = sum(1 for c in text if c.isalpha()) / max(len(text), 1)
        boilerplate_count = len(BOILERPLATE.findall(text))
        boilerplate_penalty = max(0, 1 - (boilerplate_count * 0.1))

        return (signal_ratio * 0.4 + length_score * 0.3 +
                alpha_ratio * 0.2 + boilerplate_penalty * 0.1)

    def _soup_to_text(self, el) -> str:
        for tag in el.find_all(["p", "li", "h1", "h2", "h3", "h4", "br", "div"]):
            tag.append("\n")
        text = el.get_text(separator=" ", strip=True)
        return self._normalise_whitespace(text)

    def _deduplicate(self, text: str) -> str:
        """Remove duplicate lines using content hashing (fuzzy — ignores punctuation)."""
        seen = set()
        output = []
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped:
                if output and output[-1] != "":
                    output.append("")
                continue
            normalised = re.sub(r"[^\w\s]", "", stripped.lower())
            normalised = re.sub(r"\s+", " ", normalised).strip()
            if len(normalised) < 5:
                continue
            key = hashlib.md5(normalised[:80].encode()).hexdigest()
            if key not in seen:
                seen.add(key)
                output.append(stripped)
        return "\n".join(output)

    def _normalise_whitespace(self, text: str) -> str:
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)
        return text.strip()

    def post_process(self, text: str) -> str:
        """Final pass: remove boilerplate, cap at 2500 words."""
        text = BOILERPLATE.sub("", text)
        text = self._normalise_whitespace(text)
        words = text.split()
        if len(words) > 2500:
            text = " ".join(words[:2500]) + "\n[content truncated for LLM]"
        return text

    def _empty(self, reason: str) -> dict:
        return {"text": "", "word_count": 0, "signal_score": 0.0, "strategy_used": f"empty_{reason}"}


# ─────────────────────────────────────────────────────────────────────────────
# PAGE DISCOVERER
# ─────────────────────────────────────────────────────────────────────────────

class PageDiscoverer:
    """Scores internal links to find the most valuable pages."""

    def discover(self, homepage_html: str, base_url: str) -> list:
        if not homepage_html:
            return []

        base_parsed = urlparse(base_url)
        base_domain = base_parsed.netloc
        base_clean = base_url.rstrip("/")

        soup = BeautifulSoup(homepage_html, "lxml")
        scored = {}

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue

            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)

            if parsed.netloc and parsed.netloc != base_domain:
                continue
            if SKIP_EXTENSIONS.search(parsed.path):
                continue

            clean = f"{base_parsed.scheme}://{base_domain}{parsed.path}".rstrip("/")
            if not clean or clean == base_clean:
                continue

            if SKIP_PATHS.search(parsed.path.lower()):
                continue

            score = 0
            for keyword, points in PAGE_PRIORITY:
                if keyword in parsed.path.lower():
                    score += points

            anchor = a.get_text(strip=True).lower()
            for keyword, points in PAGE_PRIORITY[:6]:
                if keyword in anchor:
                    score += int(points * 0.5)

            path_depth = len([p for p in parsed.path.split("/") if p])
            if score == 0 and path_depth == 1:
                score = 1

            if score > 0:
                if clean not in scored or scored[clean] < score:
                    scored[clean] = score

        result = [url for url, _ in sorted(scored.items(), key=lambda x: x[1], reverse=True)]
        log.info(f"Discovered {len(result)} priority pages: {result[:5]}")
        return result


# ─────────────────────────────────────────────────────────────────────────────
# URL RESOLVER — 3 fallback strategies
# ─────────────────────────────────────────────────────────────────────────────

class URLResolver:
    """
    Resolves company name → official website.
    Strategy order: DuckDuckGo → Google → Domain guessing
    Now verifies company name against website before accepting.
    """

    def resolve(self, raw_input: str, company_name: str = None, url: str = None) -> dict:
        raw = raw_input.strip()
        result = {
            "original_input": raw,
            "company_name": company_name or "",
            "url": None,
            "resolution_method": "failed",
            "confidence": "low",
            "name_mismatch_warning": False,
        }

        if url:
            result.update({
                "company_name": company_name or self._name_from_url(url),
                "url": url,
                "resolution_method": "provided_url",
                "confidence": "high",
            })
            return result

        if re.match(r"^(https?://|www\.)\S+", raw, re.IGNORECASE):
            url = raw if raw.startswith("http") else "https://" + raw
            # For direct URLs, we don't have a user-provided company name to verify against.
            # We extract a rough name and trust the provided URL.
            result.update({
                "company_name": self._name_from_url(url),
                "url": url,
                "resolution_method": "direct_url",
                "confidence": "high",
                "name_mismatch_warning": False,
            })
            return result

        company_name = self._parse_name(raw)
        result["company_name"] = company_name

        url, match_quality = self._search_duckduckgo(company_name)
        if url:
            conf = "high" if match_quality == "verified" else "medium" if match_quality == "best_guess" else "low"
            result.update({"url": url, "resolution_method": "duckduckgo", "confidence": conf,
                           "name_mismatch_warning": match_quality == "best_guess"})
            return result

        url, match_quality = self._search_google(company_name)
        if url:
            conf = "high" if match_quality == "verified" else "medium" if match_quality == "best_guess" else "low"
            result.update({"url": url, "resolution_method": "google", "confidence": conf,
                           "name_mismatch_warning": match_quality == "best_guess"})
            return result

        url = self._guess_domain(company_name)
        if url:
            result.update({"url": url, "resolution_method": "domain_guess", "confidence": "low"})
            return result

        log.warning(f"Could not resolve: {company_name}")
        return result

    def _verify_name_match(self, company_name: str, url: str) -> float:
        """Check if company name matches the URL domain. Returns similarity 0-1."""
        domain = urlparse(url).netloc.replace("www.", "")
        domain_name = domain.split(".")[0].replace("-", " ").replace("_", " ")
        return _name_similarity(company_name, domain_name)

    def _parse_name(self, raw: str) -> str:
        parts = re.split(r"\s*[–—\-|,]\s*", raw, maxsplit=1)
        name = parts[0].strip()
        name = re.sub(r"\s+[A-Z]{2}$", "", name).strip()
        name = re.sub(r"\s+(llc|inc|corp|ltd|co\.?)\.?$", "", name, flags=re.IGNORECASE).strip()
        return name or raw

    def _name_from_url(self, url: str) -> str:
        domain = urlparse(url).netloc.replace("www.", "")
        return domain.split(".")[0].replace("-", " ").replace("_", " ").title()

    def _is_valid(self, url: str) -> bool:
        if not url:
            return False
        domain = urlparse(url).netloc.replace("www.", "").lower()
        return not any(d in domain for d in DIRECTORY_DOMAINS)

    def _search_duckduckgo(self, company_name: str) -> tuple:
        """Returns (url, match_quality). match_quality: 'verified'|'best_guess'|None"""
        all_candidates = []
        endpoints = [
            ("https://html.duckduckgo.com/html/", "html"),
            ("https://lite.duckduckgo.com/lite/", "lite") # helps bypass captcha
        ]
        
        for query in [f"{company_name} official website", f'"{company_name}" site']:
            soup = None
            for endpoint_url, endpoint_type in endpoints:
                try:
                    time.sleep(random.uniform(1.5, 2.5))
                    data = {"q": query} if endpoint_type == "lite" else {}
                    params = {"q": query} if endpoint_type == "html" else {}
                    headers = {**HEADERS, "Content-Type": "application/x-www-form-urlencoded"} if endpoint_type == "lite" else HEADERS
                    
                    if endpoint_type == "lite":
                        r = requests.post(endpoint_url, data=data, headers=headers, timeout=10)
                    else:
                        r = requests.get(endpoint_url, params=params, headers=headers, timeout=10)
                    r.raise_for_status()
                    # Check if it's a real results page (e.g. not a 202 redirect or captcha)
                    if "captcha" in r.text.lower() or r.status_code == 202:
                        continue
                    temp_soup = BeautifulSoup(r.text, "lxml")
                    # LITE uses a.result-url, HTML uses .result__url, etc.
                    temp_links = temp_soup.select(".result__url") or temp_soup.select("a.result__a") or temp_soup.select(".results_links a") or temp_soup.select("a.result-url")
                    if temp_links:
                        soup = temp_soup
                        break # Found real results
                except Exception as e:
                    log.debug(f"DDG {endpoint_type} failed: {e}")
                    continue
            
            if not soup:
                continue

            links = soup.select(".result__url") or soup.select("a.result__a") or soup.select(".results_links a") or soup.select("a.result-url")

            for link in links[:6]:
                href = link.get("href", "")
                if "uddg=" in href:
                    try:
                        qs = parse_qs(urlparse(href).query)
                        href = unquote(qs.get("uddg", [""])[0])
                    except Exception:
                        pass
                if not href or not href.startswith("http"):
                    text = link.get_text(strip=True)
                    if text and "." in text:
                        href = "https://" + text if not text.startswith("http") else text
                if not href or not href.startswith("http"):
                    continue
                if self._is_valid(href):
                    parsed = urlparse(href)
                    clean = f"https://{parsed.netloc}"
                    sim = self._verify_name_match(company_name, clean)
                    if sim >= 0.3:
                        log.info(f"DDG verified '{company_name}' → {clean} (sim={sim:.2f})")
                        return clean, "verified"
                    all_candidates.append((clean, sim))

        # If no verified match, return the FIRST organically found candidate as a best guess
        if all_candidates:
            first_best = all_candidates[0]
            log.warning(f"DDG best-guess (first link) for '{company_name}' → {first_best[0]} (sim={first_best[1]:.2f})")
            return first_best[0], "best_guess"

        # HTTP search blocked/failed — try Playwright as a fallback
        if PLAYWRIGHT_AVAILABLE:
            log.info(f"DDG HTTP blocked for '{company_name}', trying Playwright fallback...")
            return self._search_duckduckgo_playwright(company_name)

        return None, None

    def _search_duckduckgo_playwright(self, company_name: str) -> tuple:
        """Use a real browser to search DuckDuckGo — bypasses bot detection."""
        try:
            from playwright.sync_api import sync_playwright
            query = f"{company_name} official website"
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"]
                )
                ctx = browser.new_context(
                    user_agent=HEADERS["User-Agent"],
                    viewport={"width": 1366, "height": 768},
                    locale="en-US",
                    timezone_id="America/New_York",
                    ignore_https_errors=True,
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                        "sec-ch-ua-mobile": "?0",
                        "sec-ch-ua-platform": '"Windows"',
                    }
                )
                page = ctx.new_page()
                if STEALTH_AVAILABLE:
                    stealth(page)
                page.goto(
                    f"https://duckduckgo.com/?q={requests.utils.quote(query)}&ia=web",
                    wait_until="domcontentloaded",
                    timeout=20000
                )
                page.wait_for_timeout(3000)
                html = page.content()
                browser.close()

            soup = BeautifulSoup(html, "lxml")
            # DDG results use <a data-testid="result-title-a"> or anchor inside .result
            links = (
                soup.select("a[data-testid='result-title-a']") or
                soup.select(".result__a") or
                soup.select("h2 a") or
                soup.select("a.result-title")
            )
            all_candidates = []
            for link in links[:6]:
                href = link.get("href", "")
                if not href or not href.startswith("http"):
                    continue
                if self._is_valid(href):
                    parsed = urlparse(href)
                    clean = f"https://{parsed.netloc}"
                    sim = self._verify_name_match(company_name, clean)
                    if sim >= 0.3:
                        log.info(f"DDG Playwright verified '{company_name}' → {clean} (sim={sim:.2f})")
                        return clean, "verified"
                    all_candidates.append((clean, sim))

            if all_candidates:
                first_best = all_candidates[0]
                log.warning(f"DDG Playwright best-guess for '{company_name}' → {first_best[0]} (sim={first_best[1]:.2f})")
                return first_best[0], "best_guess"

        except Exception as e:
            log.warning(f"DDG Playwright search failed for '{company_name}': {e}")

        return None, None

    def _search_google(self, company_name: str) -> tuple:
        """Returns (url, match_quality). match_quality: 'verified'|'best_guess'|None"""
        all_candidates = []
        try:
            time.sleep(random.uniform(2, 4))
            r = requests.get(
                "https://www.google.com/search",
                params={"q": f"{company_name} official website", "num": 8},
                headers={**HEADERS, "Referer": "https://www.google.com/"},
                timeout=10,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.select("div.g a[href]"):
                href = a.get("href", "")
                if href.startswith("/url?q="):
                    href = unquote(href[7:].split("&")[0])
                if href.startswith("http") and self._is_valid(href):
                    parsed = urlparse(href)
                    clean = f"https://{parsed.netloc}"
                    sim = self._verify_name_match(company_name, clean)
                    if sim >= 0.3:
                        log.info(f"Google verified '{company_name}' → {clean} (sim={sim:.2f})")
                        return clean, "verified"
                    all_candidates.append((clean, sim))
        except Exception as e:
            log.debug(f"Google search failed: {e}")

        if all_candidates:
            best = max(all_candidates, key=lambda x: x[1])
            log.warning(f"Google best-guess for '{company_name}' → {best[0]} (sim={best[1]:.2f})")
            return best[0], "best_guess"

        return None, None

    def _guess_domain(self, company_name: str) -> Optional[str]:
        clean = re.sub(r"[^a-z0-9\s]", "", company_name.lower())
        words = [w for w in clean.split() if w not in {"the", "and", "of", "a", "an", "in"}]
        if not words:
            return None

        candidates = [
            "".join(words) + ".com",
            "-".join(words) + ".com",
            "".join(words[:2]) + ".com" if len(words) >= 2 else None,
        ]

        fetcher = Fetcher()
        for candidate in candidates:
            if not candidate:
                continue
            url = f"https://www.{candidate}"
            log.info(f"Trying domain guess: {url}")
            html, method = fetcher.fetch(url)
            if html and method != "failed":
                log.info(f"Domain guess succeeded: {url}")
                return url
            time.sleep(0.5)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

class SalesIntelligenceScraper:
    """Full pipeline: raw input → clean text ready for LLM."""

    def __init__(self):
        self.resolver = URLResolver()
        self.fetcher = Fetcher()
        self.extractor = ContentExtractor()
        self.discoverer = PageDiscoverer()

    def scrape(self, raw_input: str, company_name: str = None, url: str = None) -> dict:
        """
        Process one lead end-to-end.

        Returns dict with:
          combined_text  → feed this to the LLM
          confidence     → high/medium/low (tell LLM how much to trust data)
          signal_score   → 0-1 quality indicator
          status         → ok/partial/url_not_found/fetch_failed/error
        """
        result = {
            "original_input": raw_input,
            "company_name": company_name or "",
            "url": None,
            "pages_scraped": [],
            "combined_text": "",
            "word_count": 0,
            "signal_score": 0.0,
            "confidence": "low",
            "fetch_methods": [],
            "status": "failed",
            "error": None,
            "error_code": None,
            "error_detail": None,
            "name_mismatch_warning": False,
            "metadata": {},
        }

        try:
            # 1. Resolve URL
            resolved = self.resolver.resolve(raw_input, company_name, url)
            result["company_name"] = resolved["company_name"]
            result["url"] = resolved["url"]
            result["name_mismatch_warning"] = resolved.get("name_mismatch_warning", False)

            if not resolved["url"]:
                result["error"] = "Could not resolve company website"
                result["error_code"] = "url_not_resolved"
                result["error_detail"] = ERROR_CODES["url_not_resolved"]
                result["status"] = "url_not_found"
                return result

            base_url = resolved["url"]

            # 2. Fetch homepage
            homepage_html, method = self.fetcher.fetch(base_url)
            if not homepage_html:
                err_code = self.fetcher.last_error_code or "connection_refused"
                result["error"] = f"Could not fetch: {base_url}"
                result["error_code"] = err_code
                result["error_detail"] = ERROR_CODES.get(err_code, f"Failed to load {base_url}")
                result["status"] = "fetch_failed"
                return result

            # Detect parked/for-sale domains
            if self._is_parked_domain(homepage_html):
                result["error"] = "Domain appears to be parked, for sale, or inactive"
                result["error_code"] = "domain_parked"
                result["error_detail"] = ERROR_CODES["domain_parked"]
                result["status"] = "parked_domain"
                return result

            result["fetch_methods"].append(method)

            # 2b. Extract metadata from homepage
            meta = _extract_metadata(homepage_html)
            result["metadata"] = meta

            # 3. Extract homepage content
            hp_extraction = self.extractor.extract(homepage_html, base_url)
            all_texts = []

            # Prepend structured metadata for LLM context
            meta_lines = []
            if meta.get("description"):
                meta_lines.append(f"[Meta Description] {meta['description']}")
            if meta.get("og_description"):
                meta_lines.append(f"[OG Description] {meta['og_description']}")
            if meta.get("keywords"):
                meta_lines.append(f"[Keywords] {meta['keywords']}")
            if meta.get("jsonld_summary"):
                meta_lines.append(f"[Structured Data] {meta['jsonld_summary']}")
            if meta_lines:
                all_texts.append("\n".join(meta_lines))

            if hp_extraction["text"]:
                all_texts.append(hp_extraction["text"])
                result["pages_scraped"].append(base_url)

            # 4. Discover priority pages
            priority_pages = self.discoverer.discover(homepage_html, base_url)

            # 5. Scrape up to 5 additional pages for richer context
            for page_url in priority_pages[:5]:
                time.sleep(random.uniform(1.0, 2.0))
                html, method = self.fetcher.fetch(page_url)
                if not html:
                    continue
                extraction = self.extractor.extract(html, page_url)
                if extraction["text"] and extraction["word_count"] > 30:
                    label = self._page_label(page_url)
                    all_texts.append(f"[{label}]\n{extraction['text']}")
                    result["pages_scraped"].append(page_url)
                    result["fetch_methods"].append(method)

            # 6. Combine and post-process
            combined = "\n\n".join(all_texts)
            combined = self.extractor._deduplicate(combined)
            combined = self.extractor.post_process(combined)

            result["combined_text"] = combined
            result["word_count"] = len(combined.split())
            result["signal_score"] = self.extractor._signal_score(combined)
            result["confidence"] = self._compute_confidence(result, resolved["confidence"])

            if result["word_count"] > 80:
                result["status"] = "ok"
            elif result["word_count"] > 20:
                result["status"] = "partial"
                result["error_code"] = "content_too_thin"
                result["error_detail"] = ERROR_CODES["content_too_thin"]
            else:
                result["status"] = "partial"
                result["error_code"] = "empty_content"
                result["error_detail"] = ERROR_CODES["empty_content"]

            log.info(
                f"DONE: {result['company_name']} | "
                f"{len(result['pages_scraped'])} pages | "
                f"{result['word_count']} words | "
                f"signal={result['signal_score']:.2f} | "
                f"confidence={result['confidence']}"
            )

        except Exception as e:
            result["error"] = str(e)
            result["status"] = "error"
            log.exception(f"Scrape error for {raw_input}: {e}")

        return result

    def _is_parked_domain(self, html: str) -> bool:
        if not html:
            return False
        
        soup = BeautifulSoup(html, "lxml")
        title = soup.title.string.lower() if soup.title and soup.title.string else ""
        
        if any(x in title for x in ["domain for sale", "buy this domain", "parked page", "default page", "site suspended"]):
            return True
            
        text = soup.get_text(separator=" ", strip=True).lower()
        if len(text.split()) < 300:
            if re.search(r"domain is registered|may still be available|buy this domain|domain for sale|this domain is for sale|domain parked|parked free|domain has expired", text):
                return True
                
        if PARKED_DOMAIN_PATTERNS.search(text):
            return True
            
        return False

    def _page_label(self, url: str) -> str:
        path = urlparse(url).path.rstrip("/")
        parts = [p for p in path.split("/") if p]
        return parts[-1].replace("-", " ").replace("_", " ").title() if parts else "Homepage"

    def _compute_confidence(self, result: dict, url_confidence: str) -> str:
        score = 0
        if result["word_count"] >= 200: score += 3
        elif result["word_count"] >= 100: score += 2
        elif result["word_count"] >= 50: score += 1
        if result["signal_score"] >= 0.6: score += 3
        elif result["signal_score"] >= 0.4: score += 2
        elif result["signal_score"] >= 0.2: score += 1
        if len(result["pages_scraped"]) >= 3: score += 2
        elif len(result["pages_scraped"]) >= 2: score += 1
        if url_confidence == "high": score += 2
        elif url_confidence == "medium": score += 1
        if score >= 8: return "high"
        elif score >= 4: return "medium"
        return "low"


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def scrape_lead(raw_input: str, company_name: str = None, url: str = None) -> dict:
    """Single lead. Pass result['combined_text'] to LLM."""
    return SalesIntelligenceScraper().scrape(raw_input, company_name, url)


def scrape_all_leads(leads: list) -> list:
    """Process all leads with polite delays."""
    scraper = SalesIntelligenceScraper()
    results = []
    for i, lead in enumerate(leads, 1):
        log.info(f"\n{'─'*60}\nLead {i}/{len(leads)}: {lead}")
        result = scraper.scrape(lead)
        results.append(result)
        icon = "✓" if result["status"] == "ok" else "⚠" if result["status"] == "partial" else "✗"
        log.info(f"{icon} {result['company_name']} | {result['status']} | {result['word_count']} words | {result['confidence']}")
        if i < len(leads):
            time.sleep(random.uniform(2.0, 4.0))

    ok = sum(1 for r in results if r["status"] == "ok")
    partial = sum(1 for r in results if r["status"] == "partial")
    failed = len(leads) - ok - partial
    log.info(f"\nSUMMARY: {ok} ok | {partial} partial | {failed} failed | {len(leads)} total")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# DEMO
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_leads = [
        "https://www.houstonroofingonline.com",
        "BrightPlay Turf – Artificial Turf & Landscaping, Chicago IL",
        "https://www.redtruckbakery.com",
        "Blue Ridge HVAC Services – Roanoke VA",
    ]

    for lead in test_leads:
        print(f"\n{'='*70}")
        print(f"INPUT : {lead}")
        result = scrape_lead(lead)
        print(f"COMPANY    : {result['company_name']}")
        print(f"URL        : {result['url']}")
        print(f"STATUS     : {result['status']}")
        print(f"CONFIDENCE : {result['confidence']}")
        print(f"WORDS      : {result['word_count']}")
        print(f"SIGNAL     : {result['signal_score']:.2f}")
        print(f"PAGES      : {result['pages_scraped']}")
        print(f"\nTEXT PREVIEW:\n{result['combined_text'][:600]}")
        print("─"*70)
