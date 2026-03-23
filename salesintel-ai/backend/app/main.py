"""
SalesIntel AI — FastAPI Application Entry Point.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db, close_db
from app.utils.logger import setup_logging

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    setup_logging()
    logger = logging.getLogger("salesintel")
    logger.info("Starting SalesIntel AI API...")

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    yield

    # Shutdown
    await close_db()
    logger.info("SalesIntel AI API shutdown complete")


app = FastAPI(
    title="SalesIntel AI",
    description="Agentic Sales Intelligence Platform — API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Mount Routers ---
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.companies import router as companies_router
from app.api.v1.routes.scraping import router as scraping_router
from app.api.v1.routes.icp import router as icp_router
from app.api.v1.routes.discovery import router as discovery_router
from app.api.v1.routes.leads import router as leads_router
from app.api.v1.routes.outreach import router as outreach_router

app.include_router(auth_router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(companies_router, prefix="/api/v1/companies", tags=["Companies"])
app.include_router(scraping_router, prefix="/api/v1/scraping", tags=["Scraping"])
app.include_router(icp_router, prefix="/api/v1/icp", tags=["ICP Matching"])
app.include_router(discovery_router, prefix="/api/v1/discovery", tags=["Discovery"])
app.include_router(leads_router, prefix="/api/v1/leads", tags=["Leads"])
app.include_router(outreach_router, prefix="/api/v1/outreach", tags=["Outreach"])


# --- Health Check ---
@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint."""
    return {
        "success": True,
        "data": {
            "status": "healthy",
            "service": "salesintel-ai",
            "version": "1.0.0",
            "environment": settings.environment,
        },
        "error": None,
    }
