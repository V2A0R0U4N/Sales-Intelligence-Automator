"""
Personalization Agent — Generates hyper-personalized outreach content.
"""

from pipeline.agents.base_agent import BaseAgent


class PersonalizationAgent(BaseAgent):
    name = "PersonalizationAgent"
    model = "llama-3.1-8b-instant"
    max_tokens = 600

    def build_system_prompt(self, **kwargs):
        return """You are a sales personalization expert.
Generate hyper-personalized outreach content based on deep research.

RULES:
- Reference SPECIFIC details from their website (not generic fluff)
- Create a connection-request message for LinkedIn (<300 chars)
- Suggest the best subject line for cold email
- Generate 3 personalization hooks
- Return ONLY valid JSON"""

    def build_user_prompt(self, **kwargs):
        company_name = kwargs.get("company_name", "")
        brief = kwargs.get("brief", {})
        icp = kwargs.get("icp_match", {})
        return f"""Company: {company_name}
Overview: {brief.get('company_overview', '')[:300]}
Product: {brief.get('core_product_service', '')}
Best Fit: {icp.get('best_fit_vertical', '')}
Pitch: {(icp.get('pitch_angle', '') or '')[:200]}

Return JSON:
{{
  "linkedin_connection_request": "< 300 char personalized LinkedIn connection note",
  "best_email_subject": "compelling subject line",
  "personalization_hooks": [
    "hook referencing something specific from their website",
    "hook about their industry trend",
    "hook about a shared connection or interest"
  ],
  "call_to_action": "specific CTA for this company",
  "tone_recommendation": "formal|casual|consultative"
}}"""

    def parse_output(self, data):
        # Truncate LinkedIn request to 300 chars
        linkedin = data.get("linkedin_connection_request", "")
        if len(linkedin) > 300:
            linkedin = linkedin[:297] + "..."
        data["linkedin_connection_request"] = linkedin
        return data
