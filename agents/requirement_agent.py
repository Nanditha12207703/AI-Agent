"""
agents/requirement_agent.py
----------------------------
Extracts structured requirements from raw conversation text.
Returns typed, validated data ready for the database.
"""

import json
import re
from typing import Dict, Any, Optional, List
from agents.base_agent import BaseAgent
from models.router import TaskType

EXTRACTION_PROMPT = """You are a requirements extraction specialist. 
Analyze the conversation below and extract structured information.

Return ONLY valid JSON with these exact keys (use null for missing data):

{{
  "industry": "string or null",
  "company_name": "string or null",
  "business_problem": "detailed string or null",
  "current_tools": ["list", "of", "tools"],
  "required_integrations": ["list", "of", "integrations"],
  "budget": "string (e.g. '$50k', '$100k-200k', 'flexible') or null",
  "timeline": "string (e.g. '3 months', 'Q1 2025') or null",
  "constraints": "string describing technical/business constraints or null",
  "decision_maker": "name/role or null",
  "team_size": "string or null",
  "urgency": "low|medium|high or null",
  "additional_context": {{}}
}}

Conversation:
{conversation}

Return only the JSON object, no other text."""

COMPLETENESS_THRESHOLD = 0.6  # 60% of key fields needed before proposal


class RequirementAgent(BaseAgent):
    name = "RequirementAgent"
    task_type = TaskType.EXTRACTION

    # Fields and their weights for completeness score
    FIELD_WEIGHTS = {
        "industry": 0.15,
        "company_name": 0.10,
        "business_problem": 0.25,
        "budget": 0.15,
        "timeline": 0.15,
        "current_tools": 0.10,
        "constraints": 0.10,
    }

    async def run(
        self,
        conversation_history: List[Dict[str, str]],
        existing_requirements: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Extract requirements from conversation history.
        Merges with existing requirements (new data wins).

        Returns dict with extracted fields + completeness_score + is_complete.
        """
        conversation_text = self._format_conversation(conversation_history)

        prompt = EXTRACTION_PROMPT.format(conversation=conversation_text)
        raw = await self._generate(prompt=prompt, task_type=TaskType.EXTRACTION)

        extracted = self._parse_json(raw)
        if not extracted:
            self.log("Failed to parse requirements JSON", "warning")
            extracted = {}

        # Merge with existing (non-null new values override existing)
        merged = dict(existing_requirements or {})
        for key, value in extracted.items():
            if value is not None and value != [] and value != {}:
                merged[key] = value

        # Calculate completeness
        score = self._completeness_score(merged)
        merged["completeness_score"] = score
        merged["is_complete"] = score >= COMPLETENESS_THRESHOLD

        self.log(f"Requirements completeness: {score:.0%}")
        return merged

    async def extract_from_document(self, document_text: str,
                                     filename: str) -> Dict[str, Any]:
        """Extract requirements from an uploaded document."""
        prompt = f"""Extract all business requirements from this document.
        
Document: {filename}
Content:
{document_text[:6000]}  

{EXTRACTION_PROMPT.format(conversation='[Document content above]')}"""

        raw = await self._generate(prompt=prompt, task_type=TaskType.EXTRACTION)
        extracted = self._parse_json(raw) or {}
        score = self._completeness_score(extracted)
        extracted["completeness_score"] = score
        extracted["is_complete"] = score >= COMPLETENESS_THRESHOLD
        return extracted

    def _completeness_score(self, requirements: Dict) -> float:
        """Score 0.0-1.0 based on weighted field coverage."""
        score = 0.0
        for field, weight in self.FIELD_WEIGHTS.items():
            value = requirements.get(field)
            if value and value != [] and value != {}:
                score += weight
        return round(min(score, 1.0), 2)

    def _format_conversation(self, history: List[Dict]) -> str:
        return "\n".join(
            f"{msg['role'].capitalize()}: {msg['content']}"
            for msg in history[-30:]  # Last 30 messages
        )

    def _parse_json(self, raw: str) -> Optional[Dict]:
        """Robustly parse JSON from LLM output."""
        # Try direct parse
        try:
            return json.loads(raw.strip())
        except json.JSONDecodeError:
            pass

        # Try extracting JSON block
        match = re.search(r'\{[\s\S]+\}', raw)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return None

    def missing_fields(self, requirements: Dict) -> List[str]:
        """Return list of important fields not yet captured."""
        important = ["industry", "company_name", "business_problem", "budget", "timeline"]
        return [f for f in important if not requirements.get(f)]
