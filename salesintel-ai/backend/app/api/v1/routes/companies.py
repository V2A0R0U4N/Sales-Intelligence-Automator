"""
Company routes — CRUD and search.
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.models.company import Company
from app.utils.helpers import format_response

router = APIRouter()


@router.get("")
async def list_companies(
    region: str = Query(None),
    category: str = Query(None),
    scrape_status: str = Query(None),
    search: str = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List companies with optional filters."""
    query = select(Company)

    if region:
        query = query.where(Company.region.ilike(f"%{region}%"))
    if category:
        query = query.where(Company.industry_category == category)
    if scrape_status:
        query = query.where(Company.scrape_status == scrape_status)
    if search:
        query = query.where(
            or_(
                Company.name.ilike(f"%{search}%"),
                Company.description_snippet.ilike(f"%{search}%"),
            )
        )

    query = query.order_by(Company.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    companies = result.scalars().all()

    return format_response(True, [
        {
            "id": str(c.id),
            "name": c.name,
            "website_url": c.website_url,
            "scrape_status": c.scrape_status,
            "industry_category": c.industry_category,
            "region": c.region,
            "description_snippet": c.description_snippet,
            "word_count": c.word_count,
            "pages_scraped": c.pages_scraped,
            "created_at": c.created_at.isoformat(),
        }
        for c in companies
    ])


@router.get("/{company_id}")
async def get_company(
    company_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get full company details including profile."""
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    return format_response(True, {
        "id": str(company.id),
        "name": company.name,
        "website_url": company.website_url,
        "scrape_status": company.scrape_status,
        "scrape_strategy_used": company.scrape_strategy_used,
        "scrape_error": company.scrape_error,
        "industry_category": company.industry_category,
        "region": company.region,
        "description_snippet": company.description_snippet,
        "profile": company.profile_json,
        "word_count": company.word_count,
        "pages_scraped": company.pages_scraped,
        "created_at": company.created_at.isoformat(),
        "updated_at": company.updated_at.isoformat() if company.updated_at else None,
    })


@router.post("/manual")
async def add_company_manually(
    name: str,
    website_url: str,
    region: str = None,
    category: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Add a company manually."""
    company = Company(
        name=name,
        website_url=website_url,
        region=region,
        industry_category=category,
        source="manual",
    )
    db.add(company)
    await db.commit()
    await db.refresh(company)

    return format_response(True, {
        "id": str(company.id),
        "name": company.name,
        "website_url": company.website_url,
    })
