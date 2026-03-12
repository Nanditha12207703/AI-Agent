"""
agents/orchestrator.py
-----------------------
The central agent orchestrator.

Coordinates: ConversationAgent → RequirementAgent → LeadScoringAgent
             DocumentAgent → ProposalAgent → Memory

One Orchestrator instance per session (or stateless with injected memory).
"""

import time
from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from agents.conversation_agent import ConversationAgent
from agents.requirement_agent import RequirementAgent
from agents.lead_scoring_agent import LeadScoringAgent
from agents.proposal_agent import ProposalAgent
from agents.document_agent import DocumentAgent
from agents.zoho_mapper import ZohoSolutionMapper
from database import crud
from database.models import MessageRole
from memory.memory_manager import get_memory, MemoryManager
from proposal_engine.generator import ProposalPDFGenerator
from loguru import logger


# Phrase that signals the agent has enough info for a proposal
PROPOSAL_TRIGGER = "I have enough information to prepare a tailored proposal"
PROPOSAL_RESPONSE = "Proposal generated successfully."


class AgentOrchestrator:
    """
    Stateless orchestrator - receives session context on each call.
    All state lives in DB + MemoryManager.
    """

    def __init__(self):
        self.conv_agent = ConversationAgent()
        self.req_agent = RequirementAgent()
        self.score_agent = LeadScoringAgent()
        self.proposal_agent = ProposalAgent()
        self.doc_agent = DocumentAgent()
        self.zoho_mapper = ZohoSolutionMapper()
        self.pdf_gen = ProposalPDFGenerator()

    # ── Main chat handler ─────────────────────────────────────────────────────

    async def chat(
        self,
        db: AsyncSession,
        user_id: str,
        session_id: str,
        user_message: str,
        message_type: str = "text",
    ) -> Dict[str, Any]:
        """
        Process a user message and return the agent's response.

        Returns:
            {
                "response": str,
                "proposal_generated": bool,
                "proposal_id": str | None,
                "requirements_complete": bool,
                "lead_score": dict | None,
            }
        """
        t0 = time.time()
        memory: MemoryManager = get_memory(session_id, user_id)

        # 1. Persist user message
        await crud.add_message(
            db, session_id, MessageRole.USER, user_message, message_type
        )
        memory.remember("user", user_message)

        # 2. Load existing requirements
        req_record = await crud.get_requirements(db, session_id)
        requirements = self._req_to_dict(req_record) if req_record else {}

        # 3. Load session context summary
        session = await crud.get_session(db, session_id, user_id)
        context_summary = session.context_summary if session else None

        # 4. Get conversation history
        history = memory.get_recent_context()

        # 5. Generate conversational response
        response = await self.conv_agent.run(
            user_message=user_message,
            conversation_history=history,
            requirements_so_far=requirements,
            context_summary=context_summary,
        )

        # 6. Periodically extract requirements (every 3 user messages)
        msg_count = len([m for m in history if m["role"] == "user"])
        if msg_count % 3 == 0 or msg_count == 1:
            requirements = await self._update_requirements(
                db, session_id, user_id, history + [{"role": "user", "content": user_message}],
                requirements
            )

        # 7. Check if proposal should be triggered
        proposal_triggered = PROPOSAL_TRIGGER.lower() in response.lower()
        proposal_id = None
        lead_score_data = None

        if proposal_triggered or requirements.get("is_complete"):
            proposal_id, lead_score_data = await self._generate_proposal_flow(
                db, user_id, session_id, requirements, memory
            )
            if proposal_id:
                response = PROPOSAL_RESPONSE

        # 8. Persist agent message
        await crud.add_message(
            db, session_id, MessageRole.ASSISTANT, response, "text"
        )
        memory.remember("assistant", response)

        # 9. Update session title on first exchange
        if msg_count == 0 and session and session.title == "New Conversation":
            title = self._generate_title(user_message)
            await crud.update_session_title(db, session_id, title)

        elapsed = int((time.time() - t0) * 1000)
        logger.info(f"Chat processed in {elapsed}ms")

        return {
            "response": response,
            "proposal_generated": bool(proposal_id),
            "proposal_id": proposal_id,
            "requirements_complete": requirements.get("is_complete", False),
            "requirements_completeness": requirements.get("completeness_score", 0.0),
            "lead_score": lead_score_data,
            "session_id": session_id,
        }

    # ── Document upload handler ───────────────────────────────────────────────

    async def process_document(
        self,
        db: AsyncSession,
        user_id: str,
        session_id: str,
        file_path: str,
        filename: str,
    ) -> Dict[str, Any]:
        """Process an uploaded document and inject it into the conversation."""
        memory = get_memory(session_id, user_id)

        # Extract + summarize + requirements
        req_record = await crud.get_requirements(db, session_id)
        existing_req = self._req_to_dict(req_record) if req_record else {}

        summary, context_msg, doc_requirements = await self.doc_agent.run(
            file_path=file_path,
            filename=filename,
            existing_requirements=existing_req,
        )

        # Merge extracted requirements into DB
        merged = {**existing_req, **{
            k: v for k, v in doc_requirements.items()
            if v and k not in ("completeness_score", "is_complete")
        }}
        if merged:
            await crud.upsert_requirements(db, session_id, user_id, merged)

        # Add to conversation history as a "document" message
        await crud.add_message(
            db, session_id, MessageRole.USER,
            f"[Document uploaded: {filename}]",
            message_type="document",
            source_file=filename,
        )
        await crud.add_message(
            db, session_id, MessageRole.ASSISTANT,
            context_msg, message_type="text"
        )
        memory.remember("user", f"[Uploaded document: {filename}]")
        memory.remember("assistant", context_msg)

        return {
            "message": context_msg,
            "summary": summary,
            "requirements_extracted": doc_requirements,
            "session_id": session_id,
        }

    # ── Manual proposal trigger ───────────────────────────────────────────────

    async def generate_proposal(
        self,
        db: AsyncSession,
        user_id: str,
        session_id: str,
    ) -> Dict[str, Any]:
        """Manually trigger proposal generation."""
        memory = get_memory(session_id, user_id)
        req_record = await crud.get_requirements(db, session_id)
        requirements = self._req_to_dict(req_record) if req_record else {}

        proposal_id, lead_score = await self._generate_proposal_flow(
            db, user_id, session_id, requirements, memory
        )

        return {
            "status": "success",
            "message": PROPOSAL_RESPONSE,
            "proposal_id": proposal_id,
            "lead_score": lead_score,
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _update_requirements(
        self,
        db: AsyncSession,
        session_id: str,
        user_id: str,
        history: List[Dict],
        existing: Dict,
    ) -> Dict:
        """Run RequirementAgent and persist results."""
        extracted = await self.req_agent.run(history, existing)
        data = {k: v for k, v in extracted.items()
                if k not in ("completeness_score", "is_complete")}
        if data:
            await crud.upsert_requirements(db, session_id, user_id, {
                **data,
                "completeness_score": extracted.get("completeness_score", 0),
                "is_complete": extracted.get("is_complete", False),
            })
        return extracted

    async def _generate_proposal_flow(
        self,
        db: AsyncSession,
        user_id: str,
        session_id: str,
        requirements: Dict,
        memory: MemoryManager,
    ) -> Tuple[Optional[str], Optional[Dict]]:
        """Full proposal generation + scoring + PDF + DB persistence."""
        t0 = time.time()

        # 1. Fetch similar past proposals from vector memory
        query = requirements.get("business_problem", "enterprise solution")
        industry = requirements.get("industry")
        similar = memory.retrieve_similar_proposals(query, industry=industry)

        # 2. Get existing proposals to determine version number
        existing_proposals = await crud.get_session_proposals(db, session_id)
        if existing_proposals:
            proposal_record = existing_proposals[0]
            version_number = proposal_record.current_version + 1
        else:
            proposal_record = None
            version_number = 1

        # 3. Run Zoho solution mapping
        zoho_mapping = await self.zoho_mapper.run(
            requirements=requirements,
            business_problem=requirements.get("business_problem", ""),
        )
        logger.info(f"Zoho mapping complete: {zoho_mapping.get('recommended_products', [])}")

        # 4. Generate proposal content (with Zoho mapping)
        content = await self.proposal_agent.run(
            requirements=requirements,
            similar_proposals=similar,
            version=version_number,
            zoho_mapping=zoho_mapping,
        )

        # 5. Generate PDF (stored server-side only)
        company = requirements.get("company_name", "Client")
        pdf_filename = f"proposal_{company.lower().replace(' ', '_')}_v{version_number}.pdf"
        pdf_path = await self.pdf_gen.generate(
            content=content,
            requirements=requirements,
            filename=pdf_filename,
        )

        # 6. Create or update proposal record
        if not proposal_record:
            proposal_record = await crud.create_proposal(
                db, user_id, session_id,
                title=f"Proposal for {company}",
                content=content,
            )

        # 7. Save proposal version
        elapsed_ms = int((time.time() - t0) * 1000)
        await crud.add_proposal_version(
            db,
            proposal_id=proposal_record.id,
            version_number=version_number,
            pdf_path=pdf_path,
            pdf_filename=pdf_filename,
            content_snapshot=content,
            requirements_snapshot=requirements,
            model_used=f"gemini-pro",
            generation_time_ms=elapsed_ms,
            change_summary=(
                "Initial proposal" if version_number == 1
                else f"Updated requirements – v{version_number}"
            ),
        )

        # 8. Lead scoring
        lead_score_data = await self.score_agent.run(
            requirements=requirements,
            conversation_signals=f"Requirements completeness: {requirements.get('completeness_score', 0):.0%}",
        )
        await crud.upsert_lead(db, user_id, session_id, {
            "company_name": requirements.get("company_name"),
            "industry": requirements.get("industry"),
            "score": lead_score_data.get("score", 0),
            "qualification": lead_score_data.get("qualification", "cold"),
            "conversion_probability": lead_score_data.get("conversion_probability", "Low"),
            "score_breakdown": lead_score_data,
        })

        # 9. Store in vector memory for future learning
        proposal_text = str(content.get("executive_summary", "")) + " " + str(content)
        memory.store_proposal_memory(
            proposal_id=proposal_record.id,
            content=proposal_text[:2000],
            industry=requirements.get("industry"),
            company=requirements.get("company_name"),
        )

        logger.info(f"Proposal v{version_number} generated in {elapsed_ms}ms")
        return proposal_record.id, lead_score_data

    def _req_to_dict(self, req) -> Dict:
        if not req:
            return {}
        return {
            "industry": req.industry,
            "company_name": req.company_name,
            "business_problem": req.business_problem,
            "current_tools": req.current_tools or [],
            "required_integrations": req.required_integrations or [],
            "budget": req.budget,
            "timeline": req.timeline,
            "constraints": req.constraints,
            "completeness_score": req.completeness_score,
            "is_complete": req.is_complete,
        }

    def _generate_title(self, first_message: str) -> str:
        words = first_message.strip().split()[:6]
        return " ".join(words).capitalize()[:60]


# ── Singleton ─────────────────────────────────────────────────────────────────

_orchestrator: Optional[AgentOrchestrator] = None


def get_orchestrator() -> AgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator()
    return _orchestrator
