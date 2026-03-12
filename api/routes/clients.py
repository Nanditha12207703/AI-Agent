"""api/routes/clients.py"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_user
from database.connection import (get_db, create_client, get_client,
                                   get_clients_by_owner, mark_bot_sent,
                                   update_client_status, get_dashboard_metrics)
from database.models import PresalesUser, ClientStatus
from services.analytics import analytics_engine

router = APIRouter(prefix="/clients", tags=["Clients"])


class CreateClientRequest(BaseModel):
    company_name: str
    industry: Optional[str] = None
    email: Optional[EmailStr] = None
    contact_name: Optional[str] = None


class ClientResponse(BaseModel):
    id: str
    client_id: str
    company_name: str
    industry: Optional[str]
    email: Optional[str]
    contact_name: Optional[str]
    status: str
    bot_url: Optional[str]
    lead_score: int
    closing_probability: float
    engagement_level: str
    total_messages: int
    total_sessions: int
    documents_uploaded: int
    current_stage: Optional[str]
    stage_history: Optional[list]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.post("", response_model=ClientResponse, status_code=201)
async def add_client(
    payload: CreateClientRequest,
    current_user: PresalesUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a new lead manually from the dashboard."""
    client = await create_client(
        db, owner_id=current_user.id,
        company_name=payload.company_name,
        industry=payload.industry,
        email=payload.email,
        contact_name=payload.contact_name,
    )
    return _map_client(client)


@router.get("", response_model=List[ClientResponse])
async def list_clients(
    current_user: PresalesUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all clients for the dashboard table."""
    clients = await get_clients_by_owner(db, current_user.id)
    return [_map_client(c) for c in clients]


@router.get("/dashboard-metrics")
async def dashboard_metrics(
    current_user: PresalesUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Top-level dashboard metrics + analytics charts data."""
    return await get_dashboard_metrics(db, current_user.id)


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client_detail(
    client_id: str,
    current_user: PresalesUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    client = await get_client(db, client_id)
    if not client or client.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Client not found")
    return _map_client(client)


@router.post("/{client_id}/send-bot")
async def send_bot(
    client_id: str,
    current_user: PresalesUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark bot as sent and return the shareable chat URL."""
    client = await get_client(db, client_id)
    if not client or client.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Client not found")
    await mark_bot_sent(db, client.client_id)
    return {
        "client_id": client.client_id,
        "chat_url": f"/client-chat/{client.client_id}",
        "full_url": f"http://localhost:3000/client-chat/{client.client_id}",
        "message": f"Bot URL ready to share with {client.company_name}"
    }


@router.get("/{client_id}/track")
async def track_client(
    client_id: str,
    current_user: PresalesUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get client progress timeline and analytics."""
    client = await get_client(db, client_id)
    if not client or client.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Client not found")

    # Recalculate analytics fresh
    analytics = await analytics_engine.recalculate(db, client.client_id)

    return {
        "client_id": client.client_id,
        "company_name": client.company_name,
        "current_stage": client.current_stage.value if client.current_stage else None,
        "stage_history": client.stage_history or [],
        "analytics": analytics,
        "proposals": [
            {
                "id": p.id,
                "title": p.title,
                "status": p.status.value,
                "current_version": p.current_version,
                "created_at": p.created_at.isoformat(),
                "versions": [
                    {
                        "version_number": v.version_number,
                        "change_summary": v.change_summary,
                        "created_at": v.created_at.isoformat(),
                    }
                    for v in (p.versions or [])
                ]
            }
            for p in (client.proposals or [])
        ]
    }


@router.get("/{client_id}/analytics")
async def get_client_analytics(
    client_id: str,
    current_user: PresalesUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed analytics for a single client."""
    client = await get_client(db, client_id)
    if not client or client.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Client not found")
    return await analytics_engine.recalculate(db, client.client_id)


def _map_client(c) -> dict:
    return {
        "id": c.id,
        "client_id": c.client_id,
        "company_name": c.company_name,
        "industry": c.industry,
        "email": c.email,
        "contact_name": c.contact_name,
        "status": c.status.value if c.status else "Not Started",
        "bot_url": c.bot_url,
        "lead_score": c.lead_score or 0,
        "closing_probability": round((c.closing_probability or 0) * 100, 1),
        "engagement_level": c.engagement_level.value if c.engagement_level else "Low",
        "total_messages": c.total_messages or 0,
        "total_sessions": c.total_sessions or 0,
        "documents_uploaded": c.documents_uploaded or 0,
        "current_stage": c.current_stage.value if c.current_stage else None,
        "stage_history": c.stage_history or [],
        "created_at": c.created_at.isoformat() if c.created_at else "",
        "updated_at": c.updated_at.isoformat() if c.updated_at else "",
    }
