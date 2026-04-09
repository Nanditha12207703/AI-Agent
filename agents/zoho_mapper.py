"""
agents/zoho_mapper.py
---------------------
Zoho Solution Mapping Engine.

Maps client business problems → Zoho product recommendations →
Solution architecture → API integration plan.

CONSTRAINT: Only Zoho products are ever recommended.
If a capability gap exists, it is filled with Zoho Creator, Zoho Flow,
or Zoho Catalyst — never with third-party tools.
"""

from typing import Dict, List, Any
import json
import re

from agents.base_agent import BaseAgent
from models.router import TaskType


# ── Master Zoho Product Catalog ───────────────────────────────────────────────

ZOHO_PRODUCTS = {
    "Zoho CRM": {
        "category": "Sales & Lead Management",
        "description": "End-to-end CRM for lead tracking, pipeline management, and sales automation.",
        "api": "https://www.zoho.com/crm/developer/docs/api/v6/",
        "key_apis": ["Lead creation", "Contact management", "Deal pipeline", "Activity logging"],
    },
    "Zoho SalesIQ": {
        "category": "Sales & Lead Management",
        "description": "Live chat and visitor tracking to capture and qualify website leads.",
        "api": "https://www.zoho.com/salesiq/help/developer-guide/rest-api.html",
        "key_apis": ["Visitor tracking", "Chat widget", "Lead capture", "Bot automation"],
    },
    "Zoho Campaigns": {
        "category": "Marketing Automation",
        "description": "Email marketing and automation platform for nurturing leads and customers.",
        "api": "https://www.zoho.com/campaigns/help/developers/campaign-management.html",
        "key_apis": ["Campaign creation", "List management", "Automation workflows", "Analytics"],
    },
    "Zoho Desk": {
        "category": "Customer Support",
        "description": "Help desk and ticketing system for customer support operations.",
        "api": "https://desk.zoho.com/support/APIDocument.do",
        "key_apis": ["Ticket creation", "Agent assignment", "SLA management", "Knowledge base"],
    },
    "Zoho Analytics": {
        "category": "Data & Reporting",
        "description": "Business intelligence and data analytics platform with dashboards and reports.",
        "api": "https://www.zoho.com/analytics/api/",
        "key_apis": ["Data import", "Report generation", "Dashboard embedding", "Data blending"],
    },
    "Zoho Books": {
        "category": "Finance & Accounting",
        "description": "Full-featured accounting software for invoicing, expenses, and financial reporting.",
        "api": "https://www.zoho.com/books/api/v3/",
        "key_apis": ["Invoice creation", "Payment recording", "Expense tracking", "Financial reports"],
    },
    "Zoho Invoice": {
        "category": "Finance & Accounting",
        "description": "Standalone invoicing tool for creating and sending professional invoices.",
        "api": "https://www.zoho.com/invoice/api/v3/",
        "key_apis": ["Invoice management", "Payment gateway", "Recurring billing", "Customer portal"],
    },
    "Zoho Expense": {
        "category": "Finance & Accounting",
        "description": "Expense reporting and approval management for teams.",
        "api": "https://www.zoho.com/expense/help/developer-guide/overview.html",
        "key_apis": ["Expense submission", "Approval workflows", "Receipt scanning", "Policy enforcement"],
    },
    "Zoho Inventory": {
        "category": "Inventory & Operations",
        "description": "Multi-channel inventory and order management system.",
        "api": "https://www.zoho.com/inventory/api/v1/",
        "key_apis": ["Item management", "Order processing", "Stock tracking", "Warehouse management"],
    },
    "Zoho People": {
        "category": "Human Resources",
        "description": "HR management platform for employee records, leave, attendance, and performance.",
        "api": "https://www.zoho.com/people/api/overview.html",
        "key_apis": ["Employee onboarding", "Leave management", "Attendance tracking", "Performance reviews"],
    },
    "Zoho Recruit": {
        "category": "Human Resources",
        "description": "Applicant tracking system for recruiting and hiring workflows.",
        "api": "https://www.zoho.com/recruit/developer-guide/apidocs/",
        "key_apis": ["Job posting", "Candidate tracking", "Interview scheduling", "Offer management"],
    },
    "Zoho Projects": {
        "category": "Project Management",
        "description": "Project planning and tracking with tasks, milestones, and Gantt charts.",
        "api": "https://www.zoho.com/projects/help/rest-api/overview.html",
        "key_apis": ["Project creation", "Task management", "Time logging", "Milestone tracking"],
    },
    "Zoho Sprints": {
        "category": "Project Management",
        "description": "Agile project management tool for scrum teams with sprint planning.",
        "api": "https://www.zoho.com/sprints/help/developer-guide/overview.html",
        "key_apis": ["Sprint planning", "Backlog management", "Story points", "Burndown charts"],
    },
    "Zoho Cliq": {
        "category": "Internal Communication",
        "description": "Team messaging and collaboration platform with channels and bots.",
        "api": "https://www.zoho.com/cliq/help/restapi/v2/",
        "key_apis": ["Message sending", "Channel management", "Bot creation", "File sharing"],
    },
    "Zoho Connect": {
        "category": "Internal Communication",
        "description": "Enterprise social network and intranet for company-wide communication.",
        "api": "https://www.zoho.com/connect/developer-guide/",
        "key_apis": ["Post creation", "Group management", "Forum discussions", "Event management"],
    },
    "Zoho Forms": {
        "category": "Customer Data Collection",
        "description": "Online form builder for data collection, surveys, and registrations.",
        "api": "https://www.zoho.com/forms/help/api/overview.html",
        "key_apis": ["Form submission", "Field mapping", "Conditional logic", "CRM integration"],
    },
    "Zoho Creator": {
        "category": "Custom Applications",
        "description": "Low-code platform for building custom business applications and workflows.",
        "api": "https://www.zoho.com/creator/help/api/v2/overview.html",
        "key_apis": ["App creation", "Form builder", "Report generation", "Custom workflows"],
    },
    "Zoho Catalyst": {
        "category": "Custom Applications",
        "description": "Serverless platform for building and deploying scalable cloud applications.",
        "api": "https://catalyst.zoho.com/help/api/v1/overview.html",
        "key_apis": ["Serverless functions", "Data store", "File store", "Authentication"],
    },
    "Zoho Flow": {
        "category": "Workflow Automation",
        "description": "Integration and workflow automation platform connecting Zoho and external apps.",
        "api": "https://www.zoho.com/flow/help/api/v1/overview.html",
        "key_apis": ["Trigger management", "Action configuration", "Data mapping", "Error handling"],
    },
    "Zoho WorkDrive": {
        "category": "Document Management",
        "description": "Cloud storage and document collaboration platform for teams.",
        "api": "https://workdrive.zoho.com/apidocs/v1/",
        "key_apis": ["File upload", "Folder management", "Permission control", "Version history"],
    },
    "Zoho Sign": {
        "category": "Document Management",
        "description": "Digital signature and document workflow automation platform.",
        "api": "https://www.zoho.com/sign/api/",
        "key_apis": ["Document sending", "Signature request", "Template management", "Audit trail"],
    },
    "Zoho Social": {
        "category": "Marketing Automation",
        "description": "Social media management and scheduling platform for marketing teams.",
        "api": "https://www.zoho.com/social/help/developer-guide.html",
        "key_apis": ["Post scheduling", "Brand monitoring", "Engagement tracking", "Report generation"],
    },
}


# ── Problem → Zoho Product Mapping Table ─────────────────────────────────────

ZOHO_MAPPING_TABLE: Dict[str, List[str]] = {
    "lead_management": ["Zoho CRM", "Zoho SalesIQ", "Zoho Campaigns"],
    "customer_support": ["Zoho Desk", "Zoho CRM", "Zoho Analytics"],
    "marketing_automation": ["Zoho Campaigns", "Zoho Social", "Zoho CRM"],
    "finance_accounting": ["Zoho Books", "Zoho Invoice", "Zoho Expense"],
    "inventory_management": ["Zoho Inventory", "Zoho Books", "Zoho Analytics"],
    "human_resource_management": ["Zoho People", "Zoho Recruit"],
    "project_management": ["Zoho Projects", "Zoho Sprints", "Zoho Analytics"],
    "internal_communication": ["Zoho Cliq", "Zoho Connect"],
    "data_analytics": ["Zoho Analytics"],
    "customer_data_collection": ["Zoho Forms", "Zoho CRM"],
    "custom_applications": ["Zoho Creator", "Zoho Catalyst"],
    "workflow_automation": ["Zoho Flow"],
    "document_management": ["Zoho WorkDrive", "Zoho Sign"],
    "sales_pipeline": ["Zoho CRM", "Zoho SalesIQ", "Zoho Analytics"],
    "billing_invoicing": ["Zoho Books", "Zoho Invoice", "Zoho Expense"],
    "ecommerce": ["Zoho Inventory", "Zoho Books", "Zoho CRM", "Zoho Campaigns"],
    "recruitment_hiring": ["Zoho Recruit", "Zoho People"],
    "employee_management": ["Zoho People", "Zoho Cliq", "Zoho Projects"],
    "reporting_dashboards": ["Zoho Analytics", "Zoho CRM"],
    "website_lead_capture": ["Zoho SalesIQ", "Zoho Forms", "Zoho CRM"],
    "email_marketing": ["Zoho Campaigns", "Zoho CRM"],
    "agile_development": ["Zoho Sprints", "Zoho Projects", "Zoho Cliq"],
    "digital_signature": ["Zoho Sign", "Zoho WorkDrive"],
    "expense_management": ["Zoho Expense", "Zoho Books"],
    "social_media_management": ["Zoho Social", "Zoho CRM", "Zoho Campaigns"],
}

# Keywords that map to workflow categories
KEYWORD_TO_WORKFLOW: Dict[str, str] = {
    # Lead / Sales
    "lead": "lead_management", "leads": "lead_management", "prospect": "lead_management",
    "sales pipeline": "sales_pipeline", "pipeline": "sales_pipeline",
    "sales": "lead_management", "crm": "lead_management",

    # Support
    "support": "customer_support", "helpdesk": "customer_support",
    "ticket": "customer_support", "customer service": "customer_support",
    "complaint": "customer_support",

    # Marketing
    "marketing": "marketing_automation", "campaign": "marketing_automation",
    "email marketing": "email_marketing", "newsletter": "email_marketing",
    "social media": "social_media_management", "social": "social_media_management",

    # Finance
    "finance": "finance_accounting", "accounting": "finance_accounting",
    "invoice": "billing_invoicing", "billing": "billing_invoicing",
    "expense": "expense_management", "payment": "billing_invoicing",
    "bookkeeping": "finance_accounting",

    # Inventory
    "inventory": "inventory_management", "stock": "inventory_management",
    "warehouse": "inventory_management", "order": "inventory_management",
    "ecommerce": "ecommerce", "online store": "ecommerce",

    # HR
    "hr": "human_resource_management", "human resource": "human_resource_management",
    "employee": "employee_management", "payroll": "human_resource_management",
    "recruit": "recruitment_hiring", "hiring": "recruitment_hiring",
    "onboarding": "human_resource_management", "attendance": "human_resource_management",
    "leave": "human_resource_management",

    # Project
    "project": "project_management", "task": "project_management",
    "milestone": "project_management", "gantt": "project_management",
    "agile": "agile_development", "scrum": "agile_development", "sprint": "agile_development",

    # Communication
    "communication": "internal_communication", "chat": "internal_communication",
    "messaging": "internal_communication", "collaboration": "internal_communication",
    "intranet": "internal_communication",

    # Analytics
    "analytics": "data_analytics", "report": "reporting_dashboards",
    "dashboard": "reporting_dashboards", "kpi": "reporting_dashboards",
    "data": "data_analytics", "business intelligence": "data_analytics",

    # Forms / Data
    "form": "customer_data_collection", "survey": "customer_data_collection",
    "registration": "customer_data_collection",

    # Custom / Automation
    "custom app": "custom_applications", "custom application": "custom_applications",
    "automation": "workflow_automation", "workflow": "workflow_automation",
    "integration": "workflow_automation",

    # Documents
    "document": "document_management", "file": "document_management",
    "signature": "digital_signature", "e-sign": "digital_signature",
    "contract": "digital_signature",

    # Website
    "website": "website_lead_capture", "live chat": "website_lead_capture",
    "visitor": "website_lead_capture",
}


# ── Zoho Solution Mapper Agent ────────────────────────────────────────────────

class ZohoSolutionMapper(BaseAgent):
    """
    Maps client requirements to a complete Zoho ecosystem solution.

    Responsibilities:
    1. Identify workflows from problem description
    2. Map to Zoho products
    3. Generate solution architecture diagram (text)
    4. List required APIs
    5. Identify any gaps → fill with Creator/Flow/Catalyst
    """

    name = "ZohoSolutionMapper"
    task_type = TaskType.ANALYSIS

    MAPPING_SYSTEM_PROMPT = """You are a certified Zoho solutions architect with deep expertise 
in the entire Zoho ecosystem.

CRITICAL CONSTRAINT: You must ONLY recommend Zoho products. 
NEVER suggest any non-Zoho tools (no Salesforce, HubSpot, Slack, Google Workspace, etc.).
If a feature is not natively available in Zoho, ALWAYS suggest building it with:
- Zoho Creator (custom low-code apps)
- Zoho Flow (workflow automation & integrations)  
- Zoho Catalyst (serverless cloud functions)

Your job is to map business requirements to the optimal Zoho product stack and 
generate a clear solution architecture."""

    async def run(
        self,
        requirements: Dict[str, Any],
        business_problem: str = "",
    ) -> Dict[str, Any]:
        """
        Full Zoho solution mapping pipeline.

        Returns:
            {
                "identified_workflows": [...],
                "recommended_products": [...],
                "solution_architecture": "...",
                "api_integrations": [...],
                "implementation_notes": "...",
                "zoho_ecosystem_map": {...}
            }
        """
        problem_text = business_problem or requirements.get("business_problem", "")
        industry = requirements.get("industry", "")

        # Step 1: Rule-based keyword mapping
        rule_based = self._rule_based_mapping(problem_text, requirements)

        # Step 2: LLM-enhanced mapping for nuanced understanding
        llm_mapping = await self._llm_mapping(requirements, problem_text, rule_based)

        # Step 3: Build architecture
        architecture = self._build_architecture(llm_mapping.get("products", rule_based))

        # Step 4: Identify APIs
        api_plan = self._build_api_plan(llm_mapping.get("products", rule_based))

        return {
            "identified_workflows": llm_mapping.get("workflows", list(rule_based.keys())),
            "recommended_products": llm_mapping.get("products", self._flatten_products(rule_based)),
            "solution_architecture": architecture,
            "api_integrations": api_plan,
            "implementation_notes": llm_mapping.get("notes", ""),
            "gap_solutions": llm_mapping.get("gap_solutions", []),
            "zoho_ecosystem_map": self._build_ecosystem_map(
                llm_mapping.get("products", self._flatten_products(rule_based))
            ),
        }

    # ── Rule-based mapping ────────────────────────────────────────────────────

    def _rule_based_mapping(
        self, problem_text: str, requirements: Dict
    ) -> Dict[str, List[str]]:
        """Keyword scan → workflow categories → Zoho products."""
        text = problem_text.lower()

        # Also scan current_tools for context
        current_tools = requirements.get("current_tools", [])
        if current_tools:
            text += " " + " ".join(str(t).lower() for t in current_tools)

        found_workflows: Dict[str, List[str]] = {}

        for keyword, workflow in KEYWORD_TO_WORKFLOW.items():
            if keyword in text:
                if workflow not in found_workflows:
                    products = ZOHO_MAPPING_TABLE.get(workflow, [])
                    if products:
                        found_workflows[workflow] = products

        # Default fallback — always include CRM for business problems
        if not found_workflows:
            found_workflows["lead_management"] = ZOHO_MAPPING_TABLE["lead_management"]

        return found_workflows

    def _flatten_products(self, workflow_map: Dict[str, List[str]]) -> List[str]:
        """Deduplicated flat list of products from workflow map."""
        seen = []
        for products in workflow_map.values():
            for p in products:
                if p not in seen:
                    seen.append(p)
        return seen

    # ── LLM-enhanced mapping ──────────────────────────────────────────────────

    async def _llm_mapping(
        self,
        requirements: Dict,
        problem_text: str,
        rule_based: Dict,
    ) -> Dict:
        """Use LLM for deeper, context-aware Zoho mapping."""

        available_products = "\n".join(
            f"- {name}: {info['description']}"
            for name, info in ZOHO_PRODUCTS.items()
        )

        rule_based_suggestion = json.dumps(
            {wf: prods for wf, prods in rule_based.items()}, indent=2
        )

        prompt = f"""Analyze this client's business requirements and map them to the optimal Zoho solution.

CLIENT REQUIREMENTS:
{json.dumps(requirements, indent=2)}

BUSINESS PROBLEM:
{problem_text}

RULE-BASED SUGGESTION (use as starting point, improve where needed):
{rule_based_suggestion}

AVAILABLE ZOHO PRODUCTS:
{available_products}

STRICT RULE: ONLY recommend products from the Zoho ecosystem listed above.
For any capability gap, use Zoho Creator, Zoho Flow, or Zoho Catalyst.
NEVER suggest non-Zoho products.

Return ONLY valid JSON:
{{
  "workflows": ["identified workflow 1", "workflow 2"],
  "products": ["Zoho CRM", "Zoho Desk"],
  "product_details": [
    {{
      "name": "Zoho CRM",
      "role": "why this product is needed",
      "priority": "primary|secondary"
    }}
  ],
  "gap_solutions": [
    {{
      "gap": "describe any capability not covered by standard Zoho products",
      "solution": "Zoho Creator|Zoho Flow|Zoho Catalyst",
      "approach": "how to build it"
    }}
  ],
  "notes": "overall solution notes and recommendations"
}}"""

        raw = await self._generate(
            prompt=prompt,
            system_prompt=self.MAPPING_SYSTEM_PROMPT,
            task_type=TaskType.ANALYSIS,
        )

        return self._parse_json(raw) or {}

    # ── Architecture builder ──────────────────────────────────────────────────

    def _build_architecture(self, products: List[str]) -> str:
        """
        Build a text-based solution architecture diagram showing
        how Zoho products connect and interact.
        """
        if not products:
            return "No products mapped."

        # Define canonical data flow order
        FLOW_ORDER = [
            "Zoho SalesIQ",
            "Zoho Forms",
            "Zoho Campaigns",
            "Zoho Social",
            "Zoho CRM",
            "Zoho Desk",
            "Zoho Projects",
            "Zoho Sprints",
            "Zoho People",
            "Zoho Recruit",
            "Zoho Inventory",
            "Zoho Books",
            "Zoho Invoice",
            "Zoho Expense",
            "Zoho Flow",
            "Zoho Creator",
            "Zoho Catalyst",
            "Zoho WorkDrive",
            "Zoho Sign",
            "Zoho Cliq",
            "Zoho Connect",
            "Zoho Analytics",
        ]

        # Filter to only selected products, maintain flow order
        ordered = [p for p in FLOW_ORDER if p in products]
        # Add any products not in order list at the end
        for p in products:
            if p not in ordered:
                ordered.append(p)

        if not ordered:
            return "No architecture to display."

        lines = ["CLIENT / WEBSITE TOUCHPOINT"]
        lines.append("         │")

        for i, product in enumerate(ordered):
            info = ZOHO_PRODUCTS.get(product, {})
            role = info.get("description", "")[:60]
            lines.append(f"  ┌──────────────────────────────────────┐")
            lines.append(f"  │  {product:<36}│")
            lines.append(f"  │  {role:<36}│")
            lines.append(f"  └──────────────────────────────────────┘")
            if i < len(ordered) - 1:
                lines.append("         │")

        lines.append("         │")
        lines.append("  ┌──────────────────────────────────────┐")
        lines.append("  │  Zoho Analytics                      │")
        lines.append("  │  Unified Reporting & Dashboards       │")
        lines.append("  └──────────────────────────────────────┘")

        return "\n".join(lines)

    # ── API plan builder ──────────────────────────────────────────────────────

    def _build_api_plan(self, products: List[str]) -> List[Dict[str, str]]:
        """Build a list of API integration points for selected products."""
        api_plan = []
        for product in products:
            info = ZOHO_PRODUCTS.get(product)
            if info and info.get("api"):
                api_plan.append({
                    "product": product,
                    "api_endpoint": info["api"],
                    "key_operations": info.get("key_apis", []),
                    "documentation": info["api"],
                })
        return api_plan

    # ── Ecosystem map ─────────────────────────────────────────────────────────

    def _build_ecosystem_map(self, products: List[str]) -> Dict[str, List[str]]:
        """Group products by category for the proposal."""
        category_map: Dict[str, List[str]] = {}
        for product in products:
            info = ZOHO_PRODUCTS.get(product, {})
            category = info.get("category", "Other")
            if category not in category_map:
                category_map[category] = []
            category_map[category].append(product)
        return category_map

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_json(self, raw: str):
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

    def quick_map(self, problem_text: str) -> List[str]:
        """
        Fast synchronous keyword-based mapping.
        Returns flat list of recommended Zoho products.
        Used for inline hints during conversation.
        """
        result = self._rule_based_mapping(problem_text, {})
        return self._flatten_products(result)
