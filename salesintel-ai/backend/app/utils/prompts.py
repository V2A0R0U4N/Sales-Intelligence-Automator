"""
All LLM prompts as constants — never inline prompts in service code.
"""

# ─── Company Profile Extraction ───
COMPANY_PROFILE_EXTRACTION_PROMPT = """You are an expert business analyst. Analyze the scraped website content and extract a structured company profile.

SCRAPED CONTENT:
{content}

Return a JSON object with EXACTLY these fields:
{{
  "primary_services": [],        // Max 5 revenue-generating core services this company offers
  "secondary_services": [],      // Support/enabling capabilities (max 5)
  "industries_served": [],       // Who they sell to (industries/verticals)
  "company_type": "",            // "product" | "service" | "hybrid"
  "tech_stack_indicators": [],   // Technologies they use or build with
  "company_size_signals": "",    // headcount mentions, office count, team size indicators
  "geographic_presence": [],     // Cities, countries, regions mentioned
  "generic_capabilities": []     // Things ALL companies have: website, social media, email, digital presence
}}

Rules:
- Use ONLY information found in the content. Do NOT make assumptions.
- Be specific about services — "custom ERP development" not just "software development"
- "primary_services" should be the services they are KNOWN for and earn revenue from
- "generic_capabilities" should include things like "has a website", "has social media", "does content marketing" — things that are NOT differentiators
- If you cannot determine a field, use an empty array or empty string
"""

# ─── ICP Verification ───
ICP_VERIFICATION_PROMPT = """You are a sales strategy expert. Determine if this company is a genuine fit for the given Ideal Customer Profile.

ICP DESCRIPTION:
{icp_description}

COMPANY PROFILE:
- Primary Services: {primary_services}
- Industries Served: {industries_served}
- Company Type: {company_type}
- Company Size: {company_size}
- Geography: {geography}

Is this company a genuine fit for this ICP?

Respond with ONLY this JSON:
{{
  "fit_confirmed": true/false,
  "fit_reasoning": "2 sentences max explaining your decision",
  "primary_match_reason": "The #1 reason they fit (or don't)",
  "risk_factors": ["what might make them a bad fit"]
}}

Be critical. A true fit means the ICP's target customer description closely matches what this company IS or what this company NEEDS."""

# ─── Cold Email Generator ───
COLD_EMAIL_PROMPT = """Generate 3 cold email variations for pitching to {company_name}.

Company profile: {company_profile_json}
Our ICP description: {icp_description}
Primary match reason: {primary_match_reason}
Recommended pitch angle: {recommended_pitch_angle}

Variation 1 — Formal: Professional, structured, clear ROI focus
Variation 2 — Casual: Conversational, peer-to-peer tone
Variation 3 — Challenger: Opens with a provocative insight about their industry

Rules for all emails:
- Subject line: under 9 words, no spam triggers, no ALL CAPS
- Body: under 120 words
- Reference something SPECIFIC about {company_name} (not generic)
- One clear CTA — a specific calendar link or reply request
- No attachments mentioned
- No "I hope this email finds you well"
- No "I wanted to reach out"

Return JSON array: [{{\"subject\": \"\", \"body\": \"\", \"tone\": \"formal|casual|challenger\", \"estimated_read_time_seconds\": 0}}]"""

# ─── Objection Handler ───
OBJECTION_HANDLER_PROMPT = """Generate 15 objection-counter pairs for selling to {company_name}.

Company type: {company_type}
Their primary services: {primary_services}
Their industry: {industries_served}
Our solution: derived from ICP: {icp_description}

For each objection:
1. Write the objection as a sales person would actually hear it (natural language, not formal)
2. Write a counter that: acknowledges the concern, pivots with evidence, ends with a question that re-engages

Return JSON: [{{"objection": "", "counter": "", "category": "price|timing|trust|need|competitor"}}]"""

# ─── Pitch Script ───
PITCH_SCRIPT_PROMPT = """Generate a 3-minute verbal pitch outline for selling to {company_name}.

Company profile: {company_profile_json}
Our ICP: {icp_description}
Primary match reason: {primary_match_reason}

Structure the pitch as:
1. Opening hook (10 seconds) — reference something specific about their business
2. Pain point identification (30 seconds) — what challenges they likely face
3. Solution presentation (60 seconds) — how our offering addresses their needs
4. Proof points (30 seconds) — relevant results or capabilities
5. Call to action (10 seconds) — specific next step

Return JSON: {{"opening": "", "pain_points": "", "solution": "", "proof": "", "cta": "", "full_script": ""}}"""

# ─── LinkedIn DM ───
LINKEDIN_DM_PROMPT = """Write a LinkedIn direct message (under 300 characters) for reaching out to a decision-maker at {company_name}.

Company: {company_name}
What they do: {primary_services}
Why they're a fit: {primary_match_reason}

Rules:
- Under 300 characters total
- Personal, not salesy
- Reference their specific work
- End with a question

Return JSON: {{"message": ""}}"""

# ─── Discovery Questions ───
DISCOVERY_QUESTIONS_PROMPT = """Generate 6 discovery call questions for {company_name}.

Their business: {primary_services}
Their industry: {industries_served}
Why we're reaching out: {primary_match_reason}

Questions should:
- Uncover their current pain points
- Understand their decision-making process
- Identify budget and timeline
- Be open-ended, not yes/no

Return JSON: {{"questions": ["q1", "q2", ...]}}"""

# ─── Email Drip Sequence ───
EMAIL_SEQUENCE_PROMPT = """Create a 5-touch email drip sequence for {company_name}.

Company profile: {company_profile_json}
ICP: {icp_description}
Match reason: {primary_match_reason}

Touch 1 (Day 1): Introduction — reference specific company details
Touch 2 (Day 3): Value proposition — share an insight relevant to their industry
Touch 3 (Day 7): Social proof — mention results or capabilities relevant to them
Touch 4 (Day 14): Break-up style — create urgency without being pushy
Touch 5 (Day 21): Final value — share a resource and close the loop

Each email: subject under 9 words, body under 100 words, clear CTA.

Return JSON: [{{"touch_number": 1, "day": 1, "subject": "", "body": "", "cta_type": "reply|calendar|resource"}}]"""

# ─── Strict RAG Chatbot ───
RAG_SYSTEM_PROMPT = """You are a strict research assistant. You ONLY answer questions using the provided context documents below.

CRITICAL RULES:
1. If the answer is not found in the context, respond EXACTLY with:
   "I don't have this information from {company_name}'s website."
2. Never make assumptions. Never use general knowledge.
3. Never say "typically", "generally", "usually", or any word that implies you are drawing from outside knowledge.
4. Every claim must be directly supported by the context.
5. Always cite which page the information came from using: [Source: {{source_url}}]
6. If the context partially answers the question, give only what the context supports and say what is missing.

CONTEXT:
{retrieved_chunks_with_sources}

USER QUESTION: {user_question}"""

# ─── Quick ICP Proximity (pre-scrape) ───
QUICK_ICP_PROXIMITY_PROMPT = """You are a sales targeting analyst. Based on minimal information about a company, estimate how likely they are to match the given ICP.

ICP DESCRIPTION:
{icp_description}

COMPANY INFO (from search results only):
- Name: {company_name}
- Description: {description_snippet}
- Industry tags: {industry_tags}

On a scale of 0.0 to 1.0, how likely is this company to match the ICP?

Return JSON:
{{
  "proximity_score": 0.0,
  "reasoning": "1 sentence explaining the estimate",
  "suggested_category": "technology|digital_marketing|design_cad|manufacturing|healthcare|finance|retail|logistics|education|real_estate|other"
}}

Rules:
- Be conservative — without scraped data, don't score above 0.7
- If the company name/description has clear overlap with ICP keywords, score higher
- If no overlap is apparent, score below 0.3"""
