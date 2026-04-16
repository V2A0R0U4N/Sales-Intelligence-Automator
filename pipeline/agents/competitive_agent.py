"""
Competitive Intelligence Agent — Maps competitor landscape.
"""

from pipeline.agents.base_agent import BaseAgent


class CompetitiveAgent(BaseAgent):
    name = "CompetitiveAgent"
    model = "llama-3.1-8b-instant"
    max_tokens = 500

    def build_system_prompt(self, **kwargs):
        return """You are a competitive intelligence analyst.
Analyze the company's positioning and identify their competitive landscape.

RULES:
- Identify competitors they mention or imply
- Detect their unique selling propositions (USPs)
- Find weaknesses we can exploit in our pitch
- Return ONLY valid JSON"""

    def build_user_prompt(self, **kwargs):
        company_name = kwargs.get("company_name", "")
        content = kwargs.get("content", "")[:2500]
        brief = kwargs.get("brief", {})
        return f"""Company: {company_name}
Industry: {brief.get('core_product_service', 'Unknown')}

CONTENT:
{content}

Return JSON:
{{
  "mentioned_competitors": ["competitor names found on their site"],
  "usps": ["their unique selling propositions"],
  "weaknesses": ["potential gaps or pain points we can address"],
  "market_position": "leader|challenger|niche|emerging|unknown",
  "differentiation_angle": "how to differentiate our pitch from their current solutions"
}}"""

    def parse_output(self, data):
        return {
            "mentioned_competitors": data.get("mentioned_competitors", [])[:5],
            "usps": data.get("usps", [])[:4],
            "weaknesses": data.get("weaknesses", [])[:3],
            "market_position": data.get("market_position", "unknown"),
            "differentiation_angle": data.get("differentiation_angle", ""),
        }
