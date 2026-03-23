"""
Company ORM model.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, Integer, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    website_url: Mapped[str] = mapped_column(String(2048), nullable=True)
    scraped_text: Mapped[str] = mapped_column(Text, nullable=True)
    scrape_status: Mapped[str] = mapped_column(
        String(50), default="pending"
    )  # pending | in_progress | completed | failed | manual_required
    scrape_strategy_used: Mapped[str] = mapped_column(String(100), nullable=True)
    scrape_error: Mapped[str] = mapped_column(Text, nullable=True)
    profile_json: Mapped[dict] = mapped_column(JSONB, nullable=True)
    industry_category: Mapped[str] = mapped_column(String(100), nullable=True, index=True)
    region: Mapped[str] = mapped_column(String(255), nullable=True, index=True)
    description_snippet: Mapped[str] = mapped_column(Text, nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, nullable=True)
    pages_scraped: Mapped[int] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(100), nullable=True)  # google_search | apollo | manual
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    scrape_jobs = relationship("ScrapeJob", back_populates="company", lazy="selectin")
    icp_matches = relationship("ICPMatch", back_populates="company", lazy="selectin")
