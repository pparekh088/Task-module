import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.azure_openai import AzureOpenAIClient, parse_json_response
from app.core.config import Settings, get_settings
from app.db.repositories import PlanningRepository
from app.schemas.planner import MessageItem, PlanJson, PlannerChatRequest, PlannerChatResponse
from app.services.file_extraction import FileExtractionService


SYSTEM_PROMPT = """You are the Task Planner Service for an enterprise application.
You are NOT a chatbot, executor, or scheduler. You ONLY design workflow plans.

Decide intent:
- If the user request is brainstorming/FAQ/Q&A, set intent="NON_TASK".
- If the request requires workflow execution, set intent="TASK".

If intent="NON_TASK":
- Respond normally in assistant_message.
- plan_json must be null.
- status must be "cancelled".

If intent="TASK":
- Create or update a workflow plan_json that follows the schema below.
- Use only the allowed tool names for tool_used.
- status should be "awaiting_user_approval" unless the user approves or cancels.
- If the user approves, set status="approved" and requires_user_approval=false.
- If the user cancels, set status="cancelled" and plan_json=null.

Allowed tool_used values:
- azure-openai-gpt-5.2
- azure-ai-search
- azure-redis
- azure-blob-storage
- azure-sql-db
- web-search-tool

Plan JSON schema:
{
  "plan_id": "...",
  "task_summary": "...",
  "mode": "TASK",
  "steps": [
    {
      "step_id": "1",
      "name": "...",
      "description": "...",
      "tool_used": "...",
      "inputs": ["..."],
      "outputs": ["..."],
      "dependencies": [],
      "success_criteria": "..."
    }
  ],
  "requires_user_approval": true,
  "status": "awaiting_user_approval"
}

Return ONLY valid JSON with keys:
intent, assistant_message, plan_json, status
"""


@dataclass
class PlannerResult:
    intent: str
    assistant_message: str
    plan_json: Optional[Dict[str, Any]]
    status: str
    file_context_used: Dict[str, Any]


class PlannerService:
    def __init__(
        self,
        settings: Settings,
        azure_openai: AzureOpenAIClient,
        file_extractor: FileExtractionService,
        repository: PlanningRepository,
    ) -> None:
        self._settings = settings
        self._azure_openai = azure_openai
        self._file_extractor = file_extractor
        self._repository = repository

    @classmethod
    def from_dependency(cls) -> "PlannerService":
        settings = get_settings()
        azure_openai = AzureOpenAIClient(settings)
        file_extractor = FileExtractionService(settings, azure_openai)
        repository = PlanningRepository()
        return cls(settings, azure_openai, file_extractor, repository)

    async def handle_chat(
        self,
        request: PlannerChatRequest,
        db: AsyncSession,
        redis_client: Optional[Redis],
    ) -> PlannerChatResponse:
        task_id = request.task_id or str(uuid.uuid4())
        session = await self._repository.get_or_create_session(db, task_id)

        if session.status == "approved" and session.latest_plan_json:
            return PlannerChatResponse(
                task_id=task_id,
                assistant_message="Plan already approved and ready for Executor.",
                plan_json=PlanJson.model_validate(session.latest_plan_json),
                status="approved",
                intent="TASK",
                file_context_used=None,
            )

        for message in request.messages:
            await self._repository.add_message(db, task_id, message.role, message.content)

        file_context = await self._file_extractor.build_file_context(
            request.uploaded_files, redis_client=redis_client
        )
        result = await self._generate_plan(
            messages=request.messages,
            task_id=task_id,
            file_context=file_context.context_text,
            current_plan=session.latest_plan_json,
        )

        await self._repository.add_message(db, task_id, "assistant", result.assistant_message)

        plan_model: Optional[PlanJson] = None
        if result.intent == "TASK" and result.plan_json:
            plan_model = PlanJson.model_validate(result.plan_json)
            plan_data = plan_model.model_dump()
            status = result.status
            if plan_data.get("status") != status:
                plan_data["status"] = status
            await self._repository.update_session(db, task_id, status=status, plan_json=plan_data)
        else:
            await self._repository.update_session(db, task_id, status="cancelled", plan_json=None)

        if redis_client:
            cache_payload = {
                "task_id": task_id,
                "status": result.status,
                "intent": result.intent,
                "plan_json": result.plan_json,
            }
            await redis_client.set(f"planner:session:{task_id}", json.dumps(cache_payload))

        return PlannerChatResponse(
            task_id=task_id,
            assistant_message=result.assistant_message,
            plan_json=plan_model,
            status=result.status,
            intent=result.intent,
            file_context_used={
                "summaries": file_context.summaries,
                "context_truncated": len(file_context.context_text)
                >= self._settings.max_file_context_chars,
            }
            if request.uploaded_files
            else None,
        )

    async def _generate_plan(
        self,
        messages: List[MessageItem],
        task_id: str,
        file_context: str,
        current_plan: Optional[Dict[str, Any]],
    ) -> PlannerResult:
        if not self._settings.azure_openai_gpt52_deployment:
            raise RuntimeError("Azure OpenAI GPT-5.2 deployment is not configured.")

        model_messages: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        model_messages.append({"role": "system", "content": f"Task ID: {task_id}"})
        if file_context:
            model_messages.append(
                {
                    "role": "system",
                    "content": f"Extracted file context:\n{file_context}",
                }
            )
        else:
            model_messages.append(
                {"role": "system", "content": "No uploaded file context was provided."}
            )
        if current_plan:
            model_messages.append(
                {
                    "role": "system",
                    "content": f"Current plan JSON (for updates):\n{json.dumps(current_plan)}",
                }
            )

        model_messages.extend([message.model_dump() for message in messages])

        max_output_tokens = self._settings.planning_max_output_tokens
        if self._settings.planning_max_tokens:
            max_output_tokens = self._settings.planning_max_tokens

        completion = await self._azure_openai.chat_completion(
            deployment=self._settings.azure_openai_gpt52_deployment,
            messages=model_messages,
            max_output_tokens=max_output_tokens,
            temperature=self._settings.planning_temperature,
            expect_json=True,
        )
        payload = parse_json_response(completion.content)

        intent_raw = str(payload.get("intent", "NON_TASK")).upper()
        intent = intent_raw if intent_raw in {"TASK", "NON_TASK"} else "NON_TASK"
        assistant_message = payload.get("assistant_message", "")
        plan_json = payload.get("plan_json")
        status = self._normalize_status(payload.get("status"), intent)

        if intent == "TASK" and not plan_json:
            raise RuntimeError("Planner returned TASK intent without a plan_json.")
        if intent != "TASK":
            plan_json = None
            status = "cancelled"

        return PlannerResult(
            intent=intent,
            assistant_message=assistant_message,
            plan_json=plan_json,
            status=status,
            file_context_used={"length": len(file_context)},
        )

    @staticmethod
    def _normalize_status(status_value: Any, intent: str) -> str:
        if not status_value:
            return "awaiting_user_approval" if intent == "TASK" else "cancelled"
        normalized = str(status_value).strip().lower().replace(" ", "_")
        if normalized in {"awaiting_user_approval", "awaiting_approval"}:
            return "awaiting_user_approval"
        if normalized in {"approved", "approve", "accepted"}:
            return "approved"
        if normalized in {"cancelled", "canceled", "cancel"}:
            return "cancelled"
        return "awaiting_user_approval" if intent == "TASK" else "cancelled"
