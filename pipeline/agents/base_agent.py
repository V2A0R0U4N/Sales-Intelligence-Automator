"""
Base Agent — Abstract foundation for all specialized agents.
============================================================
"""

import os
import json
import re
import asyncio
import time
import logging
from typing import Optional
from groq import Groq

log = logging.getLogger(__name__)

CALL_DELAY = 2.0  # Groq rate limit buffer


class BaseAgent:
    """
    Abstract base for all specialized analysis agents.
    
    Each agent has a single responsibility and produces
    a structured JSON output from website content.
    """

    name: str = "BaseAgent"
    model: str = "llama-3.1-8b-instant"  # Default: fast model
    max_tokens: int = 600
    temperature: float = 0.3

    def __init__(self):
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    def build_system_prompt(self, **kwargs) -> str:
        """Override in subclass — return the system prompt."""
        raise NotImplementedError

    def build_user_prompt(self, **kwargs) -> str:
        """Override in subclass — return the user prompt."""
        raise NotImplementedError

    def parse_output(self, raw_json: dict) -> dict:
        """Override in subclass — validate and clean LLM output."""
        return raw_json

    async def run(self, **kwargs) -> dict:
        """Execute the agent and return structured output."""
        start = time.time()
        system_prompt = self.build_system_prompt(**kwargs)
        user_prompt = self.build_user_prompt(**kwargs)

        try:
            await asyncio.sleep(CALL_DELAY)
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            raw = response.choices[0].message.content.strip()

            # Extract JSON from response
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                result = self.parse_output(data)
                elapsed = int((time.time() - start) * 1000)
                log.info(f"[{self.name}] Completed in {elapsed}ms")
                return result

            log.warning(f"[{self.name}] No JSON found in response")
            return {}

        except Exception as e:
            log.error(f"[{self.name}] Error: {e}")
            return {}
