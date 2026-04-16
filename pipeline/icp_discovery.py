"""
ICP-Driven Smart Discovery Engine
==================================
The "30 → 5" flow:
  1. User's CompanyICP profile → LLM generates 8 search queries
  2. DuckDuckGo executes searches → collects up to 30 unique companies
  3. LLM scoring pass → ranks each against ICP, discards <70
  4. Returns scored preview cards with "Why this lead?" snippets

All free — uses DuckDuckGo (no API key) + Groq (free tier).
"""

import os
import re
import json
import time
import random
import logging
from typing import Optional
from pydantic import BaseModel, Field

from groq import Groq

log = logging.getLogger(__name__)

# Reuse existing DuckDuckGo search from region_discovery
from pipeline.region_discovery import _search_ddg, ALWAYS_BLOCKED


# ─────────────────────────────────────────────────────────────
# Output model for discovery preview cards
# ─────────────────────────────────────────────────────────────

class LeadPreviewCard(BaseModel):
    """A single discovered lead before full pipeline processing."""
    name: str = ""
    url: str = ""
    snippet: str = ""
    icp_score: int = 0              # 0-100, set by LLM scoring pass
    why_this_lead: str = ""         # 1-sentence explanation
    fit_signals: list[str] = Field(default_factory=list)
    category: str = ""
    region: str = ""


# ─────────────────────────────────────────────────────────────
# Step 1: Generate search queries from ICP
# ─────────────────────────────────────────────────────────────

QUERY_GEN_PROMPT = """\
You are a lead generation expert. Given the ICP (Ideal Customer Profile) below,
generate exactly 8 diverse DuckDuckGo search queries to find potential B2B leads.

ICP:
- Company: {company_name}
- Offers: {company_description}
- Target Industries: {industries}
- Target Geographies: {geographies}
- Pain Points We Solve: {pain_points}
- Tech Stack Signals: {tech_signals}

RULES:
1. Each query must target a DIFFERENT angle:
   - 2 queries: industry + geography (e.g. "IT consulting firms in Gujarat")
   - 2 queries: pain point + geography (e.g. "companies struggling with IT support Texas")
   - 2 queries: tech stack + business type (e.g. "ConnectWise partners small business")
   - 2 queries: competitor alternatives (e.g. "companies looking for CAD outsourcing alternative")
2. Each query should be 4-8 words for best DDG results
3. Do NOT include our company name in the queries
4. Return ONLY a JSON array of 8 query strings, nothing else

Example output:
["IT managed services companies Gujarat", "MSP providers small business Texas", ...]
"""


def _generate_search_queries(icp_profile: dict) -> list[str]:
    """
    Use LLM to generate 8 targeted search queries from the ICP.
    Returns a list of query strings.
    """
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    industries = ", ".join(icp_profile.get("target_industries", [])[:6])
    geographies = ", ".join(icp_profile.get("target_geographies", [])[:4])
    pain_points = ", ".join(icp_profile.get("pain_point_keywords", [])[:5])
    tech_signals = ", ".join(icp_profile.get("tech_stack_signals", [])[:5])

    prompt = QUERY_GEN_PROMPT.format(
        company_name=icp_profile.get("your_company_name", ""),
        company_description=icp_profile.get("your_company_description", ""),
        industries=industries or "General B2B",
        geographies=geographies or "United States",
        pain_points=pain_points or "business challenges",
        tech_signals=tech_signals or "enterprise software",
    )

    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",   # Fast, free
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=400,
        )

        raw = response.choices[0].message.content.strip()

        # Extract JSON array from response
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        if match:
            queries = json.loads(match.group())
            if isinstance(queries, list) and len(queries) > 0:
                log.info(f"[ICPDiscovery] Generated {len(queries)} search queries")
                return [str(q) for q in queries[:8]]

        log.warning("[ICPDiscovery] LLM did not return valid JSON array, using fallback")
    except Exception as e:
        log.error(f"[ICPDiscovery] Query generation failed: {e}")

    # Fallback: generate basic queries from ICP fields
    fallback = []
    for ind in icp_profile.get("target_industries", [])[:3]:
        for geo in icp_profile.get("target_geographies", [])[:2]:
            fallback.append(f"{ind} companies {geo}")
    if not fallback:
        fallback = ["small business services companies USA"]
    return fallback[:8]


# ─────────────────────────────────────────────────────────────
# Step 2: Execute DuckDuckGo searches
# ─────────────────────────────────────────────────────────────

def _execute_searches(queries: list[str], max_results: int = 30) -> list[dict]:
    """
    Run DuckDuckGo searches for each query and collect unique company candidates.
    Returns a list of dicts: [{name, url, snippet}, ...]
    """
    seen_domains = set()
    candidates = []

    for query in queries:
        if len(candidates) >= max_results:
            break

        log.info(f"[ICPDiscovery] Searching: {query}")
        results = _search_ddg(query)
        time.sleep(random.uniform(1.0, 2.0))  # Respectful rate limiting

        for r in results:
            url = r.get("url", "")
            title = r.get("title", "")
            snippet = r.get("snippet", "")

            if not url:
                continue

            # Extract domain
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.replace("www.", "").lower()

            # Skip duplicates and blocked domains
            if domain in seen_domains:
                continue
            if domain in ALWAYS_BLOCKED:
                continue

            seen_domains.add(domain)

            # Clean company name from title
            name = re.split(r"\s*[-–—|]\s*", title, maxsplit=1)[0].strip()
            if not name or len(name) < 2:
                name = domain.split(".")[0].replace("-", " ").title()

            candidates.append({
                "name": name,
                "url": url,
                "snippet": snippet[:200],
                "domain": domain,
            })

            if len(candidates) >= max_results:
                break

    log.info(f"[ICPDiscovery] Found {len(candidates)} unique candidates")
    return candidates


# ─────────────────────────────────────────────────────────────
# Step 3: LLM ICP scoring pass
# ─────────────────────────────────────────────────────────────

SCORING_PROMPT = """\
You are an ICP (Ideal Customer Profile) scoring engine.

OUR COMPANY:
- Name: {company_name}
- What we offer: {company_description}
- Target industries: {industries}

Score these companies 0-100 on how well they match our ICP.
70+ = good fit, 50-69 = maybe, <50 = poor fit.

For each company, return:
- score: 0-100
- why: 1 short sentence explaining the score
- signals: list of 1-3 fit signals detected

Companies to score:
{companies_json}

Return ONLY a JSON array in this exact format, one entry per company:
[
  {{"name": "CompanyName", "score": 82, "why": "IT consulting firm in target geography", "signals": ["IT services", "US-based", "50+ employees"]}},
  ...
]
"""

CALL_DELAY = 2.0  # Groq rate limit buffer


def _score_candidates(
    candidates: list[dict],
    icp_profile: dict,
    min_score: int = 50,
) -> list[LeadPreviewCard]:
    """
    Score each candidate against the ICP using LLM.
    Processes in batches of 10 to stay within token limits.
    Returns scored LeadPreviewCards sorted by score descending.
    """
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    scored = []

    # Process in batches
    batch_size = 10
    for i in range(0, len(candidates), batch_size):
        batch = candidates[i:i + batch_size]

        companies_json = json.dumps(
            [{"name": c["name"], "snippet": c["snippet"]} for c in batch],
            indent=2,
        )

        prompt = SCORING_PROMPT.format(
            company_name=icp_profile.get("your_company_name", ""),
            company_description=icp_profile.get("your_company_description", ""),
            industries=", ".join(icp_profile.get("target_industries", [])[:5]),
            companies_json=companies_json,
        )

        try:
            time.sleep(CALL_DELAY)
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1200,
            )

            raw = response.choices[0].message.content.strip()

            # Extract JSON array
            match = re.search(r"\[.*\]", raw, re.DOTALL)
            if match:
                results = json.loads(match.group())
                if isinstance(results, list):
                    for result in results:
                        name = result.get("name", "")
                        score = int(result.get("score", 0))
                        why = result.get("why", "")
                        signals = result.get("signals", [])

                        # Find matching candidate
                        matched = None
                        for c in batch:
                            if c["name"].lower() == name.lower():
                                matched = c
                                break

                        if not matched:
                            # Fuzzy match by index
                            idx = results.index(result)
                            if idx < len(batch):
                                matched = batch[idx]

                        if matched and score >= min_score:
                            scored.append(LeadPreviewCard(
                                name=matched["name"],
                                url=matched["url"],
                                snippet=matched["snippet"],
                                icp_score=score,
                                why_this_lead=why,
                                fit_signals=signals if isinstance(signals, list) else [],
                                region="",
                                category="",
                            ))
        except Exception as e:
            log.error(f"[ICPDiscovery] Scoring batch failed: {e}")
            # Still include unscored candidates with score=0
            for c in batch:
                scored.append(LeadPreviewCard(
                    name=c["name"],
                    url=c["url"],
                    snippet=c["snippet"],
                    icp_score=0,
                    why_this_lead="Scoring unavailable",
                ))

    # Sort by score descending
    scored.sort(key=lambda x: x.icp_score, reverse=True)
    log.info(f"[ICPDiscovery] Scored {len(scored)} candidates, {sum(1 for s in scored if s.icp_score >= 70)} qualify")
    return scored


# ─────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────

def discover_leads_by_icp(
    icp_profile: dict,
    max_candidates: int = 30,
    min_score: int = 50,
) -> list[LeadPreviewCard]:
    """
    Full ICP-driven discovery pipeline.
    
    1. LLM generates 8 search queries from the ICP
    2. DuckDuckGo executes searches → up to 30 unique companies
    3. LLM scores each against ICP → discard <min_score
    4. Returns sorted preview cards
    
    Args:
        icp_profile: dict — CompanyICP.model_dump() output
        max_candidates: max companies to discover before scoring
        min_score: minimum ICP score to include (default 50)
    
    Returns:
        list[LeadPreviewCard] sorted by icp_score descending
    """
    log.info(f"[ICPDiscovery] Starting discovery for ICP: {icp_profile.get('profile_name', 'unnamed')}")

    # Step 1: Generate queries
    queries = _generate_search_queries(icp_profile)

    # Step 2: Search
    candidates = _execute_searches(queries, max_results=max_candidates)

    if not candidates:
        log.warning("[ICPDiscovery] No candidates found from search")
        return []

    # Step 3: Score
    scored = _score_candidates(candidates, icp_profile, min_score=min_score)

    return scored
