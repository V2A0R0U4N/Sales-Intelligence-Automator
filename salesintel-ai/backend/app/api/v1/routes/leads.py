"""
Lead management routes.
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.models.lead import Lead, ICPMatch
from app.models.company import Company
from app.utils.helpers import format_response

router = APIRouter()


@router.get("")
async def list_leads(
    priority: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all leads, optionally filtered by priority."""
    query = select(Lead)
    if priority:
        query = query.where(Lead.priority == priority.upper())

    result = await db.execute(query.order_by(Lead.created_at.desc()))
    leads = result.scalars().all()

    output = []
    for lead in leads:
        # Get match and company details
        match_result = await db.execute(select(ICPMatch).where(ICPMatch.id == lead.icp_match_id))
        match = match_result.scalar_one_or_none()

        company_name = "Unknown"
        if match:
            comp_result = await db.execute(select(Company).where(Company.id == match.company_id))
            company = comp_result.scalar_one_or_none()
            company_name = company.name if company else "Unknown"

        output.append({
            "id": str(lead.id),
            "company_name": company_name,
            "priority": lead.priority,
            "final_score": match.final_score if match else 0,
            "grade": match.grade if match else None,
            "next_action": lead.next_action,
            "hubspot_synced": bool(lead.hubspot_contact_id),
        })

    return format_response(True, output)
