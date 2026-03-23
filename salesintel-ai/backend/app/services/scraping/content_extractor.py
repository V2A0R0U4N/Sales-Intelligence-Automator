"""
Content Extractor — Primary: trafilatura, with BeautifulSoup metadata extraction.
"""
import re
import hashlib
import structlog
from typing import Optional

import trafilatura
from bs4 import BeautifulSoup

logger = structlog.get_logger("scraping.content")

# Boilerplate patterns to clean
BOILERPLATE_PATTERNS = re.compile(
    r"(call\s+us\s+today|call\s+now|free\s+(estimate|quote|consultation)|"
    r"contact\s+us\s+today|get\s+in\s+touch|licensed\s+and\s+insured|"
    r"follow\s+us\s+on|like\s+us\s+on\s+facebook|all\s+rights\s+reserved|"
    r"copyright\s*\d{4}|powered\s+by|website\s+by|designed\s+by|"
    r"click\s+here|sign\s+up\s+for\s+our\s+newsletter|"
    r"skip\s+to\s+(main\s+)?content|back\s+to\s+top)",
    re.IGNORECASE,
)

# Parked domain detection
PARKED_DOMAIN_PATTERNS = re.compile(
    r"(this domain is registered|get this domain|buy this domain|"
    r"domain for sale|domain parked by|parked free|"
    r"this domain has expired|future home of|"
    r"inquire about this domain|account suspended|"
    r"default web site page|website is pending)",
    re.IGNORECASE,
)

# Login wall detection
LOGIN_PATTERNS = re.compile(
    r"(please\s+(log\s*in|sign\s*in)|login\s+required|"
    r"you\s+must\s+(log\s*in|sign\s*in)|"
    r"access\s+denied|authentication\s+required)",
    re.IGNORECASE,
)


class ContentExtractor:
    """Extract clean text from HTML using trafilatura + BS4 metadata."""

    def extract(self, html: str, url: str = "") -> dict:
        """
        Extract content from HTML.
        Returns: {text, word_count, headings, meta, source_url, flags}
        """
        if not html:
            return self._empty("no_html")

        # Check for parked domain
        if PARKED_DOMAIN_PATTERNS.search(html[:3000]):
            return {
                **self._empty("parked_domain"),
                "flags": {"parked_domain": True},
            }

        # Check for login wall
        if LOGIN_PATTERNS.search(html[:3000]):
            return {
                **self._empty("login_required"),
                "flags": {"login_required": True},
            }

        # Primary extraction with trafilatura
        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            include_links=False,
            include_images=False,
            output_format="txt",
            favor_recall=True,
            url=url,
        )

        # Extract metadata separately with BS4
        meta = self._extract_metadata(html)
        headings = self._extract_headings(html)

        # Build combined text
        parts = []
        if meta.get("title"):
            parts.append(f"TITLE: {meta['title']}")
        if meta.get("description"):
            parts.append(f"DESCRIPTION: {meta['description']}")
        if headings:
            parts.append(f"HEADINGS: {' | '.join(headings)}")
        if extracted:
            parts.append(extracted)

        # Also extract footer text (often has taglines)
        footer_text = self._extract_footer(html)
        if footer_text:
            parts.append(f"FOOTER: {footer_text}")

        combined = "\n\n".join(parts)
        combined = self._clean_text(combined)
        word_count = len(combined.split()) if combined else 0

        return {
            "text": combined,
            "word_count": word_count,
            "headings": headings,
            "meta": meta,
            "source_url": url,
            "flags": {
                "parked_domain": False,
                "login_required": False,
                "thin_content": word_count < 150,
            },
        }

    def _extract_metadata(self, html: str) -> dict:
        """Extract meta tags, OG data, and JSON-LD."""
        meta = {"title": "", "description": "", "og_title": "", "og_description": "", "keywords": ""}
        try:
            soup = BeautifulSoup(html, "lxml")

            # Title
            title_tag = soup.find("title")
            if title_tag:
                meta["title"] = title_tag.get_text(strip=True)

            # Meta description
            desc = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
            if desc and desc.get("content"):
                meta["description"] = desc["content"].strip()

            # OG tags
            for prop in ["og:title", "og:description"]:
                tag = soup.find("meta", attrs={"property": prop})
                if tag and tag.get("content"):
                    key = prop.replace("og:", "og_")
                    meta[key] = tag["content"].strip()

            # Keywords
            kw = soup.find("meta", attrs={"name": re.compile(r"keywords", re.I)})
            if kw and kw.get("content"):
                meta["keywords"] = kw["content"].strip()

        except Exception as e:
            logger.warning("metadata_extraction_error", error=str(e))

        return meta

    def _extract_headings(self, html: str) -> list[str]:
        """Extract all h1, h2, h3 headings."""
        try:
            soup = BeautifulSoup(html, "lxml")
            headings = []
            for tag in soup.find_all(["h1", "h2", "h3"]):
                text = tag.get_text(strip=True)
                if text and len(text) > 2:
                    headings.append(text)
            return headings[:30]  # Cap at 30
        except Exception:
            return []

    def _extract_footer(self, html: str) -> str:
        """Extract footer text — often contains taglines."""
        try:
            soup = BeautifulSoup(html, "lxml")
            footer = soup.find("footer")
            if footer:
                text = footer.get_text(separator=" ", strip=True)
                # Only return if it's not just copyright/legal text
                if len(text.split()) > 5 and not text.lower().startswith("copyright"):
                    return text[:500]
        except Exception:
            pass
        return ""

    def _clean_text(self, text: str) -> str:
        """Remove boilerplate, normalize whitespace, deduplicate."""
        if not text:
            return ""
        # Remove boilerplate
        text = BOILERPLATE_PATTERNS.sub("", text)
        # Deduplicate lines
        text = self._deduplicate_lines(text)
        # Normalize whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)
        # Cap at 3000 words
        words = text.split()
        if len(words) > 3000:
            text = " ".join(words[:3000]) + "\n[content truncated]"
        return text.strip()

    def _deduplicate_lines(self, text: str) -> str:
        """Remove duplicate lines using content hashing."""
        seen = set()
        output = []
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped:
                if output and output[-1] != "":
                    output.append("")
                continue
            normalized = re.sub(r"[^\w\s]", "", stripped.lower())
            normalized = re.sub(r"\s+", " ", normalized).strip()
            if len(normalized) < 5:
                continue
            key = hashlib.md5(normalized[:80].encode()).hexdigest()
            if key not in seen:
                seen.add(key)
                output.append(stripped)
        return "\n".join(output)

    def _empty(self, reason: str) -> dict:
        return {
            "text": "",
            "word_count": 0,
            "headings": [],
            "meta": {},
            "source_url": "",
            "flags": {"parked_domain": False, "login_required": False, "thin_content": True},
        }
