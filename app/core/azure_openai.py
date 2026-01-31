import base64
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openai import AzureOpenAI

from app.core.config import Settings


@dataclass
class ChatResult:
    content: str
    raw: Any


class AzureOpenAIClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.azure_openai_endpoint or not settings.azure_openai_api_key:
            raise ValueError("Azure OpenAI configuration is missing.")

        self._settings = settings
        self._client = AzureOpenAI(
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
        )

    def chat_completion(
        self,
        deployment: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        expect_json: bool = False,
    ) -> ChatResult:
        response_format = {"type": "json_object"} if expect_json else None
        response = self._client.chat.completions.create(
            model=deployment,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        content = response.choices[0].message.content or ""
        return ChatResult(content=content, raw=response)

    def vision_ocr(self, image_bytes: bytes, content_type: str) -> str:
        if not self._settings.azure_openai_vision_deployment:
            raise ValueError("Azure OpenAI vision deployment is not configured.")

        encoded = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{content_type};base64,{encoded}"
        messages = [
            {
                "role": "system",
                "content": "You are an OCR engine. Extract all text verbatim.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract the text from this image."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ]
        response = self._client.chat.completions.create(
            model=self._settings.azure_openai_vision_deployment,
            messages=messages,
            temperature=0.0,
            max_tokens=800,
        )
        return response.choices[0].message.content or ""


def parse_json_response(content: str) -> Dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(content[start : end + 1])
