"""
Input Parser — Parses raw lead text and classifies each line as URL, name-only,
or region query. Handles messy real-world formats.
"""
from __future__ import annotations

import re
from models.schemas import ParsedLead


# Category keywords for detecting region-based queries
CATEGORY_KEYWORDS = {
    "technology": ["tech", "it ", "software", "saas", "technology", "digital tech", "information technology"],
    "digital": ["digital", "marketing", "advertising", "seo", "social media", "web design", "branding"],
    "design_cad": ["design", "cad", "architecture", "drafting", "interior", "graphic design", "3d"],
    "manufacturing": ["manufacturing", "industrial", "factory", "fabricat", "production"],
    "healthcare": ["healthcare", "medical", "hospital", "pharma", "health", "clinic"],
    "finance": ["finance", "accounting", "bank", "fintech", "investment", "insurance"],
    "consulting": ["consulting", "consultancy", "advisory", "management consulting"],
    "education": ["education", "training", "school", "university", "edtech", "learning"],
    "retail": ["retail", "ecommerce", "e-commerce", "store", "shop", "commerce"],
}

# Signals that a line is a region query rather than a company name
REGION_SIGNALS = re.compile(
    r"\b(companies|firms|agencies|startups|businesses|studios|shops|providers|vendors|organizations|organisations)\b",
    re.IGNORECASE,
)

# Common geographic keywords that boost region detection
GEO_SIGNALS = re.compile(
    r"\b(in |near |around |based in |from |located in )\b",
    re.IGNORECASE,
)


def parse_leads(raw_text: str) -> list[ParsedLead]:
    """
    Parse raw text input into structured ParsedLead objects.
    Each non-empty line becomes one lead.

    Supported formats:
    - https://www.example.com              → URL
    - www.example.com                      → URL (protocol added)
    - Company Name – City ST               → Name-only
    - Company Name – Service, City ST      → Name-only with service hint
    - Ahmedabad Tech Companies             → Region query (auto-detected)
    """
    leads = []
    lines = raw_text.strip().split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Decode HTML entities commonly seen in copy-paste
        line = line.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')

        lead = _classify_line(line)
        leads.append(lead)

    return leads


def _detect_region_query(line: str) -> dict | None:
    """
    Check if a line is a region-based discovery query rather than a company name.
    Returns {region, category} if detected, else None.

    Examples:
    - "Ahmedabad Tech Companies"     → region=Ahmedabad, category=technology
    - "tech companies in Gujarat"    → region=Gujarat, category=technology
    - "manufacturing firms in Europe" → region=Europe, category=manufacturing
    """
    line_lower = line.lower().strip()

    # Must contain a region signal word (companies, firms, agencies, etc.)
    if not REGION_SIGNALS.search(line_lower):
        return None

    # Detect category from keywords
    detected_category = None
    for cat_key, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in line_lower:
                detected_category = cat_key
                break
        if detected_category:
            break

    if not detected_category:
        detected_category = "technology"  # Default

    # Extract region by removing the category + signal words
    region = line
    # Remove known category keywords
    for keywords in CATEGORY_KEYWORDS.values():
        for kw in keywords:
            region = re.sub(rf"\b{re.escape(kw)}\b", "", region, flags=re.IGNORECASE)
    # Remove signal words
    region = REGION_SIGNALS.sub("", region)
    # Remove geo prepositions
    region = GEO_SIGNALS.sub("", region)
    # Clean up extra whitespace and punctuation
    region = re.sub(r"[,\-–—|]+", " ", region)
    region = re.sub(r"\s+", " ", region).strip()

    if not region or len(region) < 2:
        return None

    return {"region": region, "category": detected_category}


def _classify_line(line: str) -> ParsedLead:
    """Classify a single line as URL, Name+URL, region query, or name-only."""

    # 0. Check for region query FIRST (before treating as company name)
    region_result = _detect_region_query(line)
    if region_result:
        return ParsedLead(
            raw_input=line,
            input_type="region_query",
            company_name=None,
            location=region_result["region"],
            category=region_result["category"],
        )

    # 1. Check if line contains both a name and a URL
    url_match = re.search(r"(https?://\S+|www\.\S+)", line, re.IGNORECASE)
    if url_match:
        url_part = url_match.group(1)
        name_part = line.replace(url_part, "").strip()
        name_part = re.sub(r"^[\s,\-–—|]+|[\s,\-–—|]+$", "", name_part)

        url = _normalize_url(url_part)

        if not name_part:
            company_name = _extract_name_from_url(url)
            return ParsedLead(
                raw_input=line,
                input_type="url",
                url=url,
                company_name=company_name,
            )

        return ParsedLead(
            raw_input=line,
            input_type="name_and_url",
            url=url,
            company_name=name_part,
        )

    # 2. Check if line is purely a URL
    if _is_url(line):
        url = _normalize_url(line)
        company_name = _extract_name_from_url(url)
        return ParsedLead(
            raw_input=line,
            input_type="url",
            url=url,
            company_name=company_name,
        )

    # 3. Otherwise, it's a name-only input
    return _parse_name_input(line)


def _is_url(text: str) -> bool:
    """Check if text looks like a URL."""
    text_lower = text.lower().strip()
    return (
        text_lower.startswith("http://")
        or text_lower.startswith("https://")
        or text_lower.startswith("www.")
    )


def _normalize_url(url: str) -> str:
    """Add protocol if missing."""
    url = url.strip()
    if url.lower().startswith("www."):
        url = "https://" + url
    return url


def _extract_name_from_url(url: str) -> str:
    """Extract a rough company name from a URL for display purposes."""
    name = re.sub(r"https?://(www\.)?", "", url)
    name = name.split("/")[0]
    name = re.sub(r"\.(com|net|org|co|io|us|biz)$", "", name)
    name = name.replace("-", " ").replace(".", " ").strip()
    return name.title()


def _parse_name_input(line: str) -> ParsedLead:
    """
    Parse a name-only input line.

    Handles formats like:
    - "BrightPlay Turf – Artificial Turf & Landscaping, Chicago IL"
    - "Joe's Backyard Landscaping – Phoenix AZ"
    - "Blue Ridge HVAC Services – Roanoke VA"
    """
    company_name = line
    location = None
    service_hint = None

    parts = re.split(r"\s*[–—]\s*", line, maxsplit=1)

    if len(parts) == 2:
        company_name = parts[0].strip()
        rest = parts[1].strip()

        if "," in rest:
            sub_parts = rest.rsplit(",", maxsplit=1)
            service_hint = sub_parts[0].strip()
            location = sub_parts[1].strip()
        else:
            state_match = re.search(r"\b([A-Z]{2})\s*$", rest)
            if state_match:
                location = rest
            else:
                service_hint = rest

    elif "," in line:
        parts = line.rsplit(",", maxsplit=1)
        company_name = parts[0].strip()
        location = parts[1].strip()

    return ParsedLead(
        raw_input=line,
        input_type="name_only",
        company_name=company_name,
        location=location,
        service_hint=service_hint,
    )
