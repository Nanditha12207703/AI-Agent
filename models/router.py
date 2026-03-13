"""
models/router.py - Fixed for google-generativeai package (kept same package, fixed usage)
"""
import time
from enum import Enum
from typing import AsyncGenerator, Optional, List, Dict, Any
from loguru import logger
from config.settings import settings


class TaskType(str, Enum):
    CHAT = "chat"
    EXTRACTION = "extraction"
    SUMMARIZATION = "summarization"
    ANALYSIS = "analysis"
    PROPOSAL = "proposal"
    COMPLEX_REASONING = "complex"


TASK_MODEL_MAP: Dict[TaskType, str] = {
    TaskType.CHAT: "flash",
    TaskType.EXTRACTION: "flash",
    TaskType.SUMMARIZATION: "flash",
    TaskType.ANALYSIS: "pro",
    TaskType.PROPOSAL: "pro",
    TaskType.COMPLEX_REASONING: "pro",
}


class GeminiClient:
    def __init__(self):
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not set in environment")
        import google.generativeai as genai
        genai.configure(api_key=settings.gemini_api_key)
        self._genai = genai
        self._models: Dict[str, Any] = {}

    def _get_model(self, model_key: str) -> Any:
        if model_key not in self._models:
            model_name = (
                settings.gemini_pro_model if model_key == "pro"
                else settings.gemini_flash_model
            )
            self._models[model_key] = self._genai.GenerativeModel(
                model_name=model_name,
                generation_config=self._genai.types.GenerationConfig(
                    temperature=0.7, top_p=0.9, max_output_tokens=8192,
                ),
            )
        return self._models[model_key]

    def route(self, task_type: TaskType) -> str:
        return TASK_MODEL_MAP.get(task_type, "flash")

    async def generate(
        self, prompt: str, task_type: TaskType = TaskType.CHAT,
        system_prompt: Optional[str] = None, history: Optional[List[Dict]] = None,
        temperature: float = 0.7, max_tokens: int = 8192,
    ) -> str:
        model_key = self.route(task_type)
        model = self._get_model(model_key)
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
        self, prompt: str, task_type: TaskType = TaskType.CHAT,
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        model_key = self.route(task_type)
        model = self._get_model(model_key)
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        try:
            response = await model.generate_content_async(full_prompt, stream=True)
            async for chunk in response:
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            logger.error(f"Gemini streaming error: {e}")
            raise


_llm_client: Optional[GeminiClient] = None


def get_llm_client() -> GeminiClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = GeminiClient()
    return _llm_client
