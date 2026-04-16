"""
Deep Enrichment Pipeline
========================
Extracts firmographic signals from already-scraped website content.
No additional API calls needed — pure LLM inference on existing content.

Enrichment signals extracted:
  - Tech stack detection (from HTML meta, scripts, headers)
  - Company size estimation (from content clues)
  - Trigger events (from news/about pages)
  - Decision maker identification (from team/about pages)
  - Social media links
"""

import os
import re
import json
import time
import logging
from typing import Optional
from groq import Groq

from models.enrichment_schemas import (
    EnrichedData, TechStackItem, TriggerEvent, DecisionMaker,
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Tech Stack Detection (rule-based from HTML content)
# ─────────────────────────────────────────────────────────────

TECH_SIGNATURES = {
    # CMS
    "WordPress": (r"wp-content|wordpress", "CMS"),
    "Shopify": (r"cdn\.shopify\.com|myshopify", "E-Commerce"),
    "Wix": (r"wix\.com|wixsite", "CMS"),
    "Squarespace": (r"squarespace\.com|sqsp", "CMS"),
    "Webflow": (r"webflow\.io|webflow", "CMS"),
    "Drupal": (r"drupal\.org|drupal", "CMS"),
    # Analytics
    "Google Analytics": (r"google-analytics\.com|gtag|UA-\d+|G-\w+", "Analytics"),
    "Google Tag Manager": (r"googletagmanager\.com|GTM-\w+", "Tag Manager"),
    "Hotjar": (r"hotjar\.com|hjid", "Analytics"),
    "Mixpanel": (r"mixpanel\.com", "Analytics"),
    # Marketing
    "HubSpot": (r"hubspot\.com|hs-script|hbspt", "Marketing/CRM"),
    "Mailchimp": (r"mailchimp\.com|mc\.js", "Email Marketing"),
    "Intercom": (r"intercom\.io|intercomSettings", "Customer Support"),
    "Drift": (r"drift\.com|driftt", "Sales Chat"),
    "Salesforce": (r"salesforce\.com|pardot", "CRM"),
    "Zendesk": (r"zendesk\.com|zdassets", "Customer Support"),
    # Development
    "React": (r"react\.js|reactDOM|__NEXT_DATA__", "Frontend Framework"),
    "Next.js": (r"__NEXT_DATA__|next\.js|_next/", "Frontend Framework"),
    "Vue.js": (r"vue\.js|vuejs", "Frontend Framework"),
    "Angular": (r"angular\.js|ng-app|angular\.io", "Frontend Framework"),
    "jQuery": (r"jquery\.min\.js|jquery\.com", "JavaScript Library"),
    # Infrastructure
    "Cloudflare": (r"cloudflare\.com|cf-ray", "CDN/Security"),
    "AWS": (r"amazonaws\.com|aws\.amazon", "Cloud"),
    "Google Cloud": (r"googleapis\.com|gstatic\.com", "Cloud"),
    "Stripe": (r"stripe\.com|stripe\.js", "Payments"),
    # Business tools
    "ConnectWise": (r"connectwise", "PSA/RMM"),
    "Datto": (r"datto\.com", "RMM/Backup"),
    "Autodesk": (r"autodesk|autocad|revit", "CAD/BIM"),
}


def detect_tech_stack(html_content: str) -> list[TechStackItem]:
    """Detect technologies from raw HTML content using regex patterns."""
    found = []
    content_lower = html_content.lower()

    for tech_name, (pattern, category) in TECH_SIGNATURES.items():
        if re.search(pattern, content_lower, re.IGNORECASE):
            found.append(TechStackItem(
                name=tech_name,
                category=category,
                confidence="high",
            ))

    return found[:15]  # Cap at 15 items


# ─────────────────────────────────────────────────────────────
# Social Links Extraction
# ─────────────────────────────────────────────────────────────

SOCIAL_PATTERNS = {
    "linkedin": r"https?://(?:www\.)?linkedin\.com/(?:company|in)/[\w\-]+/?",
    "twitter": r"https?://(?:www\.)?(?:twitter|x)\.com/[\w]+/?",
    "facebook": r"https?://(?:www\.)?facebook\.com/[\w\.\-]+/?",
    "instagram": r"https?://(?:www\.)?instagram\.com/[\w\.]+/?",
    "youtube": r"https?://(?:www\.)?youtube\.com/(?:c/|channel/|@)[\w\-]+/?",
}


def extract_social_links(html_content: str) -> dict:
    """Extract social media links from HTML content."""
    socials = {}
    for platform, pattern in SOCIAL_PATTERNS.items():
        match = re.search(pattern, html_content, re.IGNORECASE)
        if match:
            socials[platform] = match.group()
    return socials


# ─────────────────────────────────────────────────────────────
# LLM-based Enrichment (size, triggers, contacts)
# ─────────────────────────────────────────────────────────────

ENRICHMENT_PROMPT = """\
You are a B2B sales intelligence analyst. Extract enrichment data from this website content.

Company: {company_name}
Website: {website}

CONTENT:
{content}

Extract the following and return ONLY valid JSON:
{{
  "employee_estimate": "estimate employee count range e.g. '50-200' or 'Unknown'",
  "revenue_estimate": "estimate annual revenue range e.g. '$5M-$20M' or 'Unknown'",
  "founded_year": "year founded or 'Unknown'",
  "headquarters": "city, state/country or 'Unknown'",
  "trigger_events": [
    {{"headline": "brief event description", "event_type": "funding|hiring|expansion|leadership|product_launch", "relevance": "high|medium|low"}}
  ],
  "decision_makers": [
    {{"name": "full name", "title": "job title", "linkedin_url": "url if found in content", "confidence": "high|medium|low"}}
  ]
}}

RULES:
- Only include information that can be inferred from the content
- For decision_makers, look for leadership/team pages, about sections
- For trigger_events, look for news, press releases, recent announcements
- Max 3 trigger_events, max 3 decision_makers
- If nothing found, use empty arrays and 'Unknown'
"""


async def enrich_lead(
    company_name: str,
    website: str,
    content: str,
    html_content: str = "",
) -> dict:
    """
    Run the full enrichment pipeline on a lead.
    
    Args:
        company_name: Company name
        website: Company website URL
        content: Cleaned text content from scraper
        html_content: Raw HTML for tech detection (optional)
    
    Returns:
        EnrichedData as a dict
    """
    import asyncio

    log.info(f"[Enrichment] Enriching: {company_name}")

    # Step 1: Rule-based tech stack detection (from HTML)
    tech_stack = detect_tech_stack(html_content or content)
    log.info(f"[Enrichment]   Tech stack: {len(tech_stack)} items detected")

    # Step 2: Social links extraction
    social_links = extract_social_links(html_content or content)
    log.info(f"[Enrichment]   Social links: {list(social_links.keys())}")

    # Step 3: LLM-based enrichment (size, triggers, contacts)
    llm_enrichment = await _llm_enrich(company_name, website, content)

    # Combine results
    enriched = EnrichedData(
        employee_estimate=llm_enrichment.get("employee_estimate", "Unknown"),
        revenue_estimate=llm_enrichment.get("revenue_estimate", "Unknown"),
        founded_year=llm_enrichment.get("founded_year", "Unknown"),
        headquarters=llm_enrichment.get("headquarters", "Unknown"),
        tech_stack=tech_stack,
        trigger_events=[
            TriggerEvent(**t) for t in llm_enrichment.get("trigger_events", [])[:3]
        ],
        decision_makers=[
            DecisionMaker(**d) for d in llm_enrichment.get("decision_makers", [])[:3]
        ],
        social_links=social_links,
        enrichment_confidence="high" if (tech_stack and llm_enrichment.get("employee_estimate", "Unknown") != "Unknown") else "medium",
    )

    # Generate email guesses for decision makers
    domain = _extract_domain(website)
    if domain:
        for dm in enriched.decision_makers:
            if dm.name and dm.name != "Not found":
                dm.email_guesses = _guess_emails(dm.name, domain)

    # Back-fill LinkedIn URL from social links
    if social_links.get("linkedin"):
        for dm in enriched.decision_makers:
            if not dm.linkedin_url:
                dm.linkedin_url = social_links["linkedin"]

    log.info(f"[Enrichment] Complete: {company_name} — confidence={enriched.enrichment_confidence}")
    return enriched.model_dump()


async def _llm_enrich(company_name: str, website: str, content: str) -> dict:
    """Use LLM to extract firmographic data from website content."""
    import asyncio

    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    prompt = ENRICHMENT_PROMPT.format(
        company_name=company_name,
        website=website,
        content=content[:4000],
    )

    try:
        await asyncio.sleep(2.0)  # Rate limit
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=800,
        )
        raw = response.choices[0].message.content.strip()

        # Extract JSON
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return data
    except Exception as e:
        log.error(f"[Enrichment] LLM enrichment failed: {e}")

    return {}


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")
        return domain
    except Exception:
        return ""


def _guess_emails(full_name: str, domain: str) -> list[str]:
    """Generate common email pattern guesses."""
    parts = full_name.lower().split()
    if len(parts) < 2:
        return [f"{parts[0]}@{domain}"]

    first = parts[0]
    last = parts[-1]

    return [
        f"{first}.{last}@{domain}",
        f"{first[0]}{last}@{domain}",
        f"{first}@{domain}",
        f"{first}{last[0]}@{domain}",
    ]
