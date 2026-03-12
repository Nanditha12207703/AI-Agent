"""
memory/memory_manager.py
------------------------
Multi-tier memory system:

  ┌─────────────────────────────────────────────────────────┐
  │  Short-term  │ In-memory window of recent messages       │
  │  Session     │ Full conversation history from DB         │
  │  Long-term   │ Past sessions & proposals from DB         │
  │  Vector      │ ChromaDB similarity search over proposals │
  └─────────────────────────────────────────────────────────┘
"""

import json
import uuid
from typing import List, Dict, Any, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from loguru import logger

from config.settings import settings


# ── Short-term memory ─────────────────────────────────────────────────────────

class ShortTermMemory:
    """Sliding window of the most recent N conversation turns."""

    def __init__(self, window_size: int = 20):
        self.window_size = window_size
        self._buffer: List[Dict[str, str]] = []

    def add(self, role: str, content: str) -> None:
        self._buffer.append({"role": role, "content": content})
        if len(self._buffer) > self.window_size:
            self._buffer = self._buffer[-self.window_size:]

    def get(self) -> List[Dict[str, str]]:
        return list(self._buffer)

    def to_gemini_history(self) -> List[Dict[str, Any]]:
        """Convert to Gemini chat history format."""
        history = []
        for msg in self._buffer:
            role = "model" if msg["role"] == "assistant" else "user"
            history.append({"role": role, "parts": [msg["content"]]})
        return history

    def clear(self) -> None:
        self._buffer.clear()

    def __len__(self) -> int:
        return len(self._buffer)


# ── Vector Memory (ChromaDB) ──────────────────────────────────────────────────

class VectorMemory:
    """
    Long-term semantic memory backed by ChromaDB.
    Stores proposal texts and conversation summaries as embeddings.
    Enables similarity search for self-learning.
    """

    def __init__(self):
        self._client: Optional[chromadb.Client] = None
        self._proposals_col = None
        self._conversations_col = None

    def _ensure_client(self) -> chromadb.Client:
        if self._client is None:
            self._client = chromadb.PersistentClient(
                path=settings.chroma_persist_dir,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._proposals_col = self._client.get_or_create_collection(
                name=settings.chroma_collection_proposals,
                metadata={"hnsw:space": "cosine"},
            )
            self._conversations_col = self._client.get_or_create_collection(
                name=settings.chroma_collection_conversations,
                metadata={"hnsw:space": "cosine"},
            )
        return self._client

    @property
    def proposals(self):
        self._ensure_client()
        return self._proposals_col

    @property
    def conversations(self):
        self._ensure_client()
        return self._conversations_col

    def store_proposal(self, proposal_id: str, content: str,
                       metadata: Dict[str, Any]) -> str:
        """Embed and store a proposal for future retrieval."""
        doc_id = f"proposal_{proposal_id}"
        try:
            self.proposals.upsert(
                ids=[doc_id],
                documents=[content],
                metadatas=[metadata],
            )
            logger.debug(f"Stored proposal vector: {doc_id}")
            return doc_id
        except Exception as e:
            logger.error(f"Vector store error: {e}")
            return doc_id

    def store_conversation_summary(self, session_id: str,
                                    summary: str,
                                    metadata: Dict[str, Any]) -> str:
        doc_id = f"session_{session_id}"
        try:
            self.conversations.upsert(
                ids=[doc_id],
                documents=[summary],
                metadatas=[metadata],
            )
            return doc_id
        except Exception as e:
            logger.error(f"Vector store error: {e}")
            return doc_id

    def search_similar_proposals(self, query: str,
                                  n_results: int = 5,
                                  industry_filter: str = None) -> List[Dict]:
        """Find proposals similar to the query text."""
        try:
            where = {"industry": industry_filter} if industry_filter else None
            results = self.proposals.query(
                query_texts=[query],
                n_results=n_results,
                where=where,
            )
            items = []
            if results["documents"] and results["documents"][0]:
                for i, doc in enumerate(results["documents"][0]):
                    items.append({
                        "id": results["ids"][0][i],
                        "content": doc,
                        "metadata": results["metadatas"][0][i],
                        "distance": results["distances"][0][i] if results.get("distances") else None,
                    })
            return items
        except Exception as e:
            logger.error(f"Vector search error: {e}")
            return []

    def search_similar_conversations(self, query: str,
                                      n_results: int = 3) -> List[Dict]:
        try:
            results = self.conversations.query(
                query_texts=[query],
                n_results=n_results,
            )
            items = []
            if results["documents"] and results["documents"][0]:
                for i, doc in enumerate(results["documents"][0]):
                    items.append({
                        "id": results["ids"][0][i],
                        "content": doc,
                        "metadata": results["metadatas"][0][i],
                    })
            return items
        except Exception as e:
            logger.error(f"Vector search error: {e}")
            return []


# ── Memory Manager (aggregates all tiers) ─────────────────────────────────────

class MemoryManager:
    """
    Unified access point for all memory tiers.
    One instance per active session.
    """

    def __init__(self, session_id: str, user_id: str):
        self.session_id = session_id
        self.user_id = user_id
        self.short_term = ShortTermMemory(window_size=20)
        self.vector = VectorMemory()

    # ── Short-term helpers ────────────────────────────────

    def remember(self, role: str, content: str) -> None:
        self.short_term.add(role, content)

    def get_recent_context(self) -> List[Dict[str, str]]:
        return self.short_term.get()

    def get_gemini_history(self) -> List[Dict]:
        return self.short_term.to_gemini_history()

    # ── Long-term / vector helpers ────────────────────────

    def store_proposal_memory(self, proposal_id: str, content: str,
                               industry: str = None,
                               company: str = None) -> str:
        metadata = {
            "proposal_id": proposal_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "industry": industry or "unknown",
            "company": company or "unknown",
        }
        return self.vector.store_proposal(proposal_id, content, metadata)

    def retrieve_similar_proposals(self, query: str,
                                    industry: str = None,
                                    n: int = 3) -> List[Dict]:
        return self.vector.search_similar_proposals(query, n_results=n,
                                                     industry_filter=industry)

    def store_session_summary(self, summary: str,
                               industry: str = None) -> str:
        metadata = {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "industry": industry or "unknown",
        }
        return self.vector.store_conversation_summary(
            self.session_id, summary, metadata
        )


# ── Global per-session registry ───────────────────────────────────────────────

_session_memories: Dict[str, MemoryManager] = {}


def get_memory(session_id: str, user_id: str) -> MemoryManager:
    """Get (or create) the MemoryManager for a session."""
    if session_id not in _session_memories:
        _session_memories[session_id] = MemoryManager(session_id, user_id)
    return _session_memories[session_id]


def flush_memory(session_id: str) -> None:
    """Remove a session's in-memory state (call on session close)."""
    _session_memories.pop(session_id, None)
