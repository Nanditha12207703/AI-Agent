"""
services/chat_service.py
------------------------
Bridges the client-facing chat to the existing Zoho presales AI agents.
Handles: conversation flow, requirement confirmation step, proposal generation.
"""

import sys
import os
import time
from typing import Dict, Any, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

# Import from the copied agent modules
from agents.conversation_agent import ConversationAgent
from agents.requirement_agent import RequirementAgent
from agents.proposal_agent import ProposalAgent
from agents.zoho_mapper import ZohoSolutionMapper
from agents.document_agent import DocumentAgent
from memory.memory_manager import get_memory, MemoryManager
from proposal_engine.generator import ProposalPDFGenerator
from services.analytics import analytics_engine

from database.connection import (
    get_client, get_session, add_message, update_session_requirements,
    update_session_confirmation, create_proposal, add_proposal_version,
    advance_client_stage, update_client_analytics, update_client_status,
    create_client_session, get_client_sessions
)
from database.models import (
    MessageRole, TrackingStage, ClientStatus, EngagementLevel
)
from config.settings import settings

# Confirmation UI trigger phrase
REQUIREMENTS_COMPLETE_TRIGGER = "I have enough information to prepare a tailored Zoho solution proposal for you."
PROPOSAL_RESPONSE = "Proposal generated successfully."

# Confirmation prompt shown to client
CONFIRMATION_PROMPT = """Based on our conversation, here's a summary of your requirements:

{summary}

Does this accurately capture your business needs?"""


class ChatService:
    """Manages the full client chat lifecycle."""

    def __init__(self):
        self.conv_agent = ConversationAgent()
        self.req_agent = RequirementAgent()
        self.proposal_agent = ProposalAgent()
        self.zoho_mapper = ZohoSolutionMapper()
        self.doc_agent = DocumentAgent()
        self.pdf_gen = ProposalPDFGenerator()

    async def handle_message(
        self,
        db: AsyncSession,
        client_id: str,
        session_id: str,
        user_message: str,
        message_type: str = "text",
    ) -> Dict[str, Any]:
        """
        Main message handler. Returns agent response + state info.
        """
        t0 = time.time()
        memory: MemoryManager = get_memory(session_id, client_id)

        # Persist user message
        await add_message(db, session_id, MessageRole.USER, user_message, message_type)
        memory.remember("user", user_message)

        # Load session state
        session = await get_session(db, session_id)
        if not session:
            return {"response": "Session not found.", "error": True}

        requirements = session.requirements_json or {}
        history = memory.get_recent_context()

        # ── STATE: Awaiting confirmation decision ─────────────────────────────
        if session.requirements_complete and not session.requirements_confirmed:
            return await self._handle_confirmation_state(
                db, client_id, session_id, session, user_message, memory
            )

        # ── STATE: Already confirmed → generate proposal ───────────────────────
        if session.requirements_confirmed and not session.confirmation_choice:
            pass  # fallthrough to normal chat

        # ── Normal conversation ────────────────────────────────────────────────
        response = await self.conv_agent.run(
            user_message=user_message,
            conversation_history=history,
            requirements_so_far=requirements,
            context_summary=session.context_summary,
        )

        # Extract requirements every 3 user messages
        msg_count = len([m for m in history if m["role"] == "user"])
        if msg_count % 3 == 0:
            requirements = await self._extract_and_save_requirements(
                db, session_id, history + [{"role": "user", "content": user_message}],
                requirements
            )

        # ── Check if agent thinks requirements are complete ────────────────────
        show_confirmation = False
        confirmation_summary = None

        if (REQUIREMENTS_COMPLETE_TRIGGER.lower() in response.lower()
                or requirements.get("is_complete")):
            # Generate summary and switch to confirmation state
            confirmation_summary = await self._generate_requirements_summary(requirements)
            await update_session_requirements(db, session_id, requirements, complete=True)
            await update_session_confirmation(db, session_id, "", confirmation_summary)

            response = CONFIRMATION_PROMPT.format(summary=confirmation_summary)
            show_confirmation = True

        # Persist agent message
        await add_message(db, session_id, MessageRole.ASSISTANT, response)
        memory.remember("assistant", response)

        # Update analytics
        await update_client_analytics(db, client_id, delta_messages=2)
        await analytics_engine.recalculate(db, client_id)

        # Advance stage if first message
        client = await get_client(db, client_id)
        if client and client.current_stage == TrackingStage.AGENT_ACCESSED:
            await advance_client_stage(db, client_id, TrackingStage.CONVERSATION_STARTED)

        elapsed = int((time.time() - t0) * 1000)
        return {
            "response": response,
            "session_id": session_id,
            "show_confirmation": show_confirmation,
            "confirmation_summary": confirmation_summary,
            "requirements_complete": session.requirements_complete or bool(requirements.get("is_complete")),
            "requirements_confirmed": session.requirements_confirmed,
            "elapsed_ms": elapsed,
        }

    async def handle_confirmation(
        self,
        db: AsyncSession,
        client_id: str,
        session_id: str,
        choice: str,  # "correct" | "clarify" | "wrong"
    ) -> Dict[str, Any]:
        """Handle client's confirmation decision."""
        memory = get_memory(session_id, client_id)
        session = await get_session(db, session_id)
        requirements = session.requirements_json or {}

        if choice == "correct":
            # Generate proposal
            await update_session_confirmation(db, session_id, "correct")
            result = await self._generate_proposal(db, client_id, session_id, requirements)
            response = PROPOSAL_RESPONSE
            await add_message(db, session_id, MessageRole.ASSISTANT, response)
            memory.remember("assistant", response)
            await advance_client_stage(db, client_id, TrackingStage.PROPOSAL_GENERATED)
            await update_client_status(db, client_id, ClientStatus.PROPOSAL_READY)
            await analytics_engine.recalculate(db, client_id)
            return {"response": response, "proposal_generated": True,
                     "proposal_id": result.get("proposal_id")}

        elif choice == "clarify":
            await update_session_confirmation(db, session_id, "clarify")
            response = ("Of course! Please tell me what you'd like to add or clarify, "
                        "and I'll update the requirements accordingly.")
            await add_message(db, session_id, MessageRole.ASSISTANT, response)
            memory.remember("assistant", response)
            return {"response": response, "show_confirmation": False}

        elif choice == "wrong":
            # Reset requirements and restart
            await update_session_confirmation(db, session_id, "wrong")
            await update_session_requirements(db, session_id, {}, complete=False)
            response = ("I apologize for the misunderstanding! Let's start fresh. "
                        "Could you describe your business challenge from the beginning?")
            await add_message(db, session_id, MessageRole.ASSISTANT, response)
            memory.short_term.clear()
            memory.remember("assistant", response)
            return {"response": response, "restart": True}

        return {"response": "Invalid choice.", "error": True}

    async def handle_document(
        self,
        db: AsyncSession,
        client_id: str,
        session_id: str,
        file_path: str,
        filename: str,
    ) -> Dict[str, Any]:
        """Process uploaded document and inject into conversation."""
        memory = get_memory(session_id, client_id)
        session = await get_session(db, session_id)
        existing_req = session.requirements_json or {}

        summary, context_msg, doc_req = await self.doc_agent.run(
            file_path=file_path, filename=filename,
            existing_requirements=existing_req,
        )

        merged = {**existing_req, **{k: v for k, v in doc_req.items()
                                      if v and k not in ("completeness_score", "is_complete")}}
        await update_session_requirements(db, session_id, merged)

        await add_message(db, session_id, MessageRole.USER,
                           f"[Document: {filename}]", "document", filename)
        await add_message(db, session_id, MessageRole.ASSISTANT, context_msg)
        memory.remember("user", f"[Document: {filename}]")
        memory.remember("assistant", context_msg)

        await update_client_analytics(db, client_id, delta_docs=1, delta_messages=2)
        await analytics_engine.recalculate(db, client_id)

        return {"message": context_msg, "summary": summary,
                 "session_id": session_id}

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _handle_confirmation_state(
        self, db, client_id, session_id, session, user_message, memory
    ) -> Dict[str, Any]:
        """When in confirmation-pending state, treat message as clarification."""
        requirements = session.requirements_json or {}
        history = memory.get_recent_context()

        # Run another round of extraction with the clarification
        new_req = await self.req_agent.run(
            history + [{"role": "user", "content": user_message}], requirements
        )
        await update_session_requirements(db, session_id, new_req,
                                           complete=new_req.get("is_complete", False))

        summary = await self._generate_requirements_summary(new_req)
        response = ("Thank you for the clarification! Here's the updated summary:\n\n"
                    + CONFIRMATION_PROMPT.format(summary=summary))

        await add_message(db, session_id, MessageRole.ASSISTANT, response)
        memory.remember("assistant", response)

        return {
            "response": response,
            "session_id": session_id,
            "show_confirmation": True,
            "confirmation_summary": summary,
        }

    async def _extract_and_save_requirements(
        self, db, session_id, history, existing
    ) -> Dict:
        extracted = await self.req_agent.run(history, existing)
        data = {k: v for k, v in extracted.items()
                if k not in ("completeness_score", "is_complete")}
        await update_session_requirements(db, session_id, {
            **data,
            "completeness_score": extracted.get("completeness_score", 0),
            "is_complete": extracted.get("is_complete", False),
        }, complete=extracted.get("is_complete", False))
        return extracted

    async def _generate_requirements_summary(self, requirements: Dict) -> str:
        """Ask LLM to format requirements into a readable summary."""
        from models.router import get_llm_client, TaskType
        llm = get_llm_client()
        prompt = f"""Format these business requirements as a clear, concise bullet-point summary 
for client confirmation. Be specific and professional.

Requirements: {requirements}

Output a clean summary with sections for:
- Company & Industry
- Business Challenge
- Required Solution (Zoho products if identified)
- Timeline & Budget
- Key Constraints

Keep it under 200 words."""
        try:
            return await llm.generate(prompt=prompt, task_type=TaskType.SUMMARIZATION)
        except Exception:
            # Fallback plain summary
            lines = []
            for k, v in requirements.items():
                if v and k not in ("completeness_score", "is_complete"):
                    lines.append(f"• {k.replace('_', ' ').title()}: {v}")
            return "\n".join(lines) or "Requirements gathered from our conversation."

    async def _generate_proposal(
        self, db, client_id, session_id, requirements
    ) -> Dict[str, Any]:
        """Run full proposal generation pipeline."""
        t0 = time.time()

        # Zoho mapping
        zoho_mapping = await self.zoho_mapper.run(
            requirements=requirements,
            business_problem=requirements.get("business_problem", ""),
        )

        # Get or create proposal record
        client = await get_client(db, client_id)
        existing = client.proposals if client else []
        if existing:
            proposal_record = existing[0]
            version_number = proposal_record.current_version + 1
        else:
            proposal_record = await create_proposal(
                db, client.id, session_id,
                title=f"Zoho Proposal for {requirements.get('company_name', 'Client')}",
                content={}
            )
            version_number = 1

        # Generate content
        content = await self.proposal_agent.run(
            requirements=requirements,
            version=version_number,
            zoho_mapping=zoho_mapping,
        )

        # Generate PDF
        company = requirements.get("company_name", "Client")
        pdf_filename = f"zoho_proposal_{company.lower().replace(' ', '_')}_v{version_number}.pdf"
        import os
        from pathlib import Path
        Path(settings.proposal_dir).mkdir(parents=True, exist_ok=True)
        pdf_path = await self.pdf_gen.generate(
            content=content, requirements=requirements, filename=pdf_filename
        )

        elapsed = int((time.time() - t0) * 1000)
        await add_proposal_version(
            db, proposal_record.id, version_number,
            pdf_path, pdf_filename, content, requirements,
            model_used="gemini-pro", generation_time_ms=elapsed,
            change_summary="Initial proposal" if version_number == 1
            else f"Updated v{version_number}"
        )

        logger.info(f"Proposal v{version_number} generated in {elapsed}ms")
        return {"proposal_id": proposal_record.id, "version": version_number}


# Singleton
chat_service = ChatService()
