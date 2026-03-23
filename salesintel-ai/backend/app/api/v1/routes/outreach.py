"""
Outreach routes — Generate emails, pitches, and objection handlers.
"""
import json
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from openai import AsyncOpenAI

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.models.lead import ICPMatch
from app.models.company import Company
from app.models.icp import ICP
from app.config import get_settings
from app.utils.prompts import (
    COLD_EMAIL_PROMPT,
    OBJECTION_HANDLER_PROMPT,
    PITCH_SCRIPT_PROMPT,
    LINKEDIN_DM_PROMPT,
    DISCOVERY_QUESTIONS_PROMPT,
    EMAIL_SEQUENCE_PROMPT,
)
from app.utils.helpers import format_response

router = APIRouter()


async def _llm_generate(prompt: str) -> dict:
    """Call Groq (via OpenAI SDK) for outreach generation."""
    settings = get_settings()
    client = AsyncOpenAI(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1"
    )

    response = await client.chat.completions.create(
        model=settings.groq_chat_model,
        messages=[
            {"role": "system", "content": "You are a sales copywriter. Return valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=3000,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


@router.post("/generate/{match_id}")
async def generate_outreach(
    match_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate full outreach materials for an ICP match."""
    # Get match + company + ICP
    match_result = await db.execute(select(ICPMatch).where(ICPMatch.id == match_id))
    match = match_result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="ICP match not found")

    comp_result = await db.execute(select(Company).where(Company.id == match.company_id))
    company = comp_result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    icp_result = await db.execute(select(ICP).where(ICP.id == match.icp_id))
    icp = icp_result.scalar_one_or_none()

    profile = company.profile_json or {}
    profile_json = json.dumps(profile, indent=2)

    # Generate all materials in parallel
    import asyncio

    emails_task = _llm_generate(COLD_EMAIL_PROMPT.format(
        company_name=company.name,
        company_profile_json=profile_json,
        icp_description=icp.description if icp else "",
        primary_match_reason=match.primary_match_reason or "",
        recommended_pitch_angle=match.recommended_pitch_angle or "",
    ))

    objections_task = _llm_generate(OBJECTION_HANDLER_PROMPT.format(
        company_name=company.name,
        company_type=profile.get("company_type", "unknown"),
        primary_services=", ".join(profile.get("primary_services", [])),
        industries_served=", ".join(profile.get("industries_served", [])),
        icp_description=icp.description if icp else "",
    ))

    pitch_task = _llm_generate(PITCH_SCRIPT_PROMPT.format(
        company_name=company.name,
        company_profile_json=profile_json,
        icp_description=icp.description if icp else "",
        primary_match_reason=match.primary_match_reason or "",
    ))

    linkedin_task = _llm_generate(LINKEDIN_DM_PROMPT.format(
        company_name=company.name,
        primary_services=", ".join(profile.get("primary_services", [])),
        primary_match_reason=match.primary_match_reason or "",
    ))

    questions_task = _llm_generate(DISCOVERY_QUESTIONS_PROMPT.format(
        company_name=company.name,
        primary_services=", ".join(profile.get("primary_services", [])),
        industries_served=", ".join(profile.get("industries_served", [])),
        primary_match_reason=match.primary_match_reason or "",
    ))

    results = await asyncio.gather(
        emails_task, objections_task, pitch_task, linkedin_task, questions_task,
        return_exceptions=True,
    )

    emails = results[0] if not isinstance(results[0], Exception) else []
    objections = results[1] if not isinstance(results[1], Exception) else []
    pitch = results[2] if not isinstance(results[2], Exception) else {}
    linkedin = results[3] if not isinstance(results[3], Exception) else {}
    questions = results[4] if not isinstance(results[4], Exception) else {}

    # Save to match record
    pitch_materials = {
        "emails": emails if isinstance(emails, list) else [emails],
        "objections": objections if isinstance(objections, list) else objections.get("objections", []) if isinstance(objections, dict) else [],
        "pitch_script": pitch,
        "linkedin_dm": linkedin.get("message", "") if isinstance(linkedin, dict) else "",
        "discovery_questions": questions.get("questions", []) if isinstance(questions, dict) else [],
    }
    match.pitch_materials_json = pitch_materials
    await db.commit()

    return format_response(True, {
        "company_name": company.name,
        "match_id": str(match.id),
        "materials": pitch_materials,
    })


@router.get("/materials/{match_id}")
async def get_outreach_materials(
    match_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get previously generated outreach materials."""
    match_result = await db.execute(select(ICPMatch).where(ICPMatch.id == match_id))
    match = match_result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    if not match.pitch_materials_json:
        raise HTTPException(status_code=404, detail="No outreach materials generated yet")

    comp_result = await db.execute(select(Company).where(Company.id == match.company_id))
    company = comp_result.scalar_one_or_none()

    return format_response(True, {
        "company_name": company.name if company else "Unknown",
        "match_id": str(match.id),
        "materials": match.pitch_materials_json,
    })
