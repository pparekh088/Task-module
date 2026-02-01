import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.models import Base, PlanningSession
from app.db.repositories import PlanningRepository
from app.schemas.planner import MessageItem, PlannerChatRequest
from app.services.planner_service import PlannerService
from tests.utils import StubAzureOpenAI, StubFileExtractor, sample_plan_json


@pytest.fixture()
async def db_session(tmp_path) -> AsyncSession:
    db_url = f"sqlite+aiosqlite:///{tmp_path}/planner.db"
    engine = create_async_engine(db_url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_local = async_sessionmaker(engine, expire_on_commit=False)
    async with session_local() as session:
        yield session
    await engine.dispose()


def test_normalize_status_variants():
    normalize = PlannerService._normalize_status
    assert normalize("awaiting_approval", "TASK") == "awaiting_user_approval"
    assert normalize("Approved", "TASK") == "approved"
    assert normalize("canceled", "TASK") == "cancelled"
    assert normalize(None, "TASK") == "awaiting_user_approval"
    assert normalize("unknown", "NON_TASK") == "cancelled"

@pytest.mark.anyio
async def test_handle_chat_persists_plan(db_session: AsyncSession):
    plan_payload = sample_plan_json()
    azure_stub = StubAzureOpenAI(
        {
            "intent": "TASK",
            "assistant_message": "Here is a proposed plan.",
            "plan_json": plan_payload,
            "status": "awaiting_user_approval",
        }
    )
    file_extractor = StubFileExtractor(
        context_text="file context", summaries=[{"blob_ref": "file.csv"}]
    )
    settings = Settings(
        azure_openai_endpoint="https://example.openai.azure.com/",
        azure_openai_api_key="test-key",
        azure_openai_gpt52_deployment="gpt-5.2",
        sql_database_url="sqlite:///./ignored.db",
    )
    service = PlannerService(settings, azure_stub, file_extractor, PlanningRepository())

    request = PlannerChatRequest(
        messages=[MessageItem(role="user", content="Plan this task.")],
        uploaded_files=["file.csv"],
    )
    response = await service.handle_chat(request, db_session, redis_client=None)

    assert response.intent == "TASK"
    assert response.status == "awaiting_user_approval"
    assert response.plan_json is not None
    assert response.plan_json.plan_id == plan_payload["plan_id"]
    assert response.plan_json.steps[0].tool_used == "azure-blob-storage"
    assert file_extractor.last_uploaded_files == ["file.csv"]
    assert response.file_context_used is not None

    result = await db_session.execute(
        select(PlanningSession).where(PlanningSession.task_id == response.task_id)
    )
    stored = result.scalar_one_or_none()
    assert stored is not None
    assert stored.latest_plan_json["plan_id"] == plan_payload["plan_id"]
