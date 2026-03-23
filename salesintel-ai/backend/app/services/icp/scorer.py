"""
ICP Scorer — Multi-dimensional weighted scoring formula.
"""
import structlog
from typing import Optional

from app.services.icp.embeddings import cosine_similarity
from app.services.icp.category_filter import CategoryFilter

logger = structlog.get_logger("icp.scorer")


class ICPScorer:
    """
    Multi-dimensional ICP scoring.

    Formula:
    final_score = (
        primary_service_cosine_similarity * 0.50 +
        industry_match_score * 0.25 +
        company_size_match * 0.10 +
        geography_match * 0.05 +
        tech_stack_overlap * 0.10
    )

    Each dimension is scored 0.0 to 1.0.
    """

    WEIGHTS = {
        "primary_services": 0.50,
        "industry_match": 0.25,
        "company_size": 0.10,
        "geography": 0.05,
        "tech_stack": 0.10,
    }

    def __init__(self):
        self.category_filter = CategoryFilter()

    def compute_score(
        self,
        icp_embedding: list[float],
        services_embedding: list[float],
        industries_embedding: list[float],
        company_profile: dict,
        icp_description: str,
        icp_size_filter: Optional[str] = None,
        icp_industry_tags: Optional[list[str]] = None,
    ) -> dict:
        """
        Compute the multi-dimensional ICP score.

        Returns:
        {
            final_score: float (0.0-1.0),
            grade: str (A/B/C),
            breakdown: {dimension: score},
            top_matching_services: list[str]
        }
        """
        # Filter generic capabilities
        filtered_profile = self.category_filter.filter_profile(
            company_profile, icp_description
        )

        # Dimension 1: Primary services cosine similarity (50%)
        primary_score = cosine_similarity(icp_embedding, services_embedding)
        primary_score = max(0.0, min(1.0, primary_score))

        # Dimension 2: Industry match (25%)
        industry_score = cosine_similarity(icp_embedding, industries_embedding)
        industry_score = max(0.0, min(1.0, industry_score))

        # Boost if industry tags explicitly match
        if icp_industry_tags and company_profile.get("industries_served"):
            tag_overlap = self._tag_overlap(
                icp_industry_tags,
                company_profile["industries_served"],
            )
            industry_score = min(1.0, industry_score + tag_overlap * 0.2)

        # Dimension 3: Company size match (10%)
        size_score = self._compute_size_match(
            company_profile.get("company_size_signals", ""),
            icp_size_filter,
        )

        # Dimension 4: Geography match (5%)
        geo_score = self._compute_geo_match(
            company_profile.get("geographic_presence", []),
            icp_description,
        )

        # Dimension 5: Tech stack overlap (10%)
        tech_score = self._compute_tech_overlap(
            company_profile.get("tech_stack_indicators", []),
            icp_description,
        )

        # Weighted final score
        final_score = (
            primary_score * self.WEIGHTS["primary_services"]
            + industry_score * self.WEIGHTS["industry_match"]
            + size_score * self.WEIGHTS["company_size"]
            + geo_score * self.WEIGHTS["geography"]
            + tech_score * self.WEIGHTS["tech_stack"]
        )
        final_score = round(max(0.0, min(1.0, final_score)), 4)

        # Grade assignment
        if final_score > 0.8:
            grade = "A"
        elif final_score > 0.6:
            grade = "B"
        elif final_score > 0.4:
            grade = "C"
        else:
            grade = "D"

        # Top matching services (from filtered list)
        top_services = filtered_profile.get("primary_services", [])[:5]

        breakdown = {
            "primary_services_score": round(primary_score, 4),
            "industry_match_score": round(industry_score, 4),
            "company_size_score": round(size_score, 4),
            "geography_score": round(geo_score, 4),
            "tech_stack_score": round(tech_score, 4),
            "weights": self.WEIGHTS,
        }

        logger.info(
            "icp_score_computed",
            final_score=final_score,
            grade=grade,
            primary=round(primary_score, 3),
            industry=round(industry_score, 3),
        )

        return {
            "final_score": final_score,
            "grade": grade,
            "breakdown": breakdown,
            "top_matching_services": top_services,
        }

    def _compute_size_match(self, size_signals: str, icp_size: Optional[str]) -> float:
        """Score company size match against ICP size filter."""
        if not icp_size:
            return 0.5  # No preference = neutral

        size_lower = size_signals.lower() if size_signals else ""
        icp_size_lower = icp_size.lower()

        size_indicators = {
            "startup": ["startup", "small team", "founding", "seed", "pre-seed", "1-50", "< 50"],
            "smb": ["mid-size", "midsize", "100-", "200-", "50-500", "growing", "established"],
            "enterprise": ["enterprise", "1000+", "global", "multinational", "fortune", "5000+", "10000+"],
        }

        target_keywords = size_indicators.get(icp_size_lower, [])
        if not target_keywords:
            return 0.5

        matches = sum(1 for kw in target_keywords if kw in size_lower)
        return min(1.0, matches * 0.3) if matches else 0.2

    def _compute_geo_match(self, geo_presence: list[str], icp_description: str) -> float:
        """Score geographic alignment."""
        if not geo_presence:
            return 0.3

        icp_lower = icp_description.lower()
        matched = sum(
            1 for geo in geo_presence
            if geo.lower() in icp_lower
        )
        return min(1.0, matched * 0.4) if matched else 0.2

    def _compute_tech_overlap(self, tech_stack: list[str], icp_description: str) -> float:
        """Score tech stack alignment."""
        if not tech_stack:
            return 0.3

        icp_lower = icp_description.lower()
        matched = sum(
            1 for tech in tech_stack
            if tech.lower() in icp_lower
        )
        return min(1.0, matched * 0.25) if matched else 0.2

    def _tag_overlap(self, tags_a: list[str], tags_b: list[str]) -> float:
        """Compute normalized tag overlap."""
        set_a = {t.lower().strip() for t in tags_a}
        set_b = {t.lower().strip() for t in tags_b}
        if not set_a or not set_b:
            return 0.0
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union)
