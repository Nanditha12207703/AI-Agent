"""api/routes/chat.py"""
import os
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import (get_db, get_client, create_client_session,
                                   get_client_sessions, get_session_messages,
                                   mark_bot_accessed, advance_client_stage,
                                   get_client_proposals)
from database.models import TrackingStage
from services.chat_service import chat_service
from voice.processor import get_transcriber
from config.settings import settings

router = APIRouter(prefix="/chat", tags=["Chat"])


class ChatRequest(BaseModel):
    client_id: str
    session_id: Optional[str] = None
    message: str


class ConfirmationRequest(BaseModel):
    client_id: str
    session_id: str
    choice: str  # correct | clarify | wrong


@router.get("/init/{client_id}")
async def init_chat(client_id: str, db: AsyncSession = Depends(get_db)):
    """
    Called when client opens their chat URL.
    Marks bot as accessed, returns session info + opening message.
    """
    client = await get_client(db, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Chat link not found or expired")

    # Mark as accessed
    await mark_bot_accessed(db, client.client_id)

    # Get existing sessions
    sessions = await get_client_sessions(db, client.client_id)

    # Get opening message from agent
    from agents.conversation_agent import ConversationAgent
    agent = ConversationAgent()

    return {
        "client_id": client.client_id,
        "company_name": client.company_name,
        "industry": client.industry,
        "sessions": [
            {
                "id": s.id,
                "session_number": s.session_number,
                "title": s.title,
                "message_count": s.message_count,
                "created_at": s.created_at.isoformat(),
            }
            for s in sessions
        ],
        "opening_message": agent.get_opening_message(),
    }


@router.post("/session/new")
async def new_session(client_id: str, db: AsyncSession = Depends(get_db)):
    """Create a new conversation session for a client."""
    client = await get_client(db, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    existing = await get_client_sessions(db, client.client_id)
    session_num = len(existing) + 1

    session = await create_client_session(db, client.id, session_num)
    await advance_client_stage(db, client.client_id, TrackingStage.CONVERSATION_STARTED)

    return {
        "session_id": session.id,
        "session_number": session_num,
        "title": session.title,
        "created_at": session.created_at.isoformat(),
    }


@router.post("/message")
async def send_message(payload: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Send a text message and get agent response."""
    client = await get_client(db, payload.client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Auto-create session if not provided
    session_id = payload.session_id
    if not session_id:
        existing = await get_client_sessions(db, client.client_id)
        if existing:
            session_id = existing[0].id
        else:
            session = await create_client_session(db, client.id, 1)
            session_id = session.id

    result = await chat_service.handle_message(
        db=db, client_id=client.client_id,
        session_id=session_id, user_message=payload.message,
    )
    return result


@router.post("/confirm")
async def confirm_requirements(payload: ConfirmationRequest,
                                 db: AsyncSession = Depends(get_db)):
    """Handle client's confirmation choice (correct/clarify/wrong)."""
    client = await get_client(db, payload.client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return await chat_service.handle_confirmation(
        db=db, client_id=client.client_id,
        session_id=payload.session_id, choice=payload.choice,
    )


@router.post("/upload")
async def upload_document(
    client_id: str = Form(...),
    session_id: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a document (PDF/DOCX/CSV) to be processed by the agent."""
    client = await get_client(db, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    contents = await file.read()
    if len(contents) > settings.max_upload_size_bytes:
        raise HTTPException(status_code=413, detail="File too large")

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4()}_{file.filename}"
    file_path = upload_dir / safe_name

    with open(file_path, "wb") as f:
        f.write(contents)

    try:
        result = await chat_service.handle_document(
            db=db, client_id=client.client_id,
            session_id=session_id,
            file_path=str(file_path), filename=file.filename,
        )
    finally:
        if file_path.exists():
            os.unlink(file_path)

    return result


@router.post("/voice")
async def voice_message(
    client_id: str = Form(...),
    session_id: str = Form(...),
    audio: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload audio, transcribe, then send as message."""
    client = await get_client(db, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    audio_bytes = await audio.read()
    suffix = Path(audio.filename).suffix or ".wav"

    transcriber = get_transcriber()
    transcription = await transcriber.transcribe_bytes_async(audio_bytes, suffix)

    if not transcription:
        raise HTTPException(status_code=422, detail="Could not transcribe audio")

    result = await chat_service.handle_message(
        db=db, client_id=client.client_id,
        session_id=session_id, user_message=transcription,
        message_type="voice",
    )
    result["transcription"] = transcription
    return result


@router.get("/history/{client_id}/{session_id}")
async def get_history(client_id: str, session_id: str,
                        db: AsyncSession = Depends(get_db)):
    """Get message history for a session."""
    messages = await get_session_messages(db, session_id)
    return {
        "session_id": session_id,
        "messages": [
            {
                "id": m.id,
                "role": m.role.value,
                "content": m.content,
                "message_type": m.message_type,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ]
    }


@router.get("/proposals/{client_id}")
async def get_proposals(client_id: str, db: AsyncSession = Depends(get_db)):
    """Get all proposals and versions for a client's sidebar."""
    proposals = await get_client_proposals(db, client_id)
    return [
        {
            "id": p.id,
            "title": p.title,
            "status": p.status.value,
            "current_version": p.current_version,
            "created_at": p.created_at.isoformat(),
            "versions": [
                {
                    "id": v.id,
                    "version_number": v.version_number,
                    "change_summary": v.change_summary,
                    "created_at": v.created_at.isoformat(),
                }
                for v in (p.versions or [])
            ]
        }
        for p in proposals
    ]
