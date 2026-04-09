"""
models/router.py
----------------
Model routing layer.

Selects between Gemini Flash (fast, simple tasks) and Gemini Pro
(complex analysis, proposal generation) based on task type and complexity.
Falls back to OpenAI or Anthropic if configured.
"""

import time
from enum import Enum
from typing import AsyncGenerator, Optional, List, Dict, Any
import google.generativeai as genai
from loguru import logger

from config.settings import settings


# ── Task Complexity ───────────────────────────────────────────────────────────

class TaskType(str, Enum):
    CHAT = "chat"                       # → Flash
    EXTRACTION = "extraction"           # → Flash
    SUMMARIZATION = "summarization"     # → Flash
    ANALYSIS = "analysis"               # → Pro
    PROPOSAL = "proposal"               # → Pro
    COMPLEX_REASONING = "complex"       # → Pro


TASK_MODEL_MAP: Dict[TaskType, str] = {
    TaskType.CHAT: "flash",
    TaskType.EXTRACTION: "flash",
    TaskType.SUMMARIZATION: "flash",
    TaskType.ANALYSIS: "pro",
    TaskType.PROPOSAL: "pro",
    TaskType.COMPLEX_REASONING: "pro",
}


# ── Gemini Client ─────────────────────────────────────────────────────────────

class GeminiClient:
    """Wrapper around google-generativeai with model routing."""

    def __init__(self):
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not set in environment")
        genai.configure(api_key=settings.gemini_api_key)
        self._models: Dict[str, genai.GenerativeModel] = {}

    def _get_model(self, model_key: str) -> genai.GenerativeModel:
        if model_key not in self._models:
            model_name = (
                settings.gemini_pro_model
                if model_key == "pro"
                else settings.gemini_flash_model
            )
            self._models[model_key] = genai.GenerativeModel(
                model_name=model_name,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.7,
                    top_p=0.9,
                    max_output_tokens=8192,
                ),
            )
        return self._models[model_key]

    def route(self, task_type: TaskType) -> str:
        """Return model key ('flash' | 'pro') for a task type."""
        return TASK_MODEL_MAP.get(task_type, "flash")

    async def generate(
        self,
        prompt: str,
        task_type: TaskType = TaskType.CHAT,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 8192,
    ) -> str:
        """
        Non-streaming generation.
        history: list of {"role": "user"|"model", "parts": ["..."]}
        """
        model_key = self.route(task_type)
        model = self._get_model(model_key)

        # Build final prompt with optional system context
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt

        try:
            t0 = time.time()

            if history:
                chat = model.start_chat(history=history)
                response = await chat.send_message_async(full_prompt)
            else:
                response = await model.generate_content_async(full_prompt)

            elapsed = int((time.time() - t0) * 1000)
            logger.debug(f"Gemini [{model_key}] | {elapsed}ms | task={task_type}")
            return response.text

        except Exception as e:
            logger.error(f"Gemini generation error: {e}")
            raise

    async def stream(
        self,
        prompt: str,
        task_type: TaskType = TaskType.CHAT,
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming generation – yields text chunks."""
        model_key = self.route(task_type)
        model = self._get_model(model_key)

        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt

        try:
            response = await model.generate_content_async(
                full_prompt, stream=True
            )
            async for chunk in response:
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            logger.error(f"Gemini streaming error: {e}")
            raise


# ── Singleton ─────────────────────────────────────────────────────────────────

_llm_client: Optional[GeminiClient] = None


def get_llm_client() -> GeminiClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = GeminiClient()
    return _llm_client
