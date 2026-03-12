"""
agents/base_agent.py
--------------------
Abstract base class every agent inherits.
Provides a consistent interface and shared utilities.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from models.router import GeminiClient, TaskType, get_llm_client
from loguru import logger


class BaseAgent(ABC):
    """Common foundation for all agents in the system."""

    name: str = "BaseAgent"
    task_type: TaskType = TaskType.CHAT

    def __init__(self):
        self._llm: Optional[GeminiClient] = None

    @property
    def llm(self) -> GeminiClient:
        if self._llm is None:
            self._llm = get_llm_client()
        return self._llm

    @abstractmethod
    async def run(self, *args, **kwargs) -> Any:
        """Execute the agent's primary task."""
        ...

    async def _generate(self, prompt: str, system_prompt: str = None,
                         task_type: TaskType = None) -> str:
        """Convenience wrapper for LLM generation."""
        t = task_type or self.task_type
        try:
            return await self.llm.generate(
                prompt=prompt,
                task_type=t,
                system_prompt=system_prompt,
            )
        except Exception as e:
            logger.error(f"[{self.name}] LLM error: {e}")
            raise

    def log(self, message: str, level: str = "info") -> None:
        getattr(logger, level)(f"[{self.name}] {message}")
