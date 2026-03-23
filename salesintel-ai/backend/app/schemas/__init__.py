"""
Pydantic request/response schemas for all API endpoints.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr
from typing import Optional


# ─── Standard Response Envelope ───
class APIResponse(BaseModel):
    success: bool
    data: Optional[dict | list] = None
    error: Optional[str] = None
    timestamp: str


# ─── Auth ───
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    org_name: Optional[str] = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    org_name: Optional[str]
    tier: str
    created_at: datetime


# ─── ICP ───
class ICPCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=10)
    industry_tags: Optional[list[str]] = None
    size_filter: Optional[str] = None  # startup | smb | enterprise

class ICPResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    industry_tags: Optional[list[str]]
    size_filter: Optional[str]
    created_at: datetime

class ICPUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    industry_tags: Optional[list[str]] = None
    size_filter: Optional[str] = None


# ─── Company ───
class CompanyResponse(BaseModel):
    id: uuid.UUID
    name: str
    website_url: Optional[str]
    scrape_status: str
    industry_category: Optional[str]
    region: Optional[str]
    description_snippet: Optional[str]
    profile_json: Optional[dict]
    word_count: Optional[int]
    pages_scraped: Optional[int]
    created_at: datetime

class CompanyBriefResponse(BaseModel):
    """Lightweight company info for discovery results."""
    id: uuid.UUID
    name: str
    website_url: Optional[str]
    industry_category: Optional[str]
    description_snippet: Optional[str]
    icp_proximity_score: Optional[float] = None  # Pre-scrape quick match %


# ─── Discovery ───
class DiscoveryRequest(BaseModel):
    region: str = Field(min_length=1, description="Geographic region to search")
    icp_id: uuid.UUID
    max_results: int = Field(default=30, ge=5, le=100)

class CategoryGroupResponse(BaseModel):
    """Companies grouped by category from discovery."""
    category: str
    companies: list[CompanyBriefResponse]
    count: int

class DiscoveryResponse(BaseModel):
    region: str
    total_found: int
    categories: list[CategoryGroupResponse]


# ─── Scraping ───
class ScrapeRequest(BaseModel):
    company_ids: list[uuid.UUID] = Field(min_length=1)

class ScrapeStatusResponse(BaseModel):
    company_id: uuid.UUID
    company_name: str
    status: str
    strategy_used: Optional[str]
    error: Optional[str]
    word_count: Optional[int]
    duration_seconds: Optional[float]


# ─── ICP Match / Scoring ───
class ICPMatchResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    company_name: str
    final_score: float
    grade: Optional[str]
    primary_match_reason: Optional[str]
    recommended_pitch_angle: Optional[str]
    fit_confirmed: bool
    score_breakdown: Optional[dict]
    risk_factors: Optional[dict]

class ICPScoreRequest(BaseModel):
    icp_id: uuid.UUID
    company_ids: list[uuid.UUID]


# ─── Outreach ───
class OutreachGenerateRequest(BaseModel):
    icp_match_id: uuid.UUID

class EmailVariation(BaseModel):
    tone: str  # formal | casual | challenger
    subject: str
    body: str
    estimated_read_time_seconds: Optional[int] = None

class ObjectionCounter(BaseModel):
    objection: str
    counter: str
    category: str  # price | timing | trust | need | competitor

class OutreachResponse(BaseModel):
    company_name: str
    emails: list[EmailVariation]
    linkedin_dm: Optional[str]
    pitch_script: Optional[str]
    objections: list[ObjectionCounter]
    discovery_questions: Optional[list[str]]


# ─── Leads ───
class LeadResponse(BaseModel):
    id: uuid.UUID
    company_name: str
    priority: str
    final_score: float
    grade: Optional[str]
    next_action: Optional[str]
    hubspot_synced: bool = False
