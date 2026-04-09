"""
agents/orchestrator.py
-----------------------
The central agent orchestrator.

Coordinates: ConversationAgent → RequirementAgent → LeadScoringAgent
             DocumentAgent → ProposalAgent → Memory

Rewritten to use database.connection functions (merged crud layer).
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
from database.connection import (
    add_message, get_session, get_session_messages,
    create_proposal, add_proposal_version, get_client_proposals,
    update_client_analytics, update_session_requirements,
)
from database.models import MessageRole, EngagementLevel
from memory.memory_manager import get_memory, MemoryManager
from proposal_engine.generator import ProposalPDFGenerator
from loguru import logger


PROPOSAL_TRIGGER = "I have enough information to prepare a tailored proposal"
PROPOSAL_RESPONSE = "Proposal generated successfully."


class AgentOrchestrator:
    def __init__(self):
        self.conv_agent = ConversationAgent()
        self.req_agent = RequirementAgent()
        self.score_agent = LeadScoringAgent()
        self.proposal_agent = ProposalAgent()
        self.doc_agent = DocumentAgent()
        self.zoho_mapper = ZohoSolutionMapper()
        self.pdf_gen = ProposalPDFGenerator()

    async def chat(
        self,
        db: AsyncSession,
        client_id: str,
        session_id: str,
        user_message: str,
        message_type: str = "text",
    ) -> Dict[str, Any]:
        t0 = time.time()
        memory: MemoryManager = get_memory(session_id, client_id)

        await add_message(db, session_id, MessageRole.USER, user_message, message_type)
        memory.remember("user", user_message)

        session = await get_session(db, session_id)
        requirements = (session.requirements_json or {}) if session else {}
        context_summary = session.context_summary if session else None

        history = memory.get_recent_context()

        response = await self.conv_agent.run(
            user_message=user_message,
            conversation_history=history,
            requirements_so_far=requirements,
            context_summary=context_summary,
        )

        msg_count = len([m for m in history if m["role"] == "user"])
        if msg_count % 3 == 0 or msg_count == 1:
            requirements = await self._update_requirements(
                db, session_id,
                history + [{"role": "user", "content": user_message}],
                requirements,
            )

        proposal_triggered = PROPOSAL_TRIGGER.lower() in response.lower()
        proposal_id = None
        lead_score_data = None

        if proposal_triggered or requirements.get("is_complete"):
            proposal_id, lead_score_data = await self._generate_proposal_flow(
                db, client_id, session_id, requirements, memory
            )
            if proposal_id:
                response = PROPOSAL_RESPONSE

        await add_message(db, session_id, MessageRole.ASSISTANT, response, "text")
        memory.remember("assistant", response)

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

    async def process_document(
        self,
        db: AsyncSession,
        client_id: str,
        session_id: str,
        file_path: str,
        filename: str,
    ) -> Dict[str, Any]:
        memory = get_memory(session_id, client_id)

        session = await get_session(db, session_id)
        existing_req = (session.requirements_json or {}) if session else {}

        summary, context_msg, doc_requirements = await self.doc_agent.run(
            file_path=file_path,
            filename=filename,
            existing_requirements=existing_req,
        )

        merged = {**existing_req, **{
            k: v for k, v in doc_requirements.items()
            if v and k not in ("completeness_score", "is_complete")
        }}
        if merged:
            await update_session_requirements(db, session_id, merged)

        await add_message(
            db, session_id, MessageRole.USER,
            f"[Document uploaded: {filename}]",
            message_type="document",
            source_file=filename,
        )
        await add_message(db, session_id, MessageRole.ASSISTANT, context_msg, "text")
        memory.remember("user", f"[Uploaded document: {filename}]")
        memory.remember("assistant", context_msg)

        return {
            "message": context_msg,
            "summary": summary,
            "requirements_extracted": doc_requirements,
            "session_id": session_id,
        }

    async def generate_proposal(
        self,
        db: AsyncSession,
        client_id: str,
        session_id: str,
    ) -> Dict[str, Any]:
        memory = get_memory(session_id, client_id)
        session = await get_session(db, session_id)
        requirements = (session.requirements_json or {}) if session else {}

        proposal_id, lead_score = await self._generate_proposal_flow(
            db, client_id, session_id, requirements, memory
        )

        return {
            "status": "success",
            "message": PROPOSAL_RESPONSE,
            "proposal_id": proposal_id,
            "lead_score": lead_score,
        }

    async def _update_requirements(
        self,
        db: AsyncSession,
        session_id: str,
        history: List[Dict],
        existing: Dict,
    ) -> Dict:
        extracted = await self.req_agent.run(history, existing)
        data = {k: v for k, v in extracted.items()
                if k not in ("completeness_score", "is_complete")}
        if data:
            merged = {
                **data,
                "completeness_score": extracted.get("completeness_score", 0),
                "is_complete": extracted.get("is_complete", False),
            }
            is_complete = extracted.get("is_complete", False)
            await update_session_requirements(db, session_id, merged, complete=is_complete)
        return extracted

    async def _generate_proposal_flow(
        self,
        db: AsyncSession,
        client_id: str,
        session_id: str,
        requirements: Dict,
        memory: MemoryManager,
    ) -> Tuple[Optional[str], Optional[Dict]]:
        t0 = time.time()

        query = requirements.get("business_problem", "enterprise solution")
        industry = requirements.get("industry")
        similar = memory.retrieve_similar_proposals(query, industry=industry)

        existing_proposals = await get_client_proposals(db, client_id)
        if existing_proposals:
            proposal_record = existing_proposals[0]
            version_number = proposal_record.current_version + 1
        else:
            proposal_record = None
            version_number = 1

        zoho_mapping = await self.zoho_mapper.run(
            requirements=requirements,
            business_problem=requirements.get("business_problem", ""),
        )
        logger.info(f"Zoho mapping complete: {zoho_mapping.get('recommended_products', [])}")

        content = await self.proposal_agent.run(
            requirements=requirements,
            similar_proposals=similar,
            version=version_number,
            zoho_mapping=zoho_mapping,
        )

        company = requirements.get("company_name", "Client")
        pdf_filename = f"proposal_{company.lower().replace(' ', '_')}_v{version_number}.pdf"
        pdf_path = await self.pdf_gen.generate(
            content=content,
            requirements=requirements,
            filename=pdf_filename,
        )

        if not proposal_record:
            proposal_record = await create_proposal(
                db, client_id, session_id,
                title=f"Proposal for {company}",
                content=content,
            )

        elapsed_ms = int((time.time() - t0) * 1000)
        await add_proposal_version(
            db,
            proposal_id=proposal_record.id,
            version_number=version_number,
            pdf_path=pdf_path,
            pdf_filename=pdf_filename,
            content_snapshot=content,
            requirements_snapshot=requirements,
            model_used="gemini-pro",
            generation_time_ms=elapsed_ms,
            change_summary=(
                "Initial proposal" if version_number == 1
                else f"Updated requirements – v{version_number}"
            ),
        )

        lead_score_data = await self.score_agent.run(
            requirements=requirements,
            conversation_signals=f"Requirements completeness: {requirements.get('completeness_score', 0):.0%}",
        )

        score = lead_score_data.get("score", 0)
        prob = lead_score_data.get("conversion_probability_float", 0.0)
        engagement = EngagementLevel.HIGH if score >= 70 else (
            EngagementLevel.MODERATE if score >= 40 else EngagementLevel.LOW
        )
        await update_client_analytics(
            db, client_id,
            lead_score=score,
            closing_probability=prob,
            engagement_level=engagement,
            lead_score_breakdown=lead_score_data,
        )

        proposal_text = str(content.get("executive_summary", "")) + " " + str(content)
        memory.store_proposal_memory(
            proposal_id=proposal_record.id,
            content=proposal_text[:2000],
            industry=requirements.get("industry"),
            company=requirements.get("company_name"),
        )

        logger.info(f"Proposal v{version_number} generated in {elapsed_ms}ms")
        return proposal_record.id, lead_score_data

    def _generate_title(self, first_message: str) -> str:
        words = first_message.strip().split()[:6]
        return " ".join(words).capitalize()[:60]


_orchestrator: Optional[AgentOrchestrator] = None


def get_orchestrator() -> AgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator()
    return _orchestrator
