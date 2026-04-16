"""
ICP Profile Models — User-Definable Ideal Customer Profile
==========================================================
Replaces the hardcoded Moksh Group ICP with a flexible, user-configurable
profile system.  Stored as documents in MongoDB 'icp_profiles' collection.

Each profile defines:
  - Who YOU are (company, verticals, services)
  - Who you're TARGETING (industries, geo, size)
  - Qualification SIGNALS (pain points, tech stack, triggers)
  - DISQUALIFICATION criteria (exclusions)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class VerticalDefinition(BaseModel):
    """
    A single business vertical / service line the user offers.
    
    Example for Moksh Group:
        name="MokshTech"
        description="IT Managed Services for SMBs"
        target_customers="Small businesses needing outsourced IT"
        services=["Help Desk", "Network Monitoring", "Cloud Migration"]
        match_signals=["uses ConnectWise", "outsources IT", "50-200 employees"]
    """
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="")
    target_customers: str = Field(default="")
    services: list[str] = Field(default_factory=list)
    match_signals: list[str] = Field(default_factory=list)


class CompanyICP(BaseModel):
    """
    Complete user-defined Ideal Customer Profile.
    
    Replaces the hardcoded MOKSH_ICP_CONTEXT in llm_analyzer.py.
    One user can have multiple saved ICPs (e.g. for different markets).
    """
    # Identity
    profile_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    profile_name: str = Field(default="My ICP", min_length=1, max_length=200)

    # Your company info
    your_company_name: str = Field(default="", max_length=200)
    your_company_description: str = Field(default="", max_length=2000)
    verticals: list[VerticalDefinition] = Field(default_factory=list)

    # Target lead filters
    target_industries: list[str] = Field(default_factory=list)
    target_geographies: list[str] = Field(default_factory=list)
    employee_count_min: Optional[int] = None
    employee_count_max: Optional[int] = None

    # Qualification signals
    pain_point_keywords: list[str] = Field(default_factory=list)
    tech_stack_signals: list[str] = Field(default_factory=list)
    trigger_events: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)

    # Disqualification
    excluded_keywords: list[str] = Field(default_factory=list)

    # Timestamps
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_mongo(self) -> dict:
        """Convert to a MongoDB-safe dict."""
        return self.model_dump()

    @classmethod
    def from_mongo(cls, doc: dict) -> "CompanyICP":
        """Create from a MongoDB document."""
        if doc and "_id" in doc:
            doc.pop("_id", None)
        return cls(**doc)


# ─────────────────────────────────────────────────────────────
# Default Moksh Group preset — backward compatibility
# ─────────────────────────────────────────────────────────────

MOKSH_DEFAULT_ICP = CompanyICP(
    profile_id="moksh-default",
    profile_name="Moksh Group — Default ICP",
    your_company_name="Moksh Group",
    your_company_description=(
        "Moksh Group is a multi-vertical B2B services company offering "
        "IT managed services (MokshTech), CAD & BIM outsourcing (MokshCAD), "
        "digital marketing (MokshDigital), and commercial signage (MokshSigns)."
    ),
    verticals=[
        VerticalDefinition(
            name="MokshTech",
            description="IT Managed Services — Help desk, NOC, SOC, cloud migration, endpoint management",
            target_customers="US/Canada SMBs (50-500 employees) needing outsourced or augmented IT",
            services=["Managed IT", "Help Desk", "NOC/SOC", "Cloud Migration", "Endpoint Management"],
            match_signals=["uses ConnectWise", "uses Datto", "outsources IT", "MSP client"],
        ),
        VerticalDefinition(
            name="MokshCAD",
            description="CAD & BIM Outsourcing — Architectural drafting, MEP modeling, Revit, AutoCAD",
            target_customers="US architecture/engineering firms, MEP contractors, construction companies",
            services=["Architectural Drafting", "MEP Modeling", "Revit", "AutoCAD", "BIM Services"],
            match_signals=["uses Revit", "uses AutoCAD", "needs drafting staff", "BIM requirement"],
        ),
        VerticalDefinition(
            name="MokshDigital",
            description="Digital Marketing — SEO, PPC, social media, web development for SMBs",
            target_customers="Small businesses needing online presence and lead generation",
            services=["SEO", "PPC/Google Ads", "Social Media", "Web Development", "Content Marketing"],
            match_signals=["needs more leads", "poor online presence", "no SEO", "outdated website"],
        ),
        VerticalDefinition(
            name="MokshSigns",
            description="Commercial Signage — Indoor/outdoor signs, vehicle wraps, trade show displays",
            target_customers="Retail stores, restaurants, offices needing physical branding",
            services=["Indoor Signs", "Outdoor Signs", "Vehicle Wraps", "Trade Show Displays", "Neon Signs"],
            match_signals=["physical retail", "new location", "rebranding", "trade show exhibitor"],
        ),
    ],
    target_industries=[
        "IT Services", "MSP", "Architecture", "Engineering", "Construction",
        "Retail", "Restaurant", "Real Estate", "Healthcare", "Manufacturing",
    ],
    target_geographies=["United States", "Canada", "Gujarat"],
    pain_point_keywords=[
        "struggling with IT", "need CAD outsourcing", "no online presence",
        "need signage", "scaling challenges", "manual processes",
    ],
    tech_stack_signals=["ConnectWise", "Datto", "Revit", "AutoCAD", "WordPress"],
    trigger_events=["recently funded", "new office", "hiring", "expansion"],
    competitors=["Accenture", "Infosys", "local MSPs"],
    excluded_keywords=["government", "B2C only"],
)
