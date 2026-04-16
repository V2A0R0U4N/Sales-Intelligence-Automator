"""
Pain Point Agent — Identifies specific pain points and buying signals.
"""

from pipeline.agents.base_agent import BaseAgent


class PainPointAgent(BaseAgent):
    name = "PainPointAgent"
    model = "llama-3.1-8b-instant"
    max_tokens = 500

    def build_system_prompt(self, **kwargs):
        return """You are a pain-point detection specialist for B2B sales.
Analyze the company's website and identify their likely pain points that our services could solve.

RULES:
- Focus on operational inefficiencies, growth blockers, technology gaps
- Score each pain point 1-10 on urgency
- Return ONLY valid JSON"""

    def build_user_prompt(self, **kwargs):
        company_name = kwargs.get("company_name", "")
        content = kwargs.get("content", "")[:2500]
        brief = kwargs.get("brief", {})
        return f"""Company: {company_name}
Industry: {brief.get('core_product_service', 'Unknown')}
Target Customer: {brief.get('target_customer', 'Unknown')}

CONTENT:
{content}

Return JSON:
{{
  "pain_points": [
    {{"pain": "description", "urgency": 1-10, "our_solution": "how we help"}},
  ],
  "buying_signals": ["signal1", "signal2"],
  "budget_indicator": "high|medium|low|unknown"
}}"""

    def parse_output(self, data):
        return {
            "pain_points": data.get("pain_points", [])[:5],
            "buying_signals": data.get("buying_signals", [])[:5],
            "budget_indicator": data.get("budget_indicator", "unknown"),
        }
