"""
LLM Analyzer — Uses Groq + LLaMA 3.1 8B Instant for all AI analysis.
Generates sales briefs, ICP matching, market context, outreach emails,
and objection preparation from cleaned website content.
"""
from __future__ import annotations

import os
import json
import asyncio
from groq import Groq
from dotenv import load_dotenv
from models.schemas import (
    SalesBrief, ICPMatch, MarketContext,
    OutreachEmail, ObjectionPrep, Objection,
)

load_dotenv()

# Initialize Groq client
_client: Groq = None
MODEL = "llama-3.3-70b-versatile"

# Rate limit: insert small delay between calls
CALL_DELAY = 2.0  # seconds between LLM calls


def _get_client() -> Groq:
    """Get or initialize the Groq client."""
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key or api_key == "your_groq_api_key_here":
            raise ValueError(
                "GROQ_API_KEY not set. Get a free key at https://console.groq.com"
            )
        _client = Groq(api_key=api_key)
    return _client


def _call_llm(system_prompt: str, user_prompt: str, model: str = MODEL, retries: int = 2) -> str:
    """Make a synchronous LLM call with retry logic."""
    client = _get_client()

    for attempt in range(retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=2000,
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content
        except Exception as e:
            if attempt < retries:
                print(f"[LLM] Retry {attempt + 1} after error: {e}")
                import time
                time.sleep(3)
            else:
                raise


async def _async_call(system_prompt: str, user_prompt: str, model: str = MODEL) -> str:
    """Async wrapper around sync LLM call."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _call_llm, system_prompt, user_prompt, model)


# ====================================================================
# MOKSH ICP PROFILE — Used across all ICP matching prompts
# ====================================================================

MOKSH_ICP_CONTEXT = """
Moksh Group operates 4 business verticals. Score the lead against EACH vertical:

1. MokshTech (mokshtech.net) — MSP Outsourcing & IT Services
   Target Customers: MSPs (Managed Service Providers), IT companies, tech firms
   Services: 24/7 NOC monitoring, Service Desk, Dedicated Engineers (Tier 1-3),
   Software Development (.NET, PHP, Mobile), IT Project management, Administrative services
   Match signals: uses RMM/PSA tools, manages IT infrastructure, needs NOC/helpdesk

2. MokshCAD (mokshcad.com) — CAD Drafting & Estimation Services
   Target Customers: Construction firms, fabricators, countertop companies, architects, millwork companies
   Services: CAD 2D/3D drafting, CNC Programming, Estimation & Take Offs,
   Cabinetry/Millwork Estimation, MEP-BIM Modeling, Data Processing
   Match signals: does construction, fabrication, remodeling, uses CAD/CNC, needs estimation

3. MokshDigital (mokshdigital.net) — AI Digital Marketing Agency
   Target Customers: ANY business needing digital presence growth
   Services: Web Design, SEO/AEO, PPC/Google Ads, Social Media Management,
   Content Writing, Graphic Design, Branding
   Match signals: has basic/outdated website, no visible SEO, local service business needing more leads

4. MokshSigns (mokshsigns.com) — Signage Smartsourcing
   Target Customers: Sign fabricators, sign companies, builders, architects
   Services: Signage Estimation & Takeoffs, CNC Programming for signs,
   CAD 2D/3D for signs, Graphic Design, Data Processing
   Match signals: manufactures or installs signs, architectural signage, vehicle wraps
"""


# ====================================================================
# Analysis Function 1: Sales Brief
# ====================================================================

async def generate_sales_brief(
    company_name: str, website: str, content: str, thin_content: bool
) -> SalesBrief:
    """Generate the core sales brief from website content."""

    system_prompt = """You are a B2B sales research analyst. Analyze the website content and generate a structured sales brief.

Rules:
- Use ONLY information present in the provided content
- If a field cannot be determined, write "Not found in available content"
- Do NOT hallucinate or infer beyond what is stated
- Return ONLY valid JSON
- Be concise but specific"""

    user_prompt = f"""Company: {company_name}
Website: {website}
Content Quality: {"Limited content available" if thin_content else "Full content available"}

WEBSITE CONTENT:
{content}

Generate a JSON sales brief with exactly these fields:
{{
  "company_name": "official company name from the website",
  "company_overview": "2-3 sentence summary of what the company does",
  "core_product_service": "1-2 sentence description of their main offering",
  "target_customer": "who they primarily serve (homeowners, businesses, etc.)",
  "b2b_qualified": true/false,
  "b2b_reason": "one sentence explaining the B2B qualification decision",
  "sales_question_1": "specific, thoughtful question for a sales rep to ask",
  "sales_question_2": "specific, thoughtful question for a sales rep to ask",
  "sales_question_3": "specific, thoughtful question for a sales rep to ask",
  "research_confidence": "high, medium, or low"
}}

B2B Qualification Criteria:
- TRUE if: serves commercial/business clients, works on contracts, offers B2B services (HVAC maintenance, commercial landscaping, fleet repair, office moving), mentions "commercial", "business", "contracts"
- FALSE if: exclusively serves individual homeowners/retail consumers
- TRUE with low confidence if unclear (qualify, let sales rep verify)"""

    try:
        raw = await _async_call(system_prompt, user_prompt)
        data = json.loads(raw)
        return SalesBrief(**data)
    except Exception as e:
        print(f"[LLM] Sales brief error: {e}")
        return SalesBrief(company_name=company_name, research_confidence="low")


# ====================================================================
# Analysis Function 2: ICP Vertical Matching
# ====================================================================

async def match_icp_verticals(
    company_name: str, content: str, brief: SalesBrief, thin_content: bool
) -> ICPMatch:
    """Score the lead against all 4 Moksh verticals using deep LLM analysis."""

    system_prompt = f"""You are an elite B2B sales strategist and NLP engine for Moksh Group.
Analyze this company's exact business model, operations, and pain points to score how well they match each Moksh vertical.

{MOKSH_ICP_CONTEXT}

Rules:
- Deeply analyze the implied needs of their business model. (e.g., an architectural firm deeply needs CAD/Estimation. A local roofing company deeply needs digital marketing).
- Score 0-100 for relevance to each vertical based on the genuine value Moksh can provide.
- MokshDigital will often score highest for local service businesses that need lead generation.
- Be highly critical — if a vertical is irrelevant, score it 0-15.
- CRITICAL: If the company is in an industry that has essentially ZERO overlap with any Moksh vertical (e.g. dairy farming, global FMCG like Amul, Netflix, general consumer banking, sports teams), set is_good_fit to false and explain WHY in rejection_reason.
- A company is NOT a good fit if they are too massive to outsource to an SME agency, or in an industry Moksh doesn't serve.
- For each vertical, provide a brief, specific explanation of WHY it scored what it did based on their exact operations.
- Return ONLY valid JSON."""

    user_prompt = f"""Company: {company_name}
Industry: {brief.core_product_service}
Target Customer: {brief.target_customer}

WEBSITE CONTENT SUMMARY:
{content[:3000]}

Return JSON:
{{
  "mokshtech_score": 0-100,
  "mokshcad_score": 0-100,
  "mokshdigital_score": 0-100,
  "mokshsigns_score": 0-100,
  "best_fit_vertical": "MokshTech|MokshCAD|MokshDigital|MokshSigns|None",
  "pitch_angle": "2-3 sentence specific pitch explaining exactly what pain point this vertical solves for this company",
  "recommended_services": ["service1", "service2", "service3"],
  "is_good_fit": true/false,
  "fit_verdict": "Strong fit|Potential fit|Weak fit|Not a good fit",
  "rejection_reason": "Only if is_good_fit is false: explain WHY none of Moksh's verticals can genuinely help this company scale",
  "vertical_explanations": {{
    "MokshTech": "deep analysis of why they do/don't need outsourced IT/Service Desk based on their business model",
    "MokshCAD": "deep analysis of their drafting/estimation/BIM needs",
    "MokshDigital": "deep analysis of their lead generation / SEO needs",
    "MokshSigns": "deep analysis of their signage fabrication/takeoff needs"
  }}
}}"""

    try:
        await asyncio.sleep(CALL_DELAY)
        # Using a more powerful model for deep analysis
        raw = await _async_call(system_prompt, user_prompt, model="llama-3.3-70b-versatile")
        data = json.loads(raw)

        # Auto-detect no-fit if all scores are very low
        all_scores = [
            int(data.get("mokshtech_score", 0)),
            int(data.get("mokshcad_score", 0)),
            int(data.get("mokshdigital_score", 0)),
            int(data.get("mokshsigns_score", 0))
        ]
        if max(all_scores) < 20:
            data["is_good_fit"] = False
            data["fit_verdict"] = "Not a good fit"
            if not data.get("rejection_reason"):
                data["rejection_reason"] = f"{company_name} operates in an industry with no meaningful overlap with any Moksh Group vertical."

        return ICPMatch(**data)
    except Exception as e:
        print(f"[LLM] ICP match error: {e}")
        return ICPMatch()


# ====================================================================
# Analysis Function 3: Market Context & Differentiation
# ====================================================================

async def generate_market_context(
    company_name: str, content: str, brief: SalesBrief, thin_content: bool
) -> MarketContext:
    """Analyze market positioning from the company's own language."""

    infer_instruction = ""
    if thin_content:
        infer_instruction = """
IMPORTANT: This website has limited content. Use industry knowledge and the company's
location/industry to infer realistic market context. Set "ai_inferred": true in your response."""

    system_prompt = f"""You are a market analyst. Analyze how this company positions itself in its market based on their website language.
{infer_instruction}

Rules:
- Focus on competitive signals found IN the company's own words
- Look for phrases like "unlike others", "#1 rated", "trusted by", "certified", "award-winning"
- Return ONLY valid JSON"""

    user_prompt = f"""Company: {company_name}
Industry: {brief.core_product_service}
Location: derived from website
Content Quality: {"THIN — use industry inference" if thin_content else "Full content available"}

WEBSITE CONTENT:
{content[:2000]}

Return JSON:
{{
  "positioning": "How this company positions itself in the market (2-3 sentences)",
  "differentiation_signals": "What makes them claim to be different from competitors (from their own language)",
  "opportunity_gaps": "Identifiable gaps or growth opportunities a Moksh vertical could help with",
  "ai_inferred": true/false
}}"""

    try:
        await asyncio.sleep(CALL_DELAY)
        raw = await _async_call(system_prompt, user_prompt)
        data = json.loads(raw)
        return MarketContext(**data)
    except Exception as e:
        print(f"[LLM] Market context error: {e}")
        return MarketContext(ai_inferred=thin_content)


# ====================================================================
# Analysis Function 4: Outreach Email
# ====================================================================

async def generate_outreach_email(
    company_name: str, brief: SalesBrief, icp: ICPMatch
) -> OutreachEmail:
    """Generate a personalized cold outreach email."""

    system_prompt = """You are a sales copywriter for Moksh Group. Write a personalized cold email.

Rules:
- Keep it under 150 words
- Reference specific things about the prospect from their website
- Pitch from the best-fit Moksh vertical's perspective
- Include a clear call to action
- Professional but warm tone
- Return ONLY valid JSON"""

    user_prompt = f"""Prospect: {company_name}
Their Business: {brief.company_overview}
Their Core Service: {brief.core_product_service}
Their Target Customer: {brief.target_customer}

Best Moksh Vertical: {icp.best_fit_vertical}
Pitch Angle: {icp.pitch_angle}
Recommended Services: {", ".join(icp.recommended_services)}

Write a cold email from {icp.best_fit_vertical}'s perspective.

Return JSON:
{{
  "subject": "email subject line",
  "body": "full email body with greeting and sign-off"
}}"""

    try:
        await asyncio.sleep(CALL_DELAY)
        raw = await _async_call(system_prompt, user_prompt)
        data = json.loads(raw)
        return OutreachEmail(**data)
    except Exception as e:
        print(f"[LLM] Email generation error: {e}")
        return OutreachEmail(subject="", body="")


# ====================================================================
# Analysis Function 5: Objection Preparation
# ====================================================================

async def generate_objection_prep(
    company_name: str, brief: SalesBrief, icp: ICPMatch
) -> ObjectionPrep:
    """Pre-generate likely prospect objections with counter-responses."""

    system_prompt = """You are a sales trainer. Predict the top 2-3 objections this specific prospect will raise and prepare counter-responses.

Rules:
- Be specific to THIS company and industry, not generic
- Counters should be confident but respectful
- Include specific data points or value propositions
- Return ONLY valid JSON"""

    user_prompt = f"""Prospect: {company_name}
Their Business: {brief.core_product_service}
Their Target Customer: {brief.target_customer}
B2B Status: {"Qualified" if brief.b2b_qualified else "Not Qualified"}

Moksh Vertical Pitching: {icp.best_fit_vertical}
Services Being Pitched: {", ".join(icp.recommended_services)}

What objections will {company_name} likely raise when pitched by {icp.best_fit_vertical}?

Return JSON:
{{
  "objections": [
    {{
      "objection": "what the prospect might say",
      "counter": "how the sales rep should respond"
    }}
  ]
}}"""

    try:
        await asyncio.sleep(CALL_DELAY)
        raw = await _async_call(system_prompt, user_prompt)
        data = json.loads(raw)
        # Validate structure
        if "objections" in data:
            return ObjectionPrep(
                objections=[Objection(**obj) for obj in data["objections"][:3]]
            )
        return ObjectionPrep()
    except Exception as e:
        print(f"[LLM] Objection prep error: {e}")
        return ObjectionPrep()


# ====================================================================
# Full Analysis Pipeline (all 5 steps for one lead)
# ====================================================================

async def analyze_lead(
    company_name: str, website: str, content: str, thin_content: bool
) -> dict:
    """
    Run all 5 analysis steps for a single lead and return combined results.
    Steps run sequentially to respect rate limits.
    """
    print(f"[LLM] Analyzing: {company_name}")

    # Step 1: Core sales brief
    brief = await generate_sales_brief(company_name, website, content, thin_content)
    print(f"[LLM]   Brief done: confidence={brief.research_confidence}")

    # Step 2: ICP vertical matching
    icp = await match_icp_verticals(company_name, content, brief, thin_content)
    print(f"[LLM]   ICP done: best_fit={icp.best_fit_vertical}")

    # Step 3: Market context
    market = await generate_market_context(company_name, content, brief, thin_content)
    print(f"[LLM]   Market context done: ai_inferred={market.ai_inferred}")

    # Step 4: Outreach email
    email = await generate_outreach_email(company_name, brief, icp)
    print(f"[LLM]   Email done")

    # Step 5: Objection prep
    objections = await generate_objection_prep(company_name, brief, icp)
    print(f"[LLM]   Objections done: {len(objections.objections)} prepared")

    return {
        "brief": brief.model_dump(),
        "icp_match": icp.model_dump(),
        "market_context": market.model_dump(),
        "outreach_email": email.model_dump(),
        "objection_prep": objections.model_dump(),
    }
