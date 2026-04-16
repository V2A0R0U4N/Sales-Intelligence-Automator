"""
RAG Chat Engine
===============
Per-lead chatbot that answers questions using lead-specific context.
Uses Groq LLaMA for generation. Context is passed directly in the
prompt (stuffing approach) — avoids ChromaDB dependency for zero-cost.

Features:
  - Answers questions about a specific lead
  - Uses all analysis data (brief, ICP, market, email, enrichment)
  - Maintains conversation history
  - Generates suggested follow-up questions
  - STRICT guardrails — rejects off-topic, math, coding, personal questions
"""

import os
import re
import json
import time
import logging
from groq import Groq

log = logging.getLogger(__name__)

SUGGESTED_QUESTIONS = [
    "What are the best services to pitch to this company?",
    "What pain points does this company likely have?",
    "How should I open a cold call with this prospect?",
    "What objections should I expect and how do I handle them?",
    "Write me a 30-second elevator pitch for this lead.",
    "What differentiates us from their current solutions?",
]

# ─── Pre-LLM Input Filters ────────────────────────────────────────────
# Fast regex/keyword checks that reject obviously off-topic inputs
# before they ever hit the LLM (saves tokens and prevents leaks).

_MATH_PATTERN = re.compile(r'^\s*\d+\s*[\+\-\*/\^%]\s*\d+', re.IGNORECASE)
_CODE_KEYWORDS = [
    'write code', 'write a code', 'python code', 'javascript code',
    'write me a function', 'write a function', 'def ', 'class ',
    'import ', 'console.log', 'print(', 'for loop', 'while loop',
    'algorithm', 'html code', 'css code', 'sql query', 'write a script',
    'provide me code', 'provide code', 'give me code', 'code for',
    'program for', 'write a program', 'coding', 'write python',
    'write java', 'write c++', 'sum of', 'factorial', 'fibonacci',
]
_PERSONAL_KEYWORDS = [
    'who are you', 'what are you', 'are you a', 'your name',
    'are you gay', 'are you male', 'are you female', 'your feelings',
    'do you feel', 'are you human', 'are you ai', 'are you real',
    'how old are you', 'where do you live', 'what gender',
    'your opinion on', 'your favorite', 'do you like',
]
_GENERAL_CHAT = [
    'tell me a joke', 'tell a joke', 'sing a song', 'write a poem',
    'what is the meaning of life', 'tell me something interesting',
    'what is the weather', 'what time is it', 'translate this',
    'explain quantum', 'what is ai', 'history of', 'capital of',
]


def _is_off_topic(message: str) -> tuple[bool, str]:
    """
    Fast pre-LLM check. Returns (is_off_topic, rejection_reason).
    """
    msg_lower = message.lower().strip()

    # Math expressions
    if _MATH_PATTERN.search(msg_lower):
        return True, "math questions"

    # Code requests
    for kw in _CODE_KEYWORDS:
        if kw in msg_lower:
            return True, "coding or programming requests"

    # Personal questions
    for kw in _PERSONAL_KEYWORDS:
        if kw in msg_lower:
            return True, "personal questions"

    # General chat / knowledge
    for kw in _GENERAL_CHAT:
        if kw in msg_lower:
            return True, "general knowledge questions"

    return False, ""


def _count_off_topic_drift(conversation_history: list[dict]) -> int:
    """Count how many recent consecutive user messages were off-topic."""
    count = 0
    for msg in reversed(conversation_history):
        if msg.get("role") != "user":
            continue
        off, _ = _is_off_topic(msg.get("content", ""))
        if off:
            count += 1
        else:
            break
    return count


def build_lead_context(lead_doc: dict) -> str:
    """
    Build a comprehensive context string from all analysis data.
    This is the 'retrieval' step — we stuff all available data into context.
    """
    brief = lead_doc.get("brief", {})
    icp = lead_doc.get("icp_match", {})
    market = lead_doc.get("market_context", {})
    email = lead_doc.get("outreach_email", {})
    objections = lead_doc.get("objection_prep", {})
    enriched = lead_doc.get("enriched_data", {})
    agents = lead_doc.get("agent_insights", {})

    sections = []

    # Core info
    sections.append(f"COMPANY: {lead_doc.get('company_name', 'Unknown')}")
    sections.append(f"WEBSITE: {lead_doc.get('website', 'N/A')}")

    # Sales brief
    if brief:
        sections.append(f"\nSALES BRIEF:")
        sections.append(f"  Overview: {brief.get('company_overview', 'N/A')}")
        sections.append(f"  Product/Service: {brief.get('core_product_service', 'N/A')}")
        sections.append(f"  Target Customer: {brief.get('target_customer', 'N/A')}")
        sections.append(f"  B2B Qualified: {brief.get('b2b_qualified', 'Unknown')}")
        sections.append(f"  B2B Reason: {brief.get('b2b_reason', 'N/A')}")
        sections.append(f"  Confidence: {brief.get('research_confidence', 'low')}")

    # ICP match
    if icp:
        sections.append(f"\nICP MATCH:")
        sections.append(f"  Best Fit Vertical: {icp.get('best_fit_vertical', 'None')}")
        sections.append(f"  Is Good Fit: {icp.get('is_good_fit', 'Unknown')}")
        sections.append(f"  Fit Verdict: {icp.get('fit_verdict', 'Not analyzed')}")
        sections.append(f"  Pitch Angle: {icp.get('pitch_angle', 'N/A')}")
        sections.append(f"  Recommended Services: {', '.join(icp.get('recommended_services', []))}")
        vs = icp.get("vertical_scores", {})
        if vs:
            sections.append(f"  Vertical Scores: {json.dumps(vs)}")
        ve = icp.get("vertical_explanations", {})
        if ve:
            for k, v in ve.items():
                sections.append(f"    {k}: {v}")

    # Market context
    if market:
        sections.append(f"\nMARKET CONTEXT:")
        sections.append(f"  Competitive Position: {market.get('competitive_position', 'N/A')}")
        sections.append(f"  Growth Indicators: {', '.join(market.get('growth_indicators', []))}")
        sections.append(f"  Certifications: {', '.join(market.get('certifications', []))}")

    # Outreach email
    if email:
        sections.append(f"\nDRAFT EMAIL:")
        sections.append(f"  Subject: {email.get('subject', 'N/A')}")
        sections.append(f"  Body: {email.get('body', 'N/A')[:500]}")

    # Objection prep
    if objections and objections.get("objections"):
        sections.append(f"\nOBJECTION PREP:")
        for obj in objections.get("objections", []):
            sections.append(f"  Objection: {obj.get('objection', '')}")
            sections.append(f"  Counter: {obj.get('counter', '')}")

    # Enrichment data
    if enriched:
        sections.append(f"\nENRICHMENT DATA:")
        sections.append(f"  Employees: {enriched.get('employee_estimate', 'Unknown')}")
        sections.append(f"  Revenue: {enriched.get('revenue_estimate', 'Unknown')}")
        sections.append(f"  Founded: {enriched.get('founded_year', 'Unknown')}")
        sections.append(f"  HQ: {enriched.get('headquarters', 'Unknown')}")
        tech = enriched.get("tech_stack", [])
        if tech:
            tech_names = [t.get("name", "") if isinstance(t, dict) else str(t) for t in tech]
            sections.append(f"  Tech Stack: {', '.join(tech_names)}")
        dms = enriched.get("decision_makers", [])
        if dms:
            for dm in dms:
                dm_info = dm if isinstance(dm, dict) else {}
                sections.append(f"  Contact: {dm_info.get('name', 'N/A')} — {dm_info.get('title', 'N/A')}")

    # Agent insights
    if agents:
        for agent_name, insights in agents.items():
            if isinstance(insights, dict):
                sections.append(f"\n{agent_name.upper()} INSIGHTS:")
                for k, v in insights.items():
                    sections.append(f"  {k}: {json.dumps(v) if isinstance(v, (list, dict)) else v}")

    return "\n".join(sections)


RAG_SYSTEM_PROMPT = """\
You are a sales intelligence assistant with data ONLY about {company_name}.
You exist to help salespeople prepare for calls and craft pitches for this SPECIFIC prospect.

LEAD DATA:
{context}

════════════════════════════════════════════════════════
ABSOLUTE RESTRICTIONS — YOU MUST NEVER VIOLATE THESE:
════════════════════════════════════════════════════════
1. You are ONLY allowed to discuss {company_name} and sales strategy for this specific prospect.
2. If the user asks ANYTHING not related to this lead — math, coding, personal questions, general knowledge, trivia, opinions, translations, or ANY other topic — respond EXACTLY with:
   "I can only help with questions about {company_name}. Try asking about their pain points, our pitch strategy, or how to approach them."
3. This applies even if the request seems harmless (like "what is 2+2") or educational.
4. If the user embeds an off-topic request within a seemingly relevant question, still refuse the off-topic part.
5. If the user starts with relevant questions and then drifts to unrelated topics, KEEP REFUSING. Do not comply just because earlier questions were valid.
6. NEVER write code, solve math problems, discuss yourself, answer personal questions, or provide information not grounded in the lead data above.
7. NEVER say "however, I can tell you that..." followed by an off-topic answer. Just refuse cleanly.

RESPONSE RULES (for valid, on-topic questions):
1. Answer using ONLY the data above — don't hallucinate
2. Be specific — reference exact data points from the lead
3. Be concise — max 3-4 sentences unless user asks for detail
4. If data is unavailable, say so honestly
5. Always be actionable — suggest next steps when relevant
6. For pitch suggestions, reference specific services and pain points
"""

_REFUSAL = "I can only help with questions about {company_name}. Try asking about their pain points, our pitch strategy, or how to approach them."


async def rag_chat(
    message: str,
    lead_doc: dict,
    conversation_history: list[dict],
) -> dict:
    """
    RAG-powered chat response for a specific lead.
    
    Args:
        message: User's question
        lead_doc: Full lead document with all analysis data
        conversation_history: Prior conversation messages
    
    Returns:
        {"response": "...", "suggested_questions": [...], "response_time_ms": 820}
    """
    start = time.time()
    company_name = lead_doc.get("company_name", "this company")

    # ── Layer 1: Pre-LLM off-topic filter ─────────────────────────────
    off_topic, reason = _is_off_topic(message)
    if off_topic:
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "response": _REFUSAL.format(company_name=company_name),
            "suggested_questions": _pick_suggested_questions(message, conversation_history),
            "response_time_ms": elapsed_ms,
            "blocked": True,
            "block_reason": reason,
        }

    # ── Layer 2: Drift detection ──────────────────────────────────────
    drift_count = _count_off_topic_drift(conversation_history)
    drift_warning = ""
    if drift_count >= 2:
        drift_warning = (
            "\n\nWARNING: The user has been asking off-topic questions repeatedly. "
            "Be EXTRA strict. If this question is even slightly off-topic, refuse immediately."
        )

    # ── Build context and call LLM ────────────────────────────────────
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    context = build_lead_context(lead_doc)

    system_prompt = RAG_SYSTEM_PROMPT.format(
        context=context, company_name=company_name
    ) + drift_warning

    messages = [{"role": "system", "content": system_prompt}]
    for msg in conversation_history[-8:]:
        messages.append({
            "role": msg.get("role", "user"),
            "content": msg.get("content", ""),
        })
    messages.append({"role": "user", "content": message})

    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            temperature=0.3,
            max_tokens=500,
        )

        reply = response.choices[0].message.content.strip()
        elapsed_ms = int((time.time() - start) * 1000)

        # Generate contextual suggested questions
        suggested = _pick_suggested_questions(message, conversation_history)

        return {
            "response": reply,
            "suggested_questions": suggested,
            "response_time_ms": elapsed_ms,
        }

    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        log.error(f"[RAG] Chat error: {e}")
        return {
            "response": "Sorry, I couldn't process that question. Please try again.",
            "suggested_questions": SUGGESTED_QUESTIONS[:3],
            "response_time_ms": elapsed_ms,
            "error": str(e),
        }


def _pick_suggested_questions(
    current_msg: str, history: list[dict]
) -> list[str]:
    """Pick 3 suggested follow-up questions, avoiding repeats."""
    asked = {current_msg.lower()}
    for msg in history:
        asked.add(msg.get("content", "").lower())

    suggestions = []
    for q in SUGGESTED_QUESTIONS:
        if q.lower() not in asked:
            suggestions.append(q)
        if len(suggestions) >= 3:
            break

    return suggestions


def get_initial_suggestions() -> list[str]:
    """Return initial suggested questions for a fresh chat."""
    return SUGGESTED_QUESTIONS[:4]
