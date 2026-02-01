from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import planner
from app.core.config import get_settings
from app.db.session import init_db


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db()
        yield

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(planner.router)
    return app


app = create_app()
