"""
services/analytics.py
----------------------
Real-time analytics engine.
Recalculates lead score, closing probability, and engagement level
whenever client activity occurs. Updates DB automatically.
"""

from datetime import datetime
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_client, update_client_analytics
from database.models import EngagementLevel


class AnalyticsEngine:
    """Calculates and updates all client engagement analytics."""

    # ── Lead Score weights (sum = 100) ────────────────────────────────────────
    SCORE_WEIGHTS = {
        "message_count":            20,   # Up to 20 pts (20+ messages = max)
        "sessions":                 10,   # Multiple sessions = committed
        "documents_uploaded":       15,   # Documents = serious intent
        "requirements_complete":    20,   # Full requirements = 20 pts
        "proposal_generated":       15,   # Proposal requested = hot lead
        "audio_uploads":             5,   # Voice = high engagement
        "response_speed":           10,   # Fast replies = interested
        "conversation_depth":        5,   # Long messages = engaged
    }

    async def recalculate(self, db: AsyncSession, client_id: str) -> Dict[str, Any]:
        """
        Recalculate all analytics for a client and persist to DB.
        Returns the updated analytics dict.
        """
        client = await get_client(db, client_id)
        if not client:
            return {}

        # ── Gather raw metrics ────────────────────────────────────────────────
        msg_count = client.total_messages or 0
        sessions = client.total_sessions or 0
        docs = client.documents_uploaded or 0
        audio = client.audio_uploads or 0

        # Check if requirements are complete from latest session
        req_complete = False
        if client.sessions:
            latest = sorted(client.sessions, key=lambda s: s.created_at, reverse=True)
            if latest:
                req_complete = latest[0].requirements_confirmed or False

        proposal_generated = len(client.proposals) > 0

        # ── Lead Score ────────────────────────────────────────────────────────
        score_breakdown = {}

        # Messages score: 0-20 pts (cap at 30 messages)
        msg_score = min(msg_count / 30, 1.0) * self.SCORE_WEIGHTS["message_count"]
        score_breakdown["message_count"] = round(msg_score, 1)

        # Sessions score: 0-10 pts
        session_score = min(sessions / 3, 1.0) * self.SCORE_WEIGHTS["sessions"]
        score_breakdown["sessions"] = round(session_score, 1)

        # Documents: 0-15 pts
        doc_score = min(docs / 3, 1.0) * self.SCORE_WEIGHTS["documents_uploaded"]
        score_breakdown["documents_uploaded"] = round(doc_score, 1)

        # Requirements complete: 0 or 20
        req_score = self.SCORE_WEIGHTS["requirements_complete"] if req_complete else 0
        score_breakdown["requirements_complete"] = req_score

        # Proposal generated: 0 or 15
        prop_score = self.SCORE_WEIGHTS["proposal_generated"] if proposal_generated else 0
        score_breakdown["proposal_generated"] = prop_score

        # Audio uploads: 0-5 pts
        audio_score = min(audio / 2, 1.0) * self.SCORE_WEIGHTS["audio_uploads"]
        score_breakdown["audio_uploads"] = round(audio_score, 1)

        # Response speed (use last_active_at vs created_at)
        speed_score = self._calc_speed_score(client)
        score_breakdown["response_speed"] = round(speed_score, 1)

        # Conversation depth (dummy for now — based on msg count)
        depth_score = min(msg_count / 20, 1.0) * self.SCORE_WEIGHTS["conversation_depth"]
        score_breakdown["conversation_depth"] = round(depth_score, 1)

        total_score = int(sum(score_breakdown.values()))
        total_score = min(max(total_score, 0), 100)

        # ── Closing Probability ────────────────────────────────────────────────
        prob = self._calc_closing_probability(
            lead_score=total_score,
            req_complete=req_complete,
            proposal_generated=proposal_generated,
            sessions=sessions,
            msg_count=msg_count,
        )

        # ── Engagement Level ──────────────────────────────────────────────────
        engagement = self._calc_engagement(msg_count, sessions, docs, audio, proposal_generated)

        # ── Conversation duration ─────────────────────────────────────────────
        duration = self._calc_duration(client)

        # ── Persist to DB ─────────────────────────────────────────────────────
        await update_client_analytics(
            db, client_id,
            lead_score=total_score,
            closing_probability=prob,
            engagement_level=engagement,
            lead_score_breakdown={
                "breakdown": score_breakdown,
                "total": total_score,
                "calculated_at": datetime.utcnow().isoformat(),
            }
        )

        return {
            "lead_score": total_score,
            "closing_probability": round(prob * 100, 1),
            "engagement_level": engagement.value,
            "score_breakdown": score_breakdown,
            "conversation_length": {
                "messages": msg_count,
                "sessions": sessions,
                "duration_minutes": round(duration, 1),
            }
        }

    def _calc_closing_probability(self, lead_score: int, req_complete: bool,
                                    proposal_generated: bool, sessions: int,
                                    msg_count: int) -> float:
        """Weighted formula for closing probability (0.0–1.0)."""
        prob = lead_score / 100 * 0.5       # Base: 50% weight on lead score
        if req_complete:
            prob += 0.15
        if proposal_generated:
            prob += 0.20
        if sessions >= 2:
            prob += 0.10
        if msg_count >= 15:
            prob += 0.05
        return min(round(prob, 3), 1.0)

    def _calc_engagement(self, msgs: int, sessions: int, docs: int,
                          audio: int, proposal: bool) -> EngagementLevel:
        """Classify engagement level."""
        points = 0
        if msgs >= 20:
            points += 3
        elif msgs >= 8:
            points += 2
        elif msgs >= 3:
            points += 1

        if sessions >= 2:
            points += 2
        if docs >= 1:
            points += 2
        if audio >= 1:
            points += 1
        if proposal:
            points += 3

        if points >= 7:
            return EngagementLevel.HIGH
        elif points >= 3:
            return EngagementLevel.MODERATE
        return EngagementLevel.LOW

    def _calc_speed_score(self, client) -> float:
        """Score based on how quickly client first accessed the bot after it was sent."""
        if not client.bot_sent_at or not client.first_accessed_at:
            return 0.0
        delta = client.first_accessed_at - client.bot_sent_at
        hours = delta.total_seconds() / 3600
        if hours <= 1:
            return self.SCORE_WEIGHTS["response_speed"]
        elif hours <= 24:
            return self.SCORE_WEIGHTS["response_speed"] * 0.6
        elif hours <= 72:
            return self.SCORE_WEIGHTS["response_speed"] * 0.3
        return 0.0

    def _calc_duration(self, client) -> float:
        """Estimate total conversation duration in minutes."""
        total = 0.0
        for session in (client.sessions or []):
            if session.started_at:
                end = session.ended_at or session.updated_at or datetime.utcnow()
                delta = (end - session.started_at).total_seconds() / 60
                total += max(0, delta)
        return total


# Singleton
analytics_engine = AnalyticsEngine()
