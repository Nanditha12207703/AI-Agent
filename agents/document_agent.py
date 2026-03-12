"""
agents/document_agent.py
------------------------
Orchestrates document ingestion:
  1. Extract raw text via DocumentProcessor
  2. Summarize long documents
  3. Extract requirements from content
  4. Return agent-ready context string
"""

from typing import Dict, Any, Tuple

from agents.base_agent import BaseAgent
from agents.requirement_agent import RequirementAgent
from documents.processor import DocumentProcessor
from models.router import TaskType

SUMMARIZE_PROMPT = """Summarize the following document in a concise, structured way.
Focus on: business requirements, problems described, technical specifications, and any metrics.
Keep the summary under 800 words.

Document ({filename}):
{content}

Summary:"""


class DocumentAgent(BaseAgent):
    name = "DocumentAgent"
    task_type = TaskType.SUMMARIZATION

    def __init__(self):
        super().__init__()
        self.processor = DocumentProcessor()
        self.req_agent = RequirementAgent()

    async def run(
        self,
        file_path: str,
        filename: str,
        existing_requirements: Dict = None,
    ) -> Tuple[str, str, Dict]:
        """
        Process an uploaded document.

        Returns:
            (summary, context_message, extracted_requirements)
        """
        # Step 1: Extract text
        self.log(f"Extracting text from: {filename}")
        raw_text, file_type = self.processor.extract_text(file_path, filename)

        if not raw_text.strip():
            return (
                "Document appears to be empty.",
                f"The uploaded document '{filename}' could not be read or is empty.",
                {},
            )

        # Step 2: Summarize if long
        summary = raw_text
        if len(raw_text) > 2000:
            self.log(f"Document is long ({len(raw_text)} chars), summarizing...")
            prompt = SUMMARIZE_PROMPT.format(
                filename=filename,
                content=raw_text[:8000],
            )
            summary = await self._generate(prompt=prompt, task_type=TaskType.SUMMARIZATION)

        # Step 3: Extract requirements
        requirements = await self.req_agent.extract_from_document(raw_text, filename)

        # Step 4: Build context message for the conversation
        context_message = (
            f"I've reviewed the document '{filename}'.\n\n"
            f"Here's what I found:\n{summary}\n\n"
            f"Based on this, I'll update my understanding of your requirements."
        )

        self.log(f"Document processed: {file_type}, {len(raw_text)} chars")
        return summary, context_message, requirements
