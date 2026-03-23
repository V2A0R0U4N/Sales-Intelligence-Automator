"""
ICP routes — Create, read, update ICPs and trigger matching.
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.models.icp import ICP
from app.models.company import Company
from app.models.lead import ICPMatch
from app.services.icp.embeddings import embed_text
from app.services.icp.matcher import ICPMatcher
from app.schemas import ICPCreateRequest, ICPUpdateRequest, ICPScoreRequest
from app.utils.helpers import format_response

router = APIRouter()


@router.post("")
async def create_icp(
    req: ICPCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new ICP with embedding."""
    # Generate embedding
    embedding = await embed_text(req.description)

    icp = ICP(
        user_id=user.id,
        name=req.name,
        description=req.description,
        embedding=embedding,
        industry_tags=req.industry_tags,
        size_filter=req.size_filter,
    )
    db.add(icp)
    await db.commit()
    await db.refresh(icp)

    return format_response(True, {
        "id": str(icp.id),
        "name": icp.name,
        "description": icp.description,
        "industry_tags": icp.industry_tags,
        "size_filter": icp.size_filter,
    })


@router.get("")
async def list_icps(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all ICPs for the current user."""
    result = await db.execute(select(ICP).where(ICP.user_id == user.id))
    icps = result.scalars().all()

    return format_response(True, [
        {
            "id": str(icp.id),
            "name": icp.name,
            "description": icp.description,
            "industry_tags": icp.industry_tags,
            "size_filter": icp.size_filter,
            "created_at": icp.created_at.isoformat(),
        }
        for icp in icps
    ])


@router.get("/{icp_id}")
async def get_icp(
    icp_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a single ICP."""
    result = await db.execute(select(ICP).where(ICP.id == icp_id, ICP.user_id == user.id))
    icp = result.scalar_one_or_none()
    if not icp:
        raise HTTPException(status_code=404, detail="ICP not found")

    return format_response(True, {
        "id": str(icp.id),
        "name": icp.name,
        "description": icp.description,
        "industry_tags": icp.industry_tags,
        "size_filter": icp.size_filter,
        "created_at": icp.created_at.isoformat(),
    })


@router.post("/{icp_id}/match")
async def trigger_matching(
    icp_id: uuid.UUID,
    req: ICPScoreRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Trigger full ICP matching for selected companies.
    Companies must be already scraped.
    """
    # Get ICP
    result = await db.execute(select(ICP).where(ICP.id == icp_id, ICP.user_id == user.id))
    icp = result.scalar_one_or_none()
    if not icp:
        raise HTTPException(status_code=404, detail="ICP not found")

    icp_embedding = list(icp.embedding) if icp.embedding is not None else []
    matcher = ICPMatcher()
    match_results = []

    for company_id in req.company_ids:
        # Get company with scraped data
        comp_result = await db.execute(select(Company).where(Company.id == company_id))
        company = comp_result.scalar_one_or_none()

        if not company or company.scrape_status != "completed" or not company.scraped_text:
            match_results.append({
                "company_id": str(company_id),
                "company_name": company.name if company else "Unknown",
                "error": "Company not scraped yet",
            })
            continue

        # Run full matching pipeline
        try:
            result = await matcher.match_company(
                scraped_text=company.scraped_text,
                icp_description=icp.description,
                icp_embedding=icp_embedding,
                icp_industry_tags=icp.industry_tags,
                icp_size_filter=icp.size_filter,
            )

            # Save match to DB
            icp_match = ICPMatch(
                icp_id=icp.id,
                company_id=company.id,
                final_score=result["final_score"],
                score_breakdown_json=result["score_breakdown"],
                grade=result["grade"],
                fit_confirmed=result["fit_confirmed"],
                fit_reasoning=result["fit_reasoning"],
                primary_match_reason=result["primary_match_reason"],
                risk_factors={"factors": result["risk_factors"]},
                recommended_pitch_angle=result["recommended_pitch_angle"],
            )
            db.add(icp_match)

            # Update company profile
            company.profile_json = result["company_profile"]
            await db.flush()

            match_results.append({
                "company_id": str(company.id),
                "company_name": company.name,
                "final_score": result["final_score"],
                "grade": result["grade"],
                "primary_match_reason": result["primary_match_reason"],
                "fit_confirmed": result["fit_confirmed"],
                "top_matching_services": result["top_matching_services"],
            })

        except Exception as e:
            match_results.append({
                "company_id": str(company_id),
                "company_name": company.name,
                "error": str(e),
            })

    await db.commit()

    # Sort by score
    match_results.sort(key=lambda x: x.get("final_score", 0), reverse=True)

    return format_response(True, {
        "icp_id": str(icp.id),
        "matches": match_results,
    })


@router.get("/{icp_id}/matches")
async def get_matches(
    icp_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get all ICP match results for an ICP."""
    result = await db.execute(
        select(ICPMatch).where(ICPMatch.icp_id == icp_id)
    )
    matches = result.scalars().all()

    output = []
    for match in matches:
        # Get company name
        comp = await db.execute(select(Company).where(Company.id == match.company_id))
        company = comp.scalar_one_or_none()

        output.append({
            "id": str(match.id),
            "company_id": str(match.company_id),
            "company_name": company.name if company else "Unknown",
            "final_score": match.final_score,
            "grade": match.grade,
            "primary_match_reason": match.primary_match_reason,
            "recommended_pitch_angle": match.recommended_pitch_angle,
            "fit_confirmed": match.fit_confirmed,
            "score_breakdown": match.score_breakdown_json,
        })

    output.sort(key=lambda x: x["final_score"], reverse=True)
    return format_response(True, output)
