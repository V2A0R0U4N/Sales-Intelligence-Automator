"""
ORM model registry — import all models so Alembic and Base.metadata can see them.
"""
from app.database import Base  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.company import Company  # noqa: F401
from app.models.icp import ICP  # noqa: F401
from app.models.lead import ICPMatch, Lead, EmailEvent  # noqa: F401
from app.models.scrape_job import ScrapeJob  # noqa: F401
