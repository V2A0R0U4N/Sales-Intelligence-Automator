"""
Enrichment Schemas — Deep firmographic data models.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class TechStackItem(BaseModel):
    """A detected technology in the company's stack."""
    name: str = ""
    category: str = ""             # "CRM", "Analytics", "CMS", "Marketing", etc.
    confidence: str = "medium"     # "high", "medium", "low"


class TriggerEvent(BaseModel):
    """A detected buying trigger event."""
    headline: str = ""
    event_type: str = ""           # "funding", "hiring", "expansion", "leadership", "product_launch"
    source: str = ""
    relevance: str = "medium"


class DecisionMaker(BaseModel):
    """A potential decision-maker contact."""
    name: str = "Not found"
    title: str = ""
    email_guesses: list[str] = Field(default_factory=list)
    linkedin_url: str = ""
    confidence: str = "low"


class EnrichedData(BaseModel):
    """Complete enrichment output for a single lead."""
    employee_estimate: str = "Unknown"
    revenue_estimate: str = "Unknown"
    founded_year: str = "Unknown"
    headquarters: str = "Unknown"
    tech_stack: list[TechStackItem] = Field(default_factory=list)
    trigger_events: list[TriggerEvent] = Field(default_factory=list)
    decision_makers: list[DecisionMaker] = Field(default_factory=list)
    social_links: dict = Field(default_factory=dict)  # {"linkedin": url, "twitter": url}
    enrichment_confidence: str = "low"
