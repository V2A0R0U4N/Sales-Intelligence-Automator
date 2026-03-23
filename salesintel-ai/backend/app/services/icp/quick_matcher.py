"""
Quick ICP Matcher — Pre-scrape proximity scoring.
Uses search snippet + company name to estimate ICP fit BEFORE scraping.
"""
import json
import structlog
from typing import Optional
from openai import AsyncOpenAI

from app.config import get_settings
from app.services.icp.embeddings import embed_text, cosine_similarity
from app.utils.prompts import QUICK_ICP_PROXIMITY_PROMPT

logger = structlog.get_logger("icp.quick_matcher")

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


class QuickICPMatcher:
    """
    Pre-scrape ICP proximity scoring.
    Fast estimate using search snippet embedding vs ICP embedding.
    """

    async def estimate_proximity(
        self,
        company_name: str,
        description_snippet: str,
        industry_tags: list[str],
        icp_embedding: list[float],
        icp_description: str,
    ) -> dict:
        """
        Quick ICP proximity estimate using:
        1. Cosine similarity of snippet embedding vs ICP embedding
        2. Optional LLM quick check (if OpenAI key available)

        Returns: {proximity_score, reasoning, suggested_category}
        """
        # Method 1: Embedding-based quick score
        snippet_text = f"{company_name}. {description_snippet}. Industries: {', '.join(industry_tags)}"
        snippet_embedding = await embed_text(snippet_text)
        embedding_score = cosine_similarity(icp_embedding, snippet_embedding)
        embedding_score = max(0.0, min(0.7, embedding_score))  # Cap at 0.7 for pre-scrape

        # Method 2: LLM-based quick estimate (optional, for more accuracy)
        llm_result = None
        try:
            llm_result = await self._llm_quick_estimate(
                company_name, description_snippet, industry_tags, icp_description
            )
        except Exception as e:
            logger.debug("llm_quick_match_skipped", error=str(e))

        if llm_result:
            # Blend embedding score with LLM score
            llm_score = llm_result.get("proximity_score", 0.5)
            final_score = (embedding_score * 0.4) + (llm_score * 0.6)
            return {
                "proximity_score": round(min(0.7, final_score), 3),  # Never above 0.7 pre-scrape
                "reasoning": llm_result.get("reasoning", ""),
                "suggested_category": llm_result.get("suggested_category", "other"),
            }

        return {
            "proximity_score": round(embedding_score, 3),
            "reasoning": "Score based on description similarity to ICP",
            "suggested_category": "other",
        }

    async def estimate_batch(
        self,
        companies: list[dict],
        icp_embedding: list[float],
        icp_description: str,
    ) -> list[dict]:
        """
        Quick proximity estimate for a batch of companies.
        Returns list of companies with added proximity_score field.
        """
        import asyncio

        async def _estimate_one(company: dict) -> dict:
            result = await self.estimate_proximity(
                company_name=company.get("title", company.get("name", "")),
                description_snippet=company.get("snippet", ""),
                industry_tags=company.get("industry_tags", []),
                icp_embedding=icp_embedding,
                icp_description=icp_description,
            )
            return {**company, **result}

        tasks = [_estimate_one(c) for c in companies]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = []
        for r in results:
            if isinstance(r, Exception):
                logger.warning("quick_match_error", error=str(r))
                output.append({"proximity_score": 0.0, "reasoning": "Error"})
            else:
                output.append(r)

        return output

    async def _llm_quick_estimate(
        self,
        company_name: str,
        description_snippet: str,
        industry_tags: list[str],
        icp_description: str,
    ) -> dict:
        """LLM-based quick ICP proximity estimate."""
        client = _get_client()
        settings = get_settings()

        prompt = QUICK_ICP_PROXIMITY_PROMPT.format(
            icp_description=icp_description,
            company_name=company_name,
            description_snippet=description_snippet,
            industry_tags=", ".join(industry_tags) if industry_tags else "unknown",
        )

        response = await client.chat.completions.create(
            model=settings.groq_chat_model,
            messages=[
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=200,
            response_format={"type": "json_object"},
        )

        return json.loads(response.choices[0].message.content)
