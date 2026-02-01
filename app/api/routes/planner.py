from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_client import get_redis
from app.db.session import get_db
from app.schemas.planner import PlannerChatRequest, PlannerChatResponse
from app.services.planner_service import PlannerService

router = APIRouter()


@router.post("/planner/chat", response_model=PlannerChatResponse)
async def planner_chat(
    request: PlannerChatRequest,
    db: AsyncSession = Depends(get_db),
    redis_client: Redis | None = Depends(get_redis),
    planner_service: PlannerService = Depends(PlannerService.from_dependency),
) -> PlannerChatResponse:
    try:
        return await planner_service.handle_chat(
            request=request,
            db=db,
            redis_client=redis_client,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
