from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, get_settings
from app.db.models import Base
from app.db.repositories import PlanningRepository
from app.db.session import get_db
from app.main import create_app
from app.services.planner_service import PlannerService
from app.cache.redis_client import get_redis
from tests.utils import StubAzureOpenAI, StubFileExtractor, sample_plan_json


def test_planner_chat_endpoint(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path}/planner.db"
    monkeypatch.setenv("SQL_DATABASE_URL", db_url)
    monkeypatch.setenv("APP_NAME", "task-planner-service")
    get_settings.cache_clear()

    engine = create_engine(db_url, connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
    session = session_local()

    plan_payload = sample_plan_json()
    azure_stub = StubAzureOpenAI(
        {
            "intent": "TASK",
            "assistant_message": "Plan ready for review.",
            "plan_json": plan_payload,
            "status": "awaiting_user_approval",
        }
    )
    file_extractor = StubFileExtractor(context_text="", summaries=[])
    settings = Settings(
        azure_openai_endpoint="https://example.openai.azure.com/",
        azure_openai_api_key="test-key",
        azure_openai_gpt52_deployment="gpt-5.2",
        sql_database_url=db_url,
    )
    planner_service = PlannerService(settings, azure_stub, file_extractor, PlanningRepository())

    app = create_app()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = lambda: None
    app.dependency_overrides[PlannerService.from_dependency] = lambda: planner_service

    client = TestClient(app)
    response = client.post(
        "/planner/chat",
        json={
            "messages": [{"role": "user", "content": "Create a workflow plan."}],
            "uploaded_files": [],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "TASK"
    assert payload["status"] == "awaiting_user_approval"
    assert payload["plan_json"]["plan_id"] == plan_payload["plan_id"]

    session.close()
