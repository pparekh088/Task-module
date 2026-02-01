import json
from typing import Any, Dict, List, Optional

from app.core.azure_openai import ChatResult
from app.services.file_extraction import FileContext


def sample_plan_json() -> Dict[str, Any]:
    return {
        "plan_id": "plan-123",
        "task_summary": "Summarize and report on uploaded data",
        "mode": "TASK",
        "steps": [
            {
                "step_id": "1",
                "name": "Extract file content",
                "description": "Parse uploaded files into structured rows",
                "tool_used": "azure-blob-storage",
                "inputs": ["uploaded_files"],
                "outputs": ["structured_rows"],
                "dependencies": [],
                "success_criteria": "Rows loaded successfully",
            },
            {
                "step_id": "2",
                "name": "AI analysis",
                "description": "Summarize and analyze extracted rows",
                "tool_used": "azure-openai-gpt-5.2",
                "inputs": ["structured_rows"],
                "outputs": ["analysis_summary"],
                "dependencies": ["1"],
                "success_criteria": "Summary generated for each row",
            },
        ],
        "requires_user_approval": True,
        "status": "awaiting_user_approval",
    }


class StubAzureOpenAI:
    def __init__(self, response_payload: Dict[str, Any]) -> None:
        self.response_payload = response_payload
        self.last_messages: Optional[List[Dict[str, Any]]] = None

    async def chat_completion(  # noqa: D401 - test stub signature
        self,
        deployment: str,
        messages: List[Dict[str, Any]],
        max_output_tokens: int,
        temperature: Optional[float],
        expect_json: bool = False,
    ) -> ChatResult:
        self.last_messages = messages
        content = json.dumps(self.response_payload)
        return ChatResult(content=content, raw={"stubbed": True})

    async def vision_ocr(self, image_bytes: bytes, content_type: str) -> str:
        return ""


class StubFileExtractor:
    def __init__(self, context_text: str = "context", summaries: Optional[List[Dict[str, Any]]] = None) -> None:
        self.context_text = context_text
        self.summaries = summaries or []
        self.last_uploaded_files: Optional[List[str]] = None

    async def build_file_context(self, uploaded_files: List[str]) -> FileContext:
        self.last_uploaded_files = uploaded_files
        return FileContext(context_text=self.context_text, summaries=self.summaries)
