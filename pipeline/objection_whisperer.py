"""
Real-Time Objection Handler — The Whisperer
============================================
Provides instant counter-responses during live sales calls.

When a sales rep is on a call and hears an objection, they type it here
and get a verbatim response in ~800ms — fast enough to use mid-conversation.

Tech: Groq + LLaMA 3.1 8B Instant (fastest Groq model, free tier)
No paid APIs. No external services.
"""

import re
import time
import os
from groq import Groq

# Fastest Groq model — prioritise speed over depth for real-time use
CALL_MODEL = "llama-3.1-8b-instant"

WHISPERER_SYSTEM = """\
You are a real-time sales coaching assistant whispering to a rep who is CURRENTLY ON A LIVE CALL.
They need an instant, verbatim response to an objection they just heard. Time is critical.

YOUR COMPANY CONTEXT:
- Company: {company_name}
- What you offer: {company_description}

LIVE LEAD PROFILE:
- Prospect Company: {lead_company}
- Their Core Business: {industry}
- Tech Stack Detected: {tech_stack}
- Best Fit for Our Services: {best_fit_vertical}

PRE-GENERATED BATTLECARD (use these if relevant):
{battlecard}

OUTPUT FORMAT — use EXACTLY this structure, nothing else:
[SAY THIS:] <the exact sentence(s) the rep should say right now — STATEMENTS ONLY, NO QUESTIONS>
[PROBE:] <one follow-up question to keep the conversation going>

STRICT RULES:
1. [SAY THIS:] must contain ONLY declarative statements (max 3 sentences). NEVER put any questions (sentences ending with ?) in [SAY THIS:]. All questions MUST go in [PROBE:] only.
2. Always start [SAY THIS:] with 1 word of empathy (e.g. "Absolutely,", "Totally,", "Fair enough —").
3. Then pivot to an insight or value statement specific to THIS lead's industry/tech stack.
4. [PROBE:] must contain exactly ONE question — a follow-up that buys the rep time and keeps the conversation going.
5. Write what the REP says, never explain your reasoning.
6. NEVER mix questions into [SAY THIS:] — a question mark (?) must ONLY appear inside [PROBE:]."""


async def get_objection_counter(objection: str, lead_doc: dict) -> dict:
    """
    Generate an instant objection counter for a live sales call.

    Args:
        objection:  The exact words/objection the rep just heard on the call.
        lead_doc:   Full lead document retrieved from the database.

    Returns:
        dict with keys:
            counter (str)            — What the rep should say verbatim
            probe (str | None)       — Optional follow-up question
            matched_battlecard (bool)— Whether we matched a pre-generated counter
            response_time_ms (int)   — How long the LLM took
    """
    start = time.perf_counter()

    # ── Pull context from the lead document ──────────────────────────
    icp = lead_doc.get("icp_match", {})
    brief = lead_doc.get("brief", {})
    enriched = lead_doc.get("enriched_data", {})
    obj_prep = lead_doc.get("objection_prep", {})

    # Build a compact battlecard string from pre-generated objection prep
    raw_objections = obj_prep.get("objections", [])
    battlecard_lines = []
    for o in raw_objections:
        o_text = o.get("objection", "").strip()
        c_text = o.get("counter", "").strip()
        if o_text and c_text:
            battlecard_lines.append(f'• Objection: "{o_text}"\n  Counter: {c_text}')
    battlecard = "\n".join(battlecard_lines) if battlecard_lines else "None available yet."

    # Tech stack summary
    tech_names = [t.get("name", "") for t in enriched.get("tech_stack", []) if t.get("name")]
    tech_str = ", ".join(tech_names[:5]) if tech_names else "Unknown"

    # Company info (may be set after Phase 1 ICP integration; fallback to Moksh defaults)
    company_name = lead_doc.get("_icp_company_name", "Moksh Group")
    company_desc = lead_doc.get("_icp_description", "IT managed services, CAD outsourcing, digital marketing, and signage")

    system_prompt = WHISPERER_SYSTEM.format(
        company_name=company_name,
        company_description=company_desc,
        lead_company=lead_doc.get("company_name", "the prospect"),
        industry=brief.get("core_product_service", "their industry"),
        tech_stack=tech_str,
        best_fit_vertical=icp.get("best_fit_vertical", "TBD"),
        battlecard=battlecard,
    )

    # ── Call Groq ─────────────────────────────────────────────────────
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    try:
        response = client.chat.completions.create(
            model=CALL_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f'Objection I just heard: "{objection}"'},
            ],
            temperature=0.35,   # Lower temp = more reliable format
            max_tokens=220,
        )

        raw_text = response.choices[0].message.content.strip()

        # ── Parse structured output ───────────────────────────────────
        say_match = re.search(
            r"\[SAY THIS:\]\s*(.*?)(?=\[PROBE:\]|$)",
            raw_text,
            re.DOTALL | re.IGNORECASE,
        )
        probe_match = re.search(
            r"\[PROBE:\]\s*(.*?)$",
            raw_text,
            re.DOTALL | re.IGNORECASE,
        )

        counter = say_match.group(1).strip() if say_match else raw_text
        probe_raw = probe_match.group(1).strip() if probe_match else None

        # Clean trailing whitespace / newlines from probe
        probe = probe_raw.strip() if probe_raw else None

        # Check if we hit a pre-generated battlecard entry
        objection_lower = objection.lower()
        matched_battlecard = any(
            o.get("objection", "").lower()[:25] in objection_lower
            for o in raw_objections
            if o.get("objection")
        )

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        return {
            "counter": counter,
            "probe": probe,
            "matched_battlecard": matched_battlecard,
            "response_time_ms": elapsed_ms,
        }

    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        # Fail gracefully — return a safe generic counter so the rep isn't left hanging
        return {
            "counter": (
                "Totally fair — a lot of our clients felt the same way initially. "
                "What I've seen work is taking 10 minutes to walk through a real example "
                f"from someone in {brief.get('core_product_service', 'your space')}. "
                "Would that be helpful?"
            ),
            "probe": "What would need to be true for this to be worth exploring?",
            "matched_battlecard": False,
            "response_time_ms": elapsed_ms,
            "error": str(exc),
        }
