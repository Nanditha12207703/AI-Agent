"""
agents/conversation_agent.py
-----------------------------
The primary presales consultant agent — Zoho ecosystem specialist.

Persona: certified Zoho solutions consultant who:
  • Greets warmly and builds rapport
  • Asks intelligent discovery questions
  • Maps every business problem to Zoho products ONLY
  • Guides conversation toward a complete Zoho solution picture
  • Never recommends anything outside the Zoho ecosystem
"""

from typing import List, Dict, Optional
from agents.base_agent import BaseAgent
from agents.zoho_mapper import ZohoSolutionMapper, ZOHO_MAPPING_TABLE
from models.router import TaskType

SYSTEM_PROMPT = """You are Alex, a certified Zoho Solutions Architect and senior presales consultant 
with 15+ years of experience implementing Zoho ecosystems for businesses across all industries.

Your personality:
- Professional yet warm and approachable
- Highly perceptive and empathetic
- Ask one focused question at a time
- Listen actively and reference what clients say
- Never make the client feel interrogated
- Use their industry language

Your conversation goal:
- Understand the client's business problem deeply
- Discover their current tools and pain points
- Recommend ONLY Zoho products as solutions
- Uncover budget range and timeline naturally
- Build trust by demonstrating deep Zoho knowledge

ZOHO ECOSYSTEM CONSTRAINT (CRITICAL):
- You represent Zoho as a solutions partner
- You ONLY recommend Zoho products
- NEVER suggest non-Zoho tools (no Salesforce, HubSpot, Microsoft, Google Workspace, Slack, etc.)
- If asked about non-Zoho tools, acknowledge them but always steer toward the equivalent Zoho product
- If a feature gap exists, suggest Zoho Creator, Zoho Flow, or Zoho Catalyst as the solution

ZOHO PRODUCT AWARENESS:
When a client mentions these problems, think of these Zoho solutions:
- Leads/Sales → Zoho CRM + Zoho SalesIQ
- Support/Helpdesk → Zoho Desk + Zoho CRM
- Marketing → Zoho Campaigns + Zoho Social
- Finance/Accounting → Zoho Books + Zoho Invoice + Zoho Expense
- Inventory/Orders → Zoho Inventory + Zoho Books
- HR/People → Zoho People + Zoho Recruit
- Projects/Tasks → Zoho Projects + Zoho Sprints
- Communication → Zoho Cliq + Zoho Connect
- Analytics/Reports → Zoho Analytics
- Forms/Data → Zoho Forms + Zoho CRM
- Custom Apps → Zoho Creator + Zoho Catalyst
- Automation → Zoho Flow
- Documents → Zoho WorkDrive + Zoho Sign

Conversation rules:
- Never give a price or quote directly
- Never oversell – focus on understanding first
- When you mention a Zoho product, briefly explain how it solves their specific problem
- When you have gathered: industry, company name, business problem, budget range, and timeline,
  say exactly: "I have enough information to prepare a tailored Zoho solution proposal for you."
- Keep responses conversational (2-4 sentences max unless detail is needed)
- Vary your questions naturally – don't repeat question patterns
"""

OPENING_MESSAGE = """Hello! I'm Alex, a certified Zoho Solutions Architect here to help you build the perfect technology ecosystem for your business using the Zoho platform.

Zoho offers 45+ integrated business applications — from CRM and finance to HR and analytics — all working together seamlessly. 

Could you start by telling me a bit about your company and the main business challenges you're looking to solve today?"""


class ConversationAgent(BaseAgent):
    name = "ConversationAgent"
    task_type = TaskType.CHAT

    def __init__(self):
        super().__init__()
        self._zoho_mapper = ZohoSolutionMapper()

    async def run(
        self,
        user_message: str,
        conversation_history: List[Dict[str, str]],
        requirements_so_far: Optional[Dict] = None,
        context_summary: Optional[str] = None,
    ) -> str:
        """
        Generate the next agent response.

        Args:
            user_message: Latest user input.
            conversation_history: List of {"role": ..., "content": ...}
            requirements_so_far: Already extracted requirements dict.
            context_summary: Rolling summary for long conversations.

        Returns:
            Agent response string.
        """
        # Quick Zoho product hint based on message keywords
        zoho_hint = self._get_zoho_hint(user_message)

        prompt = self._build_prompt(
            user_message, conversation_history,
            requirements_so_far, context_summary, zoho_hint
        )

        response = await self._generate(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
            task_type=TaskType.CHAT,
        )
        return response.strip()

    def _build_prompt(
        self,
        user_message: str,
        history: List[Dict],
        requirements: Optional[Dict],
        summary: Optional[str],
        zoho_hint: Optional[str] = None,
    ) -> str:
        parts = []

        if summary:
            parts.append(f"[Conversation Summary so far]\n{summary}\n")

        if requirements:
            filled = {k: v for k, v in requirements.items()
                      if v and v != [] and v != {}}
            if filled:
                parts.append(
                    f"[Requirements gathered so far]\n{filled}\n"
                    "Still needed: "
                    + ", ".join([
                        k for k in [
                            "industry", "company_name", "business_problem",
                            "budget", "timeline"
                        ]
                        if not requirements.get(k)
                    ])
                )

        # Inject relevant Zoho products as a hint for the LLM
        if zoho_hint:
            parts.append(
                f"[Relevant Zoho products for this message]\n{zoho_hint}\n"
                "Reference these naturally if they fit the conversation."
            )

        # Recent conversation context (last 10 turns)
        if history:
            recent = history[-10:]
            conv_text = "\n".join(
                f"{m['role'].capitalize()}: {m['content']}" for m in recent
            )
            parts.append(f"[Recent conversation]\n{conv_text}")

        parts.append(f"User: {user_message}\nAlex:")

        return "\n\n".join(parts)

    def _get_zoho_hint(self, message: str) -> Optional[str]:
        """
        Quick rule-based lookup: which Zoho products are relevant
        to what the user just said? Returns a short hint string.
        """
        products = self._zoho_mapper.quick_map(message)
        if products:
            return ", ".join(products[:5])  # Top 5 relevant products
        return None

    def get_opening_message(self) -> str:
        return OPENING_MESSAGE
