"""
agents/proposal_agent.py
------------------------
Generates structured Zoho ecosystem proposal content from requirements.
Integrates ZohoSolutionMapper output into the proposal.

CONSTRAINT: Only Zoho products are ever recommended.
"""

import json
import re
from datetime import date
from typing import Dict, Any, List, Optional
from agents.base_agent import BaseAgent
from agents.zoho_mapper import ZohoSolutionMapper
from models.router import TaskType

PROPOSAL_PROMPT = """You are an expert Zoho Solutions Architect and presales proposal writer.

Generate a comprehensive, professional Zoho ecosystem proposal.

CRITICAL RULE: ONLY recommend Zoho products. Never suggest non-Zoho tools.
For any capability gap, always use: Zoho Creator, Zoho Flow, or Zoho Catalyst.

CLIENT REQUIREMENTS:
{requirements}

ZOHO SOLUTION MAPPING (pre-analyzed by our mapping engine):
{zoho_mapping}

SIMILAR PAST PROPOSALS (for reference):
{similar_proposals}

Generate a detailed proposal. Return ONLY valid JSON:

{{
  "executive_summary": "2-3 paragraph summary of the Zoho ecosystem solution",
  "client_overview": {{
    "company": "company name",
    "industry": "industry",
    "challenge": "concise problem statement"
  }},
  "proposed_solution": {{
    "overview": "high-level Zoho ecosystem description",
    "components": [
      {{
        "name": "Zoho Product Name",
        "description": "what this Zoho product does for the client",
        "benefit": "specific business benefit for the client"
      }}
    ],
    "architecture": "description of how the Zoho products interconnect",
    "differentiators": ["why Zoho is the right choice - specific points"]
  }},
  "zoho_ecosystem": {{
    "primary_apps": ["list of main Zoho apps"],
    "supporting_apps": ["list of supporting Zoho apps"],
    "integration_layer": "Zoho Flow or Zoho Creator for custom integrations",
    "architecture_diagram": "text-based diagram showing app connections"
  }},
  "implementation_plan": {{
    "phases": [
      {{
        "phase": "Phase 1",
        "name": "phase name",
        "duration": "e.g. 4 weeks",
        "zoho_apps": ["apps being configured in this phase"],
        "activities": ["activity 1", "activity 2"],
        "deliverables": ["deliverable 1"]
      }}
    ],
    "total_duration": "total project timeline"
  }},
  "api_integrations": [
    {{
      "product": "Zoho product name",
      "api_use": "what the API is used for",
      "endpoint": "API documentation URL"
    }}
  ],
  "investment": {{
    "investment_summary": "overview of Zoho licensing + implementation investment",
    "tiers": [
      {{
        "name": "tier name e.g. Essential",
        "price_range": "e.g. $X - $Y",
        "includes": ["Zoho apps and services included"]
      }}
    ],
    "roi_statement": "expected ROI from Zoho implementation",
    "payment_terms": "payment terms description"
  }},
  "why_zoho": [
    {{
      "point": "heading",
      "detail": "supporting detail about Zoho advantage"
    }}
  ],
  "next_steps": [
    {{
      "step": 1,
      "action": "action item",
      "owner": "Client | Our Team",
      "timeline": "e.g. Within 3 days"
    }}
  ],
  "terms_conditions": "brief terms and conditions paragraph",
  "validity": "proposal valid for X days"
}}

Return only the JSON object, no markdown or extra text."""


class ProposalAgent(BaseAgent):
    name = "ProposalAgent"
    task_type = TaskType.PROPOSAL

    def __init__(self):
        super().__init__()
        self._zoho_mapper = ZohoSolutionMapper()

    async def run(
        self,
        requirements: Dict[str, Any],
        similar_proposals: Optional[List[Dict]] = None,
        version: int = 1,
        zoho_mapping: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Generate Zoho ecosystem proposal content as structured dict.

        Args:
            requirements: Extracted requirements.
            similar_proposals: Past proposals from vector memory.
            version: Version number being generated.
            zoho_mapping: Pre-computed Zoho solution mapping (optional).

        Returns:
            Structured proposal dict ready for PDF rendering.
        """
        # Run Zoho mapping if not provided
        if not zoho_mapping:
            zoho_mapping = await self._zoho_mapper.run(
                requirements=requirements,
                business_problem=requirements.get("business_problem", ""),
            )

        similar_text = self._format_similar_proposals(similar_proposals or [])

        prompt = PROPOSAL_PROMPT.format(
            requirements=json.dumps(requirements, indent=2),
            zoho_mapping=json.dumps(zoho_mapping, indent=2),
            similar_proposals=similar_text,
        )

        raw = await self._generate(prompt=prompt, task_type=TaskType.PROPOSAL)
        content = self._parse_json(raw)

        if not content:
            self.log("Proposal JSON parse failed, using structured fallback", "warning")
            content = self._fallback_proposal(requirements, zoho_mapping)

        # Embed Zoho mapping data into the proposal
        content["zoho_solution_mapping"] = zoho_mapping

        # Add metadata
        content["metadata"] = {
            "version": version,
            "generated_date": date.today().isoformat(),
            "company_name": requirements.get("company_name", "Valued Client"),
            "industry": requirements.get("industry", ""),
            "zoho_products_count": len(zoho_mapping.get("recommended_products", [])),
        }

        self.log(
            f"Zoho proposal v{version} generated for "
            f"{content['metadata']['company_name']} with "
            f"{content['metadata']['zoho_products_count']} Zoho products"
        )
        return content

    def _format_similar_proposals(self, proposals: List[Dict]) -> str:
        if not proposals:
            return "No similar past proposals available."
        lines = []
        for i, p in enumerate(proposals[:3], 1):
            snippet = p.get("content", "")[:500]
            meta = p.get("metadata", {})
            lines.append(
                f"Past Proposal {i} (Industry: {meta.get('industry', 'N/A')}):\n{snippet}"
            )
        return "\n\n".join(lines)

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

    def _fallback_proposal(self, req: Dict, zoho_mapping: Dict) -> Dict:
        """Fallback Zoho proposal if LLM output cannot be parsed."""
        company = req.get("company_name", "Your Company")
        industry = req.get("industry", "your industry")
        problem = req.get("business_problem", "your business challenge")
        products = zoho_mapping.get("recommended_products", ["Zoho CRM", "Zoho Analytics"])
        architecture = zoho_mapping.get("solution_architecture", "Zoho integrated ecosystem")

        return {
            "executive_summary": (
                f"We are pleased to present this Zoho ecosystem proposal to {company}. "
                f"Our solution addresses {problem} using a fully integrated Zoho platform "
                f"tailored for the {industry} sector. "
                f"The proposed solution includes {', '.join(products[:4])} working together "
                f"seamlessly to deliver measurable business outcomes."
            ),
            "client_overview": {
                "company": company,
                "industry": industry,
                "challenge": problem,
            },
            "proposed_solution": {
                "overview": f"A comprehensive Zoho ecosystem using {len(products)} integrated applications.",
                "components": [
                    {
                        "name": p,
                        "description": f"Core {p} functionality configured for {industry}",
                        "benefit": "Streamlined operations and improved efficiency",
                    }
                    for p in products
                ],
                "architecture": architecture,
                "differentiators": [
                    "All-in-one Zoho ecosystem eliminates data silos",
                    "Native integrations between all Zoho apps",
                    "Single vendor for support and licensing",
                    "Scalable as your business grows",
                    "Mobile-ready across all Zoho applications",
                ],
            },
            "zoho_ecosystem": {
                "primary_apps": products[:3],
                "supporting_apps": products[3:],
                "integration_layer": "Zoho Flow for workflow automation between apps",
                "architecture_diagram": architecture,
            },
            "implementation_plan": {
                "phases": [
                    {
                        "phase": "Phase 1",
                        "name": "Foundation Setup",
                        "duration": "3 weeks",
                        "zoho_apps": products[:2],
                        "activities": ["Zoho account setup", "Data migration", "User configuration"],
                        "deliverables": ["Configured Zoho environment", "User accounts"],
                    },
                    {
                        "phase": "Phase 2",
                        "name": "Integration & Automation",
                        "duration": "4 weeks",
                        "zoho_apps": products[2:] + ["Zoho Flow"],
                        "activities": ["App integrations", "Workflow automation", "Custom forms"],
                        "deliverables": ["Automated workflows", "Integration documentation"],
                    },
                    {
                        "phase": "Phase 3",
                        "name": "Training & Go-Live",
                        "duration": "2 weeks",
                        "zoho_apps": products,
                        "activities": ["User training", "UAT", "Go-live support"],
                        "deliverables": ["Trained users", "Go-live sign-off"],
                    },
                ],
                "total_duration": req.get("timeline", "9 weeks"),
            },
            "api_integrations": zoho_mapping.get("api_integrations", []),
            "investment": {
                "investment_summary": "Zoho licensing + implementation and configuration services.",
                "tiers": [
                    {
                        "name": "Essential",
                        "price_range": req.get("budget", "To be confirmed"),
                        "includes": products[:3] + ["Implementation", "3 months support"],
                    },
                    {
                        "name": "Professional",
                        "price_range": "Custom pricing",
                        "includes": products + ["Full implementation", "12 months support", "Training"],
                    },
                ],
                "roi_statement": "Expected ROI within 6-12 months through automation and efficiency gains.",
                "payment_terms": "50% upfront, 50% on successful go-live.",
            },
            "why_zoho": [
                {"point": "Unified Platform", "detail": "45+ apps working as one — no integration headaches."},
                {"point": "Cost Effective", "detail": "One subscription covers your entire business tech stack."},
                {"point": "Scalable", "detail": "Add Zoho apps as your business grows without switching vendors."},
                {"point": "Data Privacy", "detail": "Zoho does not sell your data to advertisers."},
                {"point": "Certified Support", "detail": "Dedicated implementation from certified Zoho partners."},
            ],
            "next_steps": [
                {"step": 1, "action": "Review Zoho proposal", "owner": "Client", "timeline": "3 days"},
                {"step": 2, "action": "Zoho demo session", "owner": "Our Team", "timeline": "5 days"},
                {"step": 3, "action": "Confirm product scope", "owner": "Both", "timeline": "7 days"},
                {"step": 4, "action": "Sign agreement and begin Phase 1", "owner": "Both", "timeline": "10 days"},
            ],
            "terms_conditions": "This Zoho ecosystem proposal is confidential and valid for 30 days.",
            "validity": "30 days",
        }
