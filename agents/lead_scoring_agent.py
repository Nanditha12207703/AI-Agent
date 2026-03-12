"""
agents/lead_scoring_agent.py
-----------------------------
Scores leads based on extracted requirements and conversation signals.
Produces a 0-100 score with breakdown and conversion probability.
"""

import json
import re
from typing import Dict, Any, Optional
from agents.base_agent import BaseAgent
from models.router import TaskType
from config.settings import settings

SCORING_PROMPT = """You are a B2B sales qualification specialist.
Based on the following client requirements and conversation signals, 
generate a detailed lead score.

Requirements:
{requirements}

Conversation signals (tone, urgency, engagement):
{signals}

Return ONLY valid JSON:
{{
  "score": <integer 0-100>,
  "breakdown": {{
    "budget_fit": <0-20>,
    "timeline_clarity": <0-15>,
    "problem_urgency": <0-20>,
    "decision_maker_access": <0-15>,
    "company_fit": <0-15>,
    "engagement_quality": <0-15>
  }},
  "qualification": "<hot|warm|cold|unqualified>",
  "conversion_probability": "<High|Medium|Low>",
  "strengths": ["list of positive signals"],
  "risks": ["list of risk factors"],
  "recommended_actions": ["list of next steps"]
}}"""


class LeadScoringAgent(BaseAgent):
    name = "LeadScoringAgent"
    task_type = TaskType.ANALYSIS

    async def run(
        self,
        requirements: Dict[str, Any],
        conversation_signals: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Score the lead and return structured scoring data.

        Args:
            requirements: Extracted requirement dict.
            conversation_signals: Optional text summarizing conversation tone/urgency.

        Returns:
            Dict with score, breakdown, qualification, actions.
        """
        signals = conversation_signals or "No specific signals noted."
        prompt = SCORING_PROMPT.format(
            requirements=json.dumps(requirements, indent=2),
            signals=signals,
        )

        raw = await self._generate(prompt=prompt, task_type=TaskType.ANALYSIS)
        result = self._parse_json(raw)

        if not result:
            # Fallback scoring
            result = self._fallback_score(requirements)

        # Determine qualification label from settings thresholds
        score = result.get("score", 0)
        if score >= settings.lead_score_high_threshold:
            result["qualification"] = "hot"
        elif score >= settings.lead_score_medium_threshold:
            result["qualification"] = "warm"
        else:
            result["qualification"] = "cold"

        self.log(f"Lead score: {score}/100 ({result['qualification']})")
        return result

    def _fallback_score(self, requirements: Dict) -> Dict:
        """Rule-based fallback scoring when LLM fails."""
        score = 0
        breakdown = {
            "budget_fit": 0,
            "timeline_clarity": 0,
            "problem_urgency": 0,
            "decision_maker_access": 0,
            "company_fit": 0,
            "engagement_quality": 10,
        }

        if requirements.get("budget"):
            breakdown["budget_fit"] = 15
        if requirements.get("timeline"):
            breakdown["timeline_clarity"] = 10
        if requirements.get("business_problem"):
            breakdown["problem_urgency"] = 15
        if requirements.get("company_name"):
            breakdown["company_fit"] = 10
        if requirements.get("industry"):
            breakdown["company_fit"] += 5

        score = sum(breakdown.values())

        return {
            "score": min(score, 100),
            "breakdown": breakdown,
            "qualification": "warm" if score >= 40 else "cold",
            "conversion_probability": "Medium" if score >= 40 else "Low",
            "strengths": [],
            "risks": ["Incomplete requirements data"],
            "recommended_actions": ["Gather more information"],
        }

    def _parse_json(self, raw: str) -> Optional[Dict]:
        try:
            return json.loads(raw.strip())
        except json.JSONDecodeError:
            match = re.search(r'\{[\s\S]+\}', raw)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        return None
