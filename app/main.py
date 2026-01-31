from fastapi import FastAPI

from app.api.routes import planner
from app.core.config import get_settings
from app.db.session import init_db


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)

    app.include_router(planner.router)

    @app.on_event("startup")
    def startup() -> None:
        init_db()

    return app


app = create_app()
