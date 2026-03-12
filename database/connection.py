"""
database/connection.py + crud.py (combined for brevity)
"""

from typing import AsyncGenerator, List, Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import select, update, desc, func, and_
from sqlalchemy.orm import selectinload
from loguru import logger

from config.settings import settings
from database.models import (
    Base, PresalesUser, Client, ClientSession, Message,
    Proposal, ProposalVersion, AnalyticsSnapshot,
    ClientStatus, EngagementLevel, MessageRole, TrackingStage,
    ProposalStatus
)

# ── Engine ────────────────────────────────────────────────────────────────────

def _build_engine():
    url = settings.database_url
    if url.startswith("sqlite"):
        return create_async_engine(url, echo=settings.database_echo,
                                    connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
    return create_async_engine(url, echo=settings.database_echo,
                                pool_pre_ping=True, pool_size=10, max_overflow=20)


engine = _build_engine()
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession,
                                        expire_on_commit=False, autocommit=False, autoflush=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized.")


async def close_db():
    await engine.dispose()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── PresalesUser CRUD ─────────────────────────────────────────────────────────

async def get_user_by_email(db: AsyncSession, email: str) -> Optional[PresalesUser]:
    r = await db.execute(select(PresalesUser).where(PresalesUser.email == email))
    return r.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: str) -> Optional[PresalesUser]:
    r = await db.execute(select(PresalesUser).where(PresalesUser.id == user_id))
    return r.scalar_one_or_none()


async def create_presales_user(db: AsyncSession, email: str, full_name: str = None) -> PresalesUser:
    user = PresalesUser(email=email, full_name=full_name, password_set=False)
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def set_user_password(db: AsyncSession, user_id: str, hashed_password: str):
    await db.execute(update(PresalesUser).where(PresalesUser.id == user_id)
                     .values(hashed_password=hashed_password, password_set=True,
                             updated_at=datetime.utcnow()))


async def set_reset_token(db: AsyncSession, user_id: str, token: str, expiry: datetime):
    await db.execute(update(PresalesUser).where(PresalesUser.id == user_id)
                     .values(reset_token=token, reset_token_expiry=expiry,
                             updated_at=datetime.utcnow()))


async def clear_reset_token(db: AsyncSession, user_id: str):
    await db.execute(update(PresalesUser).where(PresalesUser.id == user_id)
                     .values(reset_token=None, reset_token_expiry=None,
                             updated_at=datetime.utcnow()))


async def update_last_login(db: AsyncSession, user_id: str):
    await db.execute(update(PresalesUser).where(PresalesUser.id == user_id)
                     .values(last_login=datetime.utcnow()))


# ── Client CRUD ───────────────────────────────────────────────────────────────

def _generate_client_id(company_name: str, sequence: int) -> str:
    """Generate readable client ID: first 5 chars of company + zero-padded seq."""
    prefix = "".join(c.upper() for c in company_name if c.isalpha())[:5].ljust(5, "X")
    return f"{prefix}{str(sequence).zfill(3)}"


async def create_client(db: AsyncSession, owner_id: str, company_name: str,
                         industry: str = None, email: str = None,
                         contact_name: str = None) -> Client:
    # Count existing clients for this owner to generate sequence
    count_r = await db.execute(
        select(func.count(Client.id)).where(Client.owner_id == owner_id)
    )
    seq = (count_r.scalar() or 0) + 1
    client_id = _generate_client_id(company_name, seq)

    client = Client(owner_id=owner_id, client_id=client_id,
                     company_name=company_name, industry=industry,
                     email=email, contact_name=contact_name,
                     bot_url=f"/client-chat/{client_id}")
    db.add(client)
    await db.flush()
    await db.refresh(client)
    return client


async def get_client(db: AsyncSession, client_id_str: str) -> Optional[Client]:
    """Accepts either UUID id or short client_id like FRIST001."""
    r = await db.execute(
        select(Client).where(
            (Client.id == client_id_str) | (Client.client_id == client_id_str)
        ).options(selectinload(Client.sessions), selectinload(Client.proposals))
    )
    return r.scalar_one_or_none()


async def get_clients_by_owner(db: AsyncSession, owner_id: str,
                                 limit: int = 200) -> List[Client]:
    r = await db.execute(
        select(Client).where(Client.owner_id == owner_id)
        .order_by(desc(Client.lead_score), desc(Client.updated_at))
        .limit(limit)
    )
    return r.scalars().all()


async def update_client_status(db: AsyncSession, client_id: str, status: ClientStatus):
    await db.execute(update(Client).where(Client.client_id == client_id)
                     .values(status=status, updated_at=datetime.utcnow()))


async def mark_bot_sent(db: AsyncSession, client_id: str):
    await db.execute(update(Client).where(Client.client_id == client_id)
                     .values(status=ClientStatus.SENT, bot_sent_at=datetime.utcnow(),
                             current_stage=TrackingStage.AGENT_SENT,
                             updated_at=datetime.utcnow()))


async def mark_bot_accessed(db: AsyncSession, client_id: str):
    client = await get_client(db, client_id)
    if not client:
        return
    if not client.first_accessed_at:
        history = client.stage_history or []
        history.append({"stage": TrackingStage.AGENT_ACCESSED.value,
                         "timestamp": datetime.utcnow().isoformat()})
        await db.execute(update(Client).where(Client.client_id == client_id)
                         .values(first_accessed_at=datetime.utcnow(),
                                 current_stage=TrackingStage.AGENT_ACCESSED,
                                 stage_history=history,
                                 updated_at=datetime.utcnow()))


async def advance_client_stage(db: AsyncSession, client_id: str, stage: TrackingStage):
    client = await get_client(db, client_id)
    if not client:
        return
    history = client.stage_history or []
    history.append({"stage": stage.value, "timestamp": datetime.utcnow().isoformat()})
    await db.execute(update(Client).where(Client.client_id == client_id)
                     .values(current_stage=stage, stage_history=history,
                             updated_at=datetime.utcnow()))


# ── Analytics update ──────────────────────────────────────────────────────────

async def update_client_analytics(db: AsyncSession, client_id: str,
                                    delta_messages: int = 0,
                                    delta_docs: int = 0,
                                    delta_audio: int = 0,
                                    lead_score: int = None,
                                    closing_probability: float = None,
                                    engagement_level: EngagementLevel = None,
                                    lead_score_breakdown: dict = None):
    client = await get_client(db, client_id)
    if not client:
        return

    values = {"updated_at": datetime.utcnow(), "last_active_at": datetime.utcnow()}
    if delta_messages:
        values["total_messages"] = (client.total_messages or 0) + delta_messages
    if delta_docs:
        values["documents_uploaded"] = (client.documents_uploaded or 0) + delta_docs
    if delta_audio:
        values["audio_uploads"] = (client.audio_uploads or 0) + delta_audio
    if lead_score is not None:
        values["lead_score"] = lead_score
    if closing_probability is not None:
        values["closing_probability"] = closing_probability
    if engagement_level is not None:
        values["engagement_level"] = engagement_level
    if lead_score_breakdown is not None:
        values["lead_score_breakdown"] = lead_score_breakdown

    await db.execute(update(Client).where(Client.client_id == client_id).values(**values))


# ── Session CRUD ──────────────────────────────────────────────────────────────

async def create_client_session(db: AsyncSession, client_id: str,
                                  session_number: int = 1) -> ClientSession:
    session = ClientSession(client_id=client_id, session_number=session_number)
    db.add(session)
    # Increment client session count
    client = await get_client(db, client_id)
    if client:
        await db.execute(update(Client).where(Client.client_id == client_id)
                         .values(total_sessions=(client.total_sessions or 0) + 1,
                                 status=ClientStatus.IN_SESSION,
                                 updated_at=datetime.utcnow()))
    await db.flush()
    await db.refresh(session)
    return session


async def get_session(db: AsyncSession, session_id: str) -> Optional[ClientSession]:
    r = await db.execute(
        select(ClientSession).where(ClientSession.id == session_id)
        .options(selectinload(ClientSession.messages))
    )
    return r.scalar_one_or_none()


async def get_client_sessions(db: AsyncSession, client_id: str) -> List[ClientSession]:
    client = await get_client(db, client_id)
    if not client:
        return []
    r = await db.execute(
        select(ClientSession).where(ClientSession.client_id == client.id)
        .order_by(desc(ClientSession.created_at))
    )
    return r.scalars().all()


async def update_session_requirements(db: AsyncSession, session_id: str,
                                        requirements: dict, complete: bool = False):
    await db.execute(
        update(ClientSession).where(ClientSession.id == session_id)
        .values(requirements_json=requirements, requirements_complete=complete,
                updated_at=datetime.utcnow())
    )


async def update_session_confirmation(db: AsyncSession, session_id: str,
                                        choice: str, summary: str = None):
    vals = {"confirmation_choice": choice, "updated_at": datetime.utcnow()}
    if choice == "correct":
        vals["requirements_confirmed"] = True
    if summary:
        vals["requirements_summary"] = summary
    await db.execute(update(ClientSession).where(ClientSession.id == session_id).values(**vals))


# ── Message CRUD ──────────────────────────────────────────────────────────────

async def add_message(db: AsyncSession, session_id: str, role: MessageRole,
                       content: str, message_type: str = "text",
                       source_file: str = None) -> Message:
    msg = Message(session_id=session_id, role=role, content=content,
                   message_type=message_type, source_file=source_file)
    db.add(msg)
    await db.execute(update(ClientSession).where(ClientSession.id == session_id)
                     .values(message_count=ClientSession.message_count + 1,
                             updated_at=datetime.utcnow()))
    await db.flush()
    await db.refresh(msg)
    return msg


async def get_session_messages(db: AsyncSession, session_id: str) -> List[Message]:
    r = await db.execute(
        select(Message).where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )
    return r.scalars().all()


# ── Proposal CRUD ─────────────────────────────────────────────────────────────

async def create_proposal(db: AsyncSession, client_id: str, session_id: str,
                            title: str, content: dict) -> Proposal:
    prop = Proposal(client_id=client_id, session_id=session_id,
                     title=title, proposal_content=content,
                     status=ProposalStatus.DRAFT)
    db.add(prop)
    await db.flush()
    await db.refresh(prop)
    return prop


async def get_client_proposals(db: AsyncSession, client_id: str) -> List[Proposal]:
    client = await get_client(db, client_id)
    if not client:
        return []
    r = await db.execute(
        select(Proposal).where(Proposal.client_id == client.id)
        .options(selectinload(Proposal.versions))
        .order_by(desc(Proposal.created_at))
    )
    return r.scalars().all()


async def add_proposal_version(db: AsyncSession, proposal_id: str, version_number: int,
                                 pdf_path: str, pdf_filename: str,
                                 content_snapshot: dict, requirements_snapshot: dict,
                                 model_used: str = None, generation_time_ms: int = None,
                                 change_summary: str = None) -> ProposalVersion:
    v = ProposalVersion(proposal_id=proposal_id, version_number=version_number,
                         pdf_path=pdf_path, pdf_filename=pdf_filename,
                         content_snapshot=content_snapshot,
                         requirements_snapshot=requirements_snapshot,
                         model_used=model_used, generation_time_ms=generation_time_ms,
                         change_summary=change_summary)
    db.add(v)
    await db.execute(update(Proposal).where(Proposal.id == proposal_id)
                     .values(current_version=version_number,
                             status=ProposalStatus.GENERATED,
                             updated_at=datetime.utcnow()))
    await db.flush()
    await db.refresh(v)
    return v


# ── Dashboard Aggregates ──────────────────────────────────────────────────────

async def get_dashboard_metrics(db: AsyncSession, owner_id: str) -> Dict[str, Any]:
    clients = await get_clients_by_owner(db, owner_id)

    total = len(clients)
    bots_sent = sum(1 for c in clients if c.bot_sent_at)
    active = sum(1 for c in clients if c.status == ClientStatus.IN_SESSION)
    proposals_ready = sum(1 for c in clients if c.status in
                          (ClientStatus.PROPOSAL_READY, ClientStatus.SUBMITTED))

    # Engagement distribution
    high = sum(1 for c in clients if c.engagement_level == EngagementLevel.HIGH)
    moderate = sum(1 for c in clients if c.engagement_level == EngagementLevel.MODERATE)
    low = sum(1 for c in clients if c.engagement_level == EngagementLevel.LOW)

    # Lead score buckets
    scores = [c.lead_score or 0 for c in clients]
    s0_25 = sum(1 for s in scores if s <= 25)
    s26_50 = sum(1 for s in scores if 26 <= s <= 50)
    s51_75 = sum(1 for s in scores if 51 <= s <= 75)
    s76_100 = sum(1 for s in scores if s > 75)

    avg_prob = (sum(c.closing_probability or 0 for c in clients) / total) if total else 0

    return {
        "total_clients": total,
        "bots_sent": bots_sent,
        "active_sessions": active,
        "proposals_ready": proposals_ready,
        "engagement_distribution": {"high": high, "moderate": moderate, "low": low},
        "lead_score_distribution": {"0-25": s0_25, "26-50": s26_50,
                                     "51-75": s51_75, "76-100": s76_100},
        "avg_closing_probability": round(avg_prob * 100, 1),
    }
