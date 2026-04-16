"""
Multi-Agent Orchestrator
========================
Coordinates specialized agents to run in parallel,
collects their outputs, and merges into a unified analysis.

Runs as an OPTIONAL enhancement layer on top of the existing
pipeline — falls back gracefully if agents fail.
"""

import asyncio
import logging
import time

from pipeline.agents.pain_point_agent import PainPointAgent
from pipeline.agents.personalization_agent import PersonalizationAgent
from pipeline.agents.competitive_agent import CompetitiveAgent

log = logging.getLogger(__name__)


class AgentOrchestrator:
    """
    Runs multiple specialized agents in parallel and merges results.
    
    Usage:
        orchestrator = AgentOrchestrator()
        extra_insights = await orchestrator.run(
            company_name="Acme Corp",
            content="...",
            brief={...},
            icp_match={...},
        )
    """

    def __init__(self):
        self.agents = [
            PainPointAgent(),
            PersonalizationAgent(),
            CompetitiveAgent(),
        ]

    async def run(self, **kwargs) -> dict:
        """
        Run all agents in parallel and merge their outputs.
        
        Returns a dict with keys from each agent's output, plus metadata.
        """
        start = time.time()
        log.info(f"[Orchestrator] Running {len(self.agents)} agents for: {kwargs.get('company_name', 'Unknown')}")

        # Run all agents concurrently
        tasks = [agent.run(**kwargs) for agent in self.agents]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge results
        merged = {
            "agent_insights": {},
            "agents_run": [],
            "agents_failed": [],
        }

        for agent, result in zip(self.agents, results):
            if isinstance(result, Exception):
                log.error(f"[Orchestrator] {agent.name} failed: {result}")
                merged["agents_failed"].append(agent.name)
            elif result:
                merged["agent_insights"][agent.name] = result
                merged["agents_run"].append(agent.name)
            else:
                merged["agents_failed"].append(agent.name)

        elapsed = int((time.time() - start) * 1000)
        merged["orchestrator_time_ms"] = elapsed
        merged["total_agents"] = len(self.agents)

        log.info(
            f"[Orchestrator] Complete: {len(merged['agents_run'])}/{len(self.agents)} "
            f"agents succeeded in {elapsed}ms"
        )

        return merged
