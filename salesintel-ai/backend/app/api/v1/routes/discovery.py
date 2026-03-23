"""
Discovery routes — Region-based company discovery with category grouping.
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.models.icp import ICP
from app.models.company import Company
from app.services.discovery.google_search import GoogleSearchClient
from app.services.discovery.category_classifier import CategoryClassifier
from app.services.discovery.region_mapper import RegionMapper
from app.services.icp.quick_matcher import QuickICPMatcher
from app.schemas import DiscoveryRequest
from app.utils.helpers import format_response
from sqlalchemy import select

router = APIRouter()


@router.post("/search")
async def discover_companies(
    req: DiscoveryRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Discover companies by region + ICP.
    Returns companies grouped by category with pre-scrape ICP proximity scores.
    """
    # Get the ICP
    result = await db.execute(select(ICP).where(ICP.id == req.icp_id, ICP.user_id == user.id))
    icp = result.scalar_one_or_none()
    if not icp:
        raise HTTPException(status_code=404, detail="ICP not found")

    # Build search queries
    region_mapper = RegionMapper()
    queries = region_mapper.build_search_queries(
        icp_description=icp.description,
        region=req.region,
        industry_tags=icp.industry_tags or [],
    )

    # Execute searches
    google_client = GoogleSearchClient()
    all_results = []
    seen_links = set()

    for query in queries:
        results = await google_client.search_companies(
            query=query, region=req.region, max_results=15
        )
        for r in results:
            link = r.get("link", "").rstrip("/").lower()
            if link and link not in seen_links:
                seen_links.add(link)
                all_results.append(r)

    if not all_results:
        return format_response(True, {
            "region": req.region,
            "total_found": 0,
            "categories": [],
        })

    # Classify into categories
    classifier = CategoryClassifier()
    grouped = classifier.classify_batch(all_results)

    # Quick ICP proximity scoring
    quick_matcher = QuickICPMatcher()
    icp_embedding = list(icp.embedding) if icp.embedding is not None else []

    categories_output = []
    for category_key, companies in grouped.items():
        # Estimate ICP proximity for each company
        if icp_embedding:
            companies_with_scores = await quick_matcher.estimate_batch(
                companies=companies,
                icp_embedding=icp_embedding,
                icp_description=icp.description,
            )
        else:
            companies_with_scores = companies

        # Sort by proximity score descending
        companies_with_scores.sort(
            key=lambda c: c.get("proximity_score", 0), reverse=True
        )

        # Save discovered companies to DB
        saved_companies = []
        for comp in companies_with_scores:
            # Check if already exists
            existing = await db.execute(
                select(Company).where(Company.website_url == comp.get("link", ""))
            )
            existing_company = existing.scalar_one_or_none()

            if existing_company:
                saved_companies.append({
                    "id": str(existing_company.id),
                    "name": existing_company.name,
                    "website_url": existing_company.website_url,
                    "industry_category": category_key,
                    "description_snippet": comp.get("snippet", ""),
                    "icp_proximity_score": comp.get("proximity_score", 0),
                })
            else:
                new_company = Company(
                    name=comp.get("title", "Unknown"),
                    website_url=comp.get("link", ""),
                    industry_category=category_key,
                    region=req.region,
                    description_snippet=comp.get("snippet", ""),
                    source="google_search",
                )
                db.add(new_company)
                await db.flush()

                saved_companies.append({
                    "id": str(new_company.id),
                    "name": new_company.name,
                    "website_url": new_company.website_url,
                    "industry_category": category_key,
                    "description_snippet": comp.get("snippet", ""),
                    "icp_proximity_score": comp.get("proximity_score", 0),
                })

        categories_output.append({
            "category": CategoryClassifier.get_category_label(category_key),
            "category_key": category_key,
            "icon": CategoryClassifier.get_category_icon(category_key),
            "count": len(saved_companies),
            "companies": saved_companies,
        })

    await db.commit()

    # Sort categories by total proximity score
    categories_output.sort(
        key=lambda c: sum(co.get("icp_proximity_score", 0) for co in c["companies"]),
        reverse=True,
    )

    return format_response(True, {
        "region": req.region,
        "total_found": len(all_results),
        "categories": categories_output,
    })


@router.get("/categories")
async def list_categories():
    """List all available company categories."""
    return format_response(True, {
        "categories": CategoryClassifier.get_all_categories()
    })
