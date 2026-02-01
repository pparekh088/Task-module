import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.models import Base, PlanningSession
from app.db.repositories import PlanningRepository
from app.schemas.planner import MessageItem, PlannerChatRequest
from app.services.planner_service import PlannerService
from tests.utils import StubAzureOpenAI, StubFileExtractor, sample_plan_json


@pytest.fixture()
def db_session(tmp_path):
    db_url = f"sqlite:///{tmp_path}/planner.db"
    engine = create_engine(db_url, connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
    session = session_local()
    try:
        yield session
    finally:
        session.close()


def test_normalize_status_variants():
    normalize = PlannerService._normalize_status
    assert normalize("awaiting_approval", "TASK") == "awaiting_user_approval"
    assert normalize("Approved", "TASK") == "approved"
    assert normalize("canceled", "TASK") == "cancelled"
    assert normalize(None, "TASK") == "awaiting_user_approval"
    assert normalize("unknown", "NON_TASK") == "cancelled"


def test_handle_chat_persists_plan(db_session):
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
    response = service.handle_chat(request, db_session, redis_client=None)

    assert response.intent == "TASK"
    assert response.status == "awaiting_user_approval"
    assert response.plan_json is not None
    assert response.plan_json.plan_id == plan_payload["plan_id"]
    assert response.plan_json.steps[0].tool_used == "azure-blob-storage"
    assert file_extractor.last_uploaded_files == ["file.csv"]
    assert response.file_context_used is not None

    stored = (
        db_session.query(PlanningSession)
        .filter(PlanningSession.task_id == response.task_id)
        .first()
    )
    assert stored is not None
    assert stored.latest_plan_json["plan_id"] == plan_payload["plan_id"]
