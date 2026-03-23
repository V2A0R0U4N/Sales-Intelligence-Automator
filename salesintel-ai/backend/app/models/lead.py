"""
Lead and ICP Match ORM models.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, Float, Boolean, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ICPMatch(Base):
    __tablename__ = "icp_matches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()")
    )
    icp_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("icps.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    final_score: Mapped[float] = mapped_column(Float, default=0.0)
    score_breakdown_json: Mapped[dict] = mapped_column(JSONB, nullable=True)
    grade: Mapped[str] = mapped_column(String(2), nullable=True)  # A, B, C
    pitch_materials_json: Mapped[dict] = mapped_column(JSONB, nullable=True)
    email_sequences_json: Mapped[dict] = mapped_column(JSONB, nullable=True)
    fit_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    fit_reasoning: Mapped[str] = mapped_column(Text, nullable=True)
    primary_match_reason: Mapped[str] = mapped_column(Text, nullable=True)
    risk_factors: Mapped[dict] = mapped_column(JSONB, nullable=True)
    recommended_pitch_angle: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    icp = relationship("ICP", back_populates="matches")
    company = relationship("Company", back_populates="icp_matches")
    leads = relationship("Lead", back_populates="icp_match", lazy="selectin")


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()")
    )
    icp_match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("icp_matches.id", ondelete="CASCADE"), nullable=False
    )
    priority: Mapped[str] = mapped_column(String(10), default="COLD")  # HOT | WARM | COLD
    hubspot_contact_id: Mapped[str] = mapped_column(String(255), nullable=True)
    engagement_score: Mapped[float] = mapped_column(Float, default=0.0)
    last_action: Mapped[str] = mapped_column(String(255), nullable=True)
    next_action: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    icp_match = relationship("ICPMatch", back_populates="leads")
    email_events = relationship("EmailEvent", back_populates="lead", lazy="selectin")


class EmailEvent(Base):
    __tablename__ = "email_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()")
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)  # sent | opened | clicked | replied
    email_variation: Mapped[str] = mapped_column(String(50), nullable=True)  # formal | casual | challenger
    sendgrid_message_id: Mapped[str] = mapped_column(String(255), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    lead = relationship("Lead", back_populates="email_events")
