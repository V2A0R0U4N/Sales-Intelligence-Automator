"""
Bilingual Conversational Call Agent (Hindi + English)
=====================================================
A specialized agent for live & practice sales conversations.
Uses Groq LLaMA 3.1 for real-time, context-aware call responses.

Features:
  - Bilingual: English + Hindi (transliterated Hinglish)
  - Call script generation: openers, discovery questions, objection handling
  - Practice mode: salesperson can role-play against the AI
  - Uses Web Speech API (browser-native) for voice I/O — zero cost
"""

import os
import time
import json
import logging
from groq import Groq

log = logging.getLogger(__name__)

CALL_SYSTEM_PROMPT = """\
You are a world-class bilingual sales call coach for {company_name}.
You help salespeople practice calls and respond to live conversation scenarios.

ABOUT OUR COMPANY:
{company_description}

ABOUT THE LEAD WE'RE CALLING:
- Company: {lead_name}
- Overview: {lead_overview}
- Core Product/Service: {lead_product}
- Target Customer: {lead_target}
- Best ICP Fit: {icp_fit}
- Pitch Angle: {pitch_angle}

LANGUAGE RULES:
- Current mode: {language}
- If English: respond naturally in professional sales English
- If Hindi: respond in everyday Hinglish (Hindi written in English script/Roman Hindi)
  - Example: "Namaste ji, aapka business ke baare mein humne research kiya hai..."
  - Mix naturally like how Indian salespeople actually talk
  - DO NOT use Devanagari script, only Roman/English letters

CONVERSATION RULES:
1. Be concise — max 2-3 sentences per response
2. Sound natural, not scripted
3. Mirror the buyer's energy — if they're busy, be brief; if engaged, elaborate
4. Always nudge toward a meeting/demo booking
5. If asked about pricing, deflect to value first then offer to schedule a call
6. Handle objections with empathy, then pivot

Respond to the salesperson's scenario or continue the role-play conversation.
"""


def _build_call_context(lead_doc: dict, language: str = "english") -> str:
    """Build the system prompt with lead context."""
    brief = lead_doc.get("brief", {})
    icp = lead_doc.get("icp_match", {})

    return CALL_SYSTEM_PROMPT.format(
        company_name="Moksh Group",  # Will be dynamic with Phase 1 ICP
        company_description="B2B services: IT managed services, CAD outsourcing, digital marketing, signage",
        lead_name=lead_doc.get("company_name", "Unknown"),
        lead_overview=brief.get("company_overview", "Not available")[:200],
        lead_product=brief.get("core_product_service", "Not available"),
        lead_target=brief.get("target_customer", "Not available"),
        icp_fit=icp.get("best_fit_vertical", "Unknown"),
        pitch_angle=(icp.get("pitch_angle", "") or "")[:200],
        language=language,
    )


async def get_call_response(
    message: str,
    lead_doc: dict,
    conversation_history: list[dict],
    language: str = "english",
) -> dict:
    """
    Generate a call practice/live response.
    
    Args:
        message: The salesperson's input (what they said or scenario description)
        lead_doc: Full lead document from database
        conversation_history: List of prior messages [{role, content}, ...]
        language: "english" or "hindi"
    
    Returns:
        {"response": "...", "suggestion": "...", "response_time_ms": 820}
    """
    start = time.time()

    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    system_prompt = _build_call_context(lead_doc, language)

    # Build messages with recent history (last 10 turns to keep context manageable)
    messages = [{"role": "system", "content": system_prompt}]
    for msg in conversation_history[-10:]:
        messages.append({
            "role": msg.get("role", "user"),
            "content": msg.get("content", ""),
        })
    messages.append({"role": "user", "content": message})

    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",  # Fast for real-time conversation
            messages=messages,
            temperature=0.7,
            max_tokens=250,
        )

        reply = response.choices[0].message.content.strip()
        elapsed_ms = int((time.time() - start) * 1000)

        # Generate a follow-up suggestion
        suggestion = None
        if len(conversation_history) < 3:
            suggestion = "Try asking about their current challenges or pain points"
        elif len(conversation_history) < 6:
            suggestion = "Now steer toward how your solution addresses their specific need"
        else:
            suggestion = "You're deep in — push for a meeting or demo"

        return {
            "response": reply,
            "suggestion": suggestion,
            "response_time_ms": elapsed_ms,
            "language": language,
        }

    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        log.error(f"[CallAgent] Error: {e}")
        return {
            "response": "Sorry, I couldn't process that. Please try again.",
            "suggestion": None,
            "response_time_ms": elapsed_ms,
            "language": language,
            "error": str(e),
        }


def generate_call_opener(lead_doc: dict, language: str = "english") -> str:
    """
    Generate a cold call opening line for a specific lead.
    Synchronous — used during pipeline processing.
    """
    brief = lead_doc.get("brief", {})
    icp = lead_doc.get("icp_match", {})

    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    lang_instruction = ""
    if language == "hindi":
        lang_instruction = "Write in Hinglish (Hindi in Roman/English script). Example: 'Namaste ji, main [name] bol raha hoon [company] se...'"

    prompt = f"""Generate a cold call opening line (2 sentences max) for this lead.

Lead: {lead_doc.get('company_name', 'Unknown')}
Industry: {brief.get('core_product_service', 'Unknown')}
Our pitch angle: {(icp.get('pitch_angle', '') or '')[:150]}

{lang_instruction}

Return ONLY the opening line, nothing else."""

    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=100,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        log.error(f"[CallAgent] Opener error: {e}")
        return f"Hi, this is [Your Name] from Moksh Group. I noticed {lead_doc.get('company_name', 'your company')} is in the {brief.get('core_product_service', 'services')} space — do you have 2 minutes?"
