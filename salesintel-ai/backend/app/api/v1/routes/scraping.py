"""
Scraping routes — Trigger scraping jobs and track status.
"""
import uuid
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.models.company import Company
from app.models.scrape_job import ScrapeJob
from app.services.scraping.scraper import ScraperOrchestrator
from app.schemas import ScrapeRequest
from app.utils.helpers import format_response

router = APIRouter()


@router.post("/batch")
async def scrape_companies(
    req: ScrapeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Trigger batch scraping for selected companies.
    Runs asynchronously — returns job IDs immediately.
    """
    job_ids = []
    companies_to_scrape = []

    for company_id in req.company_ids:
        result = await db.execute(select(Company).where(Company.id == company_id))
        company = result.scalar_one_or_none()

        if not company:
            continue

        if company.scrape_status == "completed" and company.scraped_text:
            # Already scraped — skip
            job_ids.append({
                "company_id": str(company.id),
                "company_name": company.name,
                "status": "already_scraped",
            })
            continue

        # Create scrape job
        job = ScrapeJob(company_id=company.id, status="pending")
        db.add(job)
        company.scrape_status = "in_progress"
        await db.flush()

        job_ids.append({
            "company_id": str(company.id),
            "company_name": company.name,
            "job_id": str(job.id),
            "status": "queued",
        })
        companies_to_scrape.append({
            "company_id": company.id,
            "job_id": job.id,
            "url": company.website_url,
            "name": company.name,
        })

    await db.commit()

    # Start async scraping in background
    if companies_to_scrape:
        asyncio.create_task(
            _run_scraping_batch(companies_to_scrape)
        )

    return format_response(True, {
        "message": f"Scraping started for {len(companies_to_scrape)} companies",
        "jobs": job_ids,
    })


async def _run_scraping_batch(companies: list[dict]):
    """Background task to run scraping for a batch of companies."""
    from app.database import async_session_factory

    orchestrator = ScraperOrchestrator()
    semaphore = asyncio.Semaphore(5)

    async def scrape_one(comp: dict):
        async with semaphore:
            result = await orchestrator.scrape_company(
                url=comp["url"],
                company_name=comp["name"],
            )

            # Save results to DB
            async with async_session_factory() as db:
                # Update company
                company_result = await db.execute(
                    select(Company).where(Company.id == comp["company_id"])
                )
                company = company_result.scalar_one_or_none()
                if company:
                    company.scrape_status = "completed" if result.success else "failed"
                    company.scraped_text = result.combined_text if result.success else None
                    company.scrape_strategy_used = result.strategy_used
                    company.scrape_error = result.error
                    company.word_count = result.word_count
                    company.pages_scraped = result.pages_scraped

                # Update scrape job
                job_result = await db.execute(
                    select(ScrapeJob).where(ScrapeJob.id == comp["job_id"])
                )
                job = job_result.scalar_one_or_none()
                if job:
                    job.status = "completed" if result.success else "failed"
                    job.strategy_log_json = result.strategy_log
                    job.duration_seconds = result.duration_seconds

                await db.commit()

    tasks = [scrape_one(c) for c in companies]
    await asyncio.gather(*tasks, return_exceptions=True)


@router.get("/status/{company_id}")
async def get_scrape_status(
    company_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get scraping status for a company."""
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Get latest scrape job
    job_result = await db.execute(
        select(ScrapeJob)
        .where(ScrapeJob.company_id == company_id)
        .order_by(ScrapeJob.created_at.desc())
        .limit(1)
    )
    job = job_result.scalar_one_or_none()

    return format_response(True, {
        "company_id": str(company.id),
        "company_name": company.name,
        "scrape_status": company.scrape_status,
        "strategy_used": company.scrape_strategy_used,
        "error": company.scrape_error,
        "word_count": company.word_count,
        "pages_scraped": company.pages_scraped,
        "job": {
            "id": str(job.id) if job else None,
            "status": job.status if job else None,
            "duration_seconds": job.duration_seconds if job else None,
            "strategy_log": job.strategy_log_json if job else None,
        } if job else None,
    })


@router.get("/batch-status")
async def get_batch_status(
    company_ids: str,  # comma-separated UUIDs
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get scraping status for multiple companies at once."""
    ids = [uuid.UUID(cid.strip()) for cid in company_ids.split(",") if cid.strip()]
    results = []

    for cid in ids:
        result = await db.execute(select(Company).where(Company.id == cid))
        company = result.scalar_one_or_none()
        if company:
            results.append({
                "company_id": str(company.id),
                "company_name": company.name,
                "scrape_status": company.scrape_status,
                "word_count": company.word_count,
            })

    return format_response(True, results)
