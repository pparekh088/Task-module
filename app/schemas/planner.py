from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class MessageItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class PlannerChatRequest(BaseModel):
    task_id: Optional[str] = None
    messages: List[MessageItem]
    uploaded_files: List[str] = Field(default_factory=list)


class PlanStep(BaseModel):
    step_id: str
    name: str
    description: str
    tool_used: str
    inputs: List[str]
    outputs: List[str]
    dependencies: List[str]
    success_criteria: str


class ScheduleInfo(BaseModel):
    schedule_type: str
    frequency: str


class TrialRunInfo(BaseModel):
    enabled: bool
    sample_size: Optional[int] = None
    notes: Optional[str] = None


class PlanJson(BaseModel):
    model_config = ConfigDict(extra="allow")

    plan_id: str
    task_summary: str
    mode: Literal["TASK"]
    steps: List[PlanStep]
    requires_user_approval: bool
    status: Literal["awaiting_user_approval", "approved", "cancelled"]
    schedule: Optional[ScheduleInfo] = None
    trial_run: Optional[TrialRunInfo] = None


class PlannerChatResponse(BaseModel):
    task_id: str
    assistant_message: str
    plan_json: Optional[PlanJson] = None
    status: Literal["awaiting_user_approval", "approved", "cancelled"]
    intent: Literal["TASK", "NON_TASK"]
    file_context_used: Optional[Dict[str, Any]] = None
