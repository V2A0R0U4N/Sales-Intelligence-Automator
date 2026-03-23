"""
ICP Matcher — Full 6-step matching pipeline.

1. Company profile extraction via GPT-4o
2. Generic capability separation
3. Embedding-based cosine similarity
4. Multi-dimensional weighted scoring
5. LLM verification pass (for scores > 0.60)
6. Structured output
"""
import json
import structlog
from typing import Optional
from openai import AsyncOpenAI

from app.config import get_settings
from app.services.icp.embeddings import embed_text, cosine_similarity
from app.services.icp.scorer import ICPScorer
from app.services.icp.category_filter import CategoryFilter
from app.utils.prompts import COMPANY_PROFILE_EXTRACTION_PROMPT, ICP_VERIFICATION_PROMPT

logger = structlog.get_logger("icp.matcher")

_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncOpenAI(
            api_key=settings.groq_api_key,
            base_url="https://api.groq.com/openai/v1"
        )
    return _client


class ICPMatcher:
    """Full ICP matching pipeline."""

    def __init__(self):
        self.scorer = ICPScorer()
        self.category_filter = CategoryFilter()

    async def match_company(
        self,
        scraped_text: str,
        icp_description: str,
        icp_embedding: list[float],
        icp_industry_tags: Optional[list[str]] = None,
        icp_size_filter: Optional[str] = None,
    ) -> dict:
        """
        Run the full 6-step ICP matching pipeline for a company.

        Returns: {
            company_profile, final_score, grade, score_breakdown,
            primary_match_reason, risk_factors, recommended_pitch_angle,
            fit_confirmed, top_matching_services
        }
        """
        # Step 1: Company profile extraction via GPT-4o
        logger.info("step_1_profile_extraction")
        profile = await self._extract_profile(scraped_text)

        # Step 2: Generic capability separation
        logger.info("step_2_filter_generics")
        filtered_profile = self.category_filter.filter_profile(
            profile, icp_description
        )

        # Step 3: Embedding-based similarity
        logger.info("step_3_embed_similarity")
        primary_services_text = ", ".join(
            filtered_profile.get("primary_services", [])
        )
        industries_text = ", ".join(
            profile.get("industries_served", [])
        )

        services_embedding = await embed_text(primary_services_text)
        industries_embedding = await embed_text(industries_text)

        # Step 4: Multi-dimensional scoring
        logger.info("step_4_scoring")
        score_result = self.scorer.compute_score(
            icp_embedding=icp_embedding,
            services_embedding=services_embedding,
            industries_embedding=industries_embedding,
            company_profile=profile,
            icp_description=icp_description,
            icp_size_filter=icp_size_filter,
            icp_industry_tags=icp_industry_tags,
        )

        # Step 5: LLM verification for scores > 0.60
        verification = {
            "fit_confirmed": False,
            "fit_reasoning": "",
            "primary_match_reason": "",
            "risk_factors": [],
        }
        if score_result["final_score"] > 0.60:
            logger.info("step_5_llm_verification", score=score_result["final_score"])
            verification = await self._verify_fit(
                icp_description=icp_description,
                profile=profile,
            )

        # Step 6: Structured output
        return {
            "company_profile": profile,
            "final_score": score_result["final_score"],
            "grade": score_result["grade"],
            "score_breakdown": score_result["breakdown"],
            "top_matching_services": score_result["top_matching_services"],
            "primary_match_reason": verification.get("primary_match_reason", ""),
            "risk_factors": verification.get("risk_factors", []),
            "recommended_pitch_angle": self._generate_pitch_angle(
                profile, icp_description, verification
            ),
            "fit_confirmed": verification.get("fit_confirmed", False),
            "fit_reasoning": verification.get("fit_reasoning", ""),
        }

    async def _extract_profile(self, scraped_text: str) -> dict:
        """Step 1: Extract structured company profile via GPT-4o."""
        client = _get_client()
        settings = get_settings()

        prompt = COMPANY_PROFILE_EXTRACTION_PROMPT.format(
            content=scraped_text[:6000]
        )

        try:
            response = await client.chat.completions.create(
                model=settings.groq_chat_model,
                messages=[
                    {"role": "system", "content": "You are a business analyst. Return valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=1500,
                response_format={"type": "json_object"},
            )

            data = json.loads(response.choices[0].message.content)
            # Ensure all required fields exist
            defaults = {
                "primary_services": [],
                "secondary_services": [],
                "industries_served": [],
                "company_type": "unknown",
                "tech_stack_indicators": [],
                "company_size_signals": "",
                "geographic_presence": [],
                "generic_capabilities": [],
            }
            for key, default in defaults.items():
                if key not in data:
                    data[key] = default

            logger.info(
                "profile_extracted",
                primary_services=len(data["primary_services"]),
                industries=len(data["industries_served"]),
            )
            return data

        except Exception as e:
            logger.error("profile_extraction_failed", error=str(e))
            return {
                "primary_services": [],
                "secondary_services": [],
                "industries_served": [],
                "company_type": "unknown",
                "tech_stack_indicators": [],
                "company_size_signals": "",
                "geographic_presence": [],
                "generic_capabilities": [],
            }

    async def _verify_fit(self, icp_description: str, profile: dict) -> dict:
        """Step 5: LLM verification pass for scores > 0.60."""
        client = _get_client()
        settings = get_settings()

        prompt = ICP_VERIFICATION_PROMPT.format(
            icp_description=icp_description,
            primary_services=", ".join(profile.get("primary_services", [])),
            industries_served=", ".join(profile.get("industries_served", [])),
            company_type=profile.get("company_type", "unknown"),
            company_size=profile.get("company_size_signals", "unknown"),
            geography=", ".join(profile.get("geographic_presence", [])),
        )

        try:
            response = await client.chat.completions.create(
                model=settings.openai_chat_model,
                messages=[
                    {"role": "system", "content": "You are a sales strategy expert. Return valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=500,
                response_format={"type": "json_object"},
            )

            data = json.loads(response.choices[0].message.content)
            logger.info("fit_verified", confirmed=data.get("fit_confirmed"))
            return data

        except Exception as e:
            logger.error("verification_failed", error=str(e))
            return {
                "fit_confirmed": False,
                "fit_reasoning": "Verification failed",
                "primary_match_reason": "",
                "risk_factors": [],
            }

    def _generate_pitch_angle(
        self, profile: dict, icp_description: str, verification: dict
    ) -> str:
        """Generate a recommended pitch angle from the match data."""
        match_reason = verification.get("primary_match_reason", "")
        services = profile.get("primary_services", [])[:3]
        if match_reason:
            return f"Based on their focus on {', '.join(services)}: {match_reason}"
        return f"Explore partnership opportunities around {', '.join(services)}" if services else ""
