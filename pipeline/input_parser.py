"""
Input Parser — Parses raw lead text and classifies each line as URL or name-only.
Handles messy real-world formats: URLs, company names with location, service hints.
"""
from __future__ import annotations

import re
from models.schemas import ParsedLead


def parse_leads(raw_text: str) -> list[ParsedLead]:
    """
    Parse raw text input into structured ParsedLead objects.
    Each non-empty line becomes one lead.

    Supported formats:
    - https://www.example.com              → URL
    - www.example.com                      → URL (protocol added)
    - Company Name – City ST               → Name-only
    - Company Name – Service, City ST      → Name-only with service hint
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


def _classify_line(line: str) -> ParsedLead:
    """Classify a single line as URL, Name+URL, or name-only and extract fields."""

    # 1. Check if line contains both a name and a URL
    # Look for a URL pattern anywhere in the string
    url_match = re.search(r"(https?://\S+|www\.\S+)", line, re.IGNORECASE)
    if url_match:
        url_part = url_match.group(1)
        name_part = line.replace(url_part, "").strip()
        # Clean up any leftover punctuation from the removal
        name_part = re.sub(r"^[\s,\-–—|]+|[\s,\-–—|]+$", "", name_part)

        url = _normalize_url(url_part)

        # If name is empty, it was just a URL line
        if not name_part:
            company_name = _extract_name_from_url(url)
            return ParsedLead(
                raw_input=line,
                input_type="url",
                url=url,
                company_name=company_name,
            )

        # It's a Name + URL format
        return ParsedLead(
            raw_input=line,
            input_type="name_and_url",
            url=url,
            company_name=name_part,
        )

    # 2. Check if line is purely a URL (handled by regex above, but keeping for safety if regex misses something)
    if _is_url(line):
        url = _normalize_url(line)
        company_name = _extract_name_from_url(url)
        return ParsedLead(
            raw_input=line,
            input_type="url",
            url=url,
            company_name=company_name,
        )

    # 3. Otherwise, it's a name-only input — extract parts
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
    # Remove protocol and www
    name = re.sub(r"https?://(www\.)?", "", url)
    # Remove trailing path and TLD
    name = name.split("/")[0]  # Remove path
    name = re.sub(r"\.(com|net|org|co|io|us|biz)$", "", name)
    # Convert dashes/dots to spaces and title-case
    name = name.replace("-", " ").replace(".", " ").strip()
    return name.title()


def _parse_name_input(line: str) -> ParsedLead:
    """
    Parse a name-only input line.

    Handles formats like:
    - "BrightPlay Turf – Artificial Turf & Landscaping, Chicago IL"
    - "Joe's Backyard Landscaping – Phoenix AZ"
    - "Blue Ridge HVAC Services – Roanoke VA"
    - "Acme Roofing & Construction – Dallas TX"
    """
    company_name = line
    location = None
    service_hint = None

    # Split on common separators: – — -
    # The dash/em-dash usually separates company name from location/service
    parts = re.split(r"\s*[–—]\s*", line, maxsplit=1)

    if len(parts) == 2:
        company_name = parts[0].strip()
        rest = parts[1].strip()

        # Check if rest contains a comma (service, location format)
        if "," in rest:
            sub_parts = rest.rsplit(",", maxsplit=1)
            service_hint = sub_parts[0].strip()
            location = sub_parts[1].strip()
        else:
            # Check if rest looks like a location (ends with state abbreviation)
            state_match = re.search(
                r"\b([A-Z]{2})\s*$", rest
            )
            if state_match:
                location = rest
            else:
                # Could be service description or location
                service_hint = rest

    # If no dash separator found, try comma separation
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
