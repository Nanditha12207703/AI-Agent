"""
database/models.py
------------------
Full ORM schema for the PresalesAI platform.
Covers: presales agents, clients, sessions, messages, proposals,
        analytics, and engagement tracking.
"""

import uuid
from datetime import datetime
import enum

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, JSON, Enum as SAEnum, Index
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


def gen_uuid() -> str:
    return str(uuid.uuid4())


def gen_client_id(prefix: str = "CLT") -> str:
    """Generate human-readable client ID like FRIST001."""
    return f"{prefix}{str(uuid.uuid4().int)[:6].zfill(6)}"


# ── Enums ─────────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    PRESALES = "presales"
    ADMIN = "admin"


class ClientStatus(str, enum.Enum):
    NOT_STARTED = "Not Started"
    IN_SESSION = "In Session"
    SUBMITTED = "Submitted"
    SENT = "Sent"
    PROPOSAL_READY = "Proposal Ready"
    CLOSED = "Closed"


class EngagementLevel(str, enum.Enum):
    LOW = "Low"
    MODERATE = "Moderate"
    HIGH = "High"


class ProposalStatus(str, enum.Enum):
    DRAFT = "draft"
    GENERATED = "generated"
    SENT = "sent"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class TrackingStage(str, enum.Enum):
    AGENT_SENT = "Agent Sent"
    AGENT_ACCESSED = "Agent Accessed"
    CONVERSATION_STARTED = "Conversation Started"
    PROPOSAL_GENERATED = "Proposal Generated"
    PROPOSAL_SENT = "Proposal Sent"


# ── Presales Agent Users ───────────────────────────────────────────────────────

class PresalesUser(Base):
    """Presales agents who log into the dashboard."""
    __tablename__ = "presales_users"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255))
    hashed_password = Column(String(255))        # None until first login
    role = Column(SAEnum(UserRole), default=UserRole.PRESALES)
    is_active = Column(Boolean, default=True)
    password_set = Column(Boolean, default=False)  # First-time password flow
    reset_token = Column(String(255))
    reset_token_expiry = Column(DateTime)
    last_login = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    clients = relationship("Client", back_populates="owner", cascade="all, delete-orphan")


# ── Clients ───────────────────────────────────────────────────────────────────

class Client(Base):
    """Clients managed by presales agents."""
    __tablename__ = "clients"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    client_id = Column(String(20), unique=True, nullable=False, index=True)  # e.g. FRIST001
    owner_id = Column(String(36), ForeignKey("presales_users.id"), nullable=False, index=True)

    # Identity
    company_name = Column(String(255), nullable=False)
    industry = Column(String(255))
    email = Column(String(255))
    contact_name = Column(String(255))
    phone = Column(String(50))

    # Status
    status = Column(SAEnum(ClientStatus), default=ClientStatus.NOT_STARTED)
    bot_url = Column(String(500))    # The unique chat URL sent to client
    bot_sent_at = Column(DateTime)
    first_accessed_at = Column(DateTime)
    notes = Column(Text)

    # ── Analytics Fields ──────────────────────────────────────────────────────
    total_messages = Column(Integer, default=0)
    total_sessions = Column(Integer, default=0)
    conversation_duration_minutes = Column(Float, default=0.0)
    last_active_at = Column(DateTime)
    documents_uploaded = Column(Integer, default=0)
    audio_uploads = Column(Integer, default=0)

    # Scoring
    lead_score = Column(Integer, default=0)           # 0-100
    closing_probability = Column(Float, default=0.0)  # 0.0-1.0
    engagement_level = Column(SAEnum(EngagementLevel), default=EngagementLevel.LOW)
    lead_score_breakdown = Column(JSON, default=dict)

    # Tracking stage
    current_stage = Column(SAEnum(TrackingStage))
    stage_history = Column(JSON, default=list)        # [{stage, timestamp}]

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    owner = relationship("PresalesUser", back_populates="clients")
    sessions = relationship("ClientSession", back_populates="client", cascade="all, delete-orphan")
    proposals = relationship("Proposal", back_populates="client", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_client_owner_status", "owner_id", "status"),
        Index("idx_client_lead_score", "lead_score"),
    )


# ── Client Sessions ───────────────────────────────────────────────────────────

class ClientSession(Base):
    """A single conversation session between a client and the AI agent."""
    __tablename__ = "client_sessions"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    client_id = Column(String(36), ForeignKey("clients.id"), nullable=False, index=True)
    session_number = Column(Integer, default=1)
    title = Column(String(255), default="New Conversation")

    # Requirement gathering state
    requirements_json = Column(JSON, default=dict)
    requirements_complete = Column(Boolean, default=False)
    requirements_confirmed = Column(Boolean, default=False)    # Client confirmed summary
    confirmation_choice = Column(String(50))                   # correct/clarify/wrong
    requirements_summary = Column(Text)                        # Summary shown to client

    # Context
    context_summary = Column(Text)                             # Rolling LLM summary
    is_active = Column(Boolean, default=True)

    # Analytics per session
    message_count = Column(Integer, default=0)
    duration_minutes = Column(Float, default=0.0)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    client = relationship("Client", back_populates="sessions")
    messages = relationship("Message", back_populates="session",
                             cascade="all, delete-orphan",
                             order_by="Message.created_at")


# ── Messages ──────────────────────────────────────────────────────────────────

class Message(Base):
    """Individual messages within a session."""
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("client_sessions.id"), nullable=False, index=True)
    role = Column(SAEnum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)
    message_type = Column(String(50), default="text")   # text|voice|document|image
    source_file = Column(String(500))
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("ClientSession", back_populates="messages")


# ── Proposals ─────────────────────────────────────────────────────────────────

class Proposal(Base):
    """Proposals generated for clients."""
    __tablename__ = "proposals"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    client_id = Column(String(36), ForeignKey("clients.id"), nullable=False, index=True)
    session_id = Column(String(36), ForeignKey("client_sessions.id"), nullable=True)
    title = Column(String(500))
    status = Column(SAEnum(ProposalStatus), default=ProposalStatus.DRAFT)
    current_version = Column(Integer, default=1)
    proposal_content = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("Client", back_populates="proposals")
    versions = relationship("ProposalVersion", back_populates="proposal",
                             cascade="all, delete-orphan",
                             order_by="ProposalVersion.version_number")


class ProposalVersion(Base):
    """Version history for proposals."""
    __tablename__ = "proposal_versions"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    proposal_id = Column(String(36), ForeignKey("proposals.id"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    pdf_path = Column(String(1000))
    pdf_filename = Column(String(500))
    content_snapshot = Column(JSON)
    requirements_snapshot = Column(JSON)
    model_used = Column(String(100))
    generation_time_ms = Column(Integer)
    change_summary = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    proposal = relationship("Proposal", back_populates="versions")


# ── Analytics Snapshots ───────────────────────────────────────────────────────

class AnalyticsSnapshot(Base):
    """Daily/periodic analytics snapshots for dashboard charts."""
    __tablename__ = "analytics_snapshots"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    owner_id = Column(String(36), ForeignKey("presales_users.id"), index=True)
    snapshot_date = Column(DateTime, default=datetime.utcnow)

    # Aggregate metrics
    total_clients = Column(Integer, default=0)
    bots_sent = Column(Integer, default=0)
    active_sessions = Column(Integer, default=0)
    proposals_ready = Column(Integer, default=0)

    # Engagement distribution
    high_engagement_count = Column(Integer, default=0)
    moderate_engagement_count = Column(Integer, default=0)
    low_engagement_count = Column(Integer, default=0)

    # Lead score distribution buckets
    score_0_25 = Column(Integer, default=0)
    score_26_50 = Column(Integer, default=0)
    score_51_75 = Column(Integer, default=0)
    score_76_100 = Column(Integer, default=0)

    # Conversion probability averages
    avg_closing_probability = Column(Float, default=0.0)

    created_at = Column(DateTime, default=datetime.utcnow)
