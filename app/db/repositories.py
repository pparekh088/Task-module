from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PlannerMessage, PlanningSession


class PlanningRepository:
    async def get_or_create_session(self, db: AsyncSession, task_id: str) -> PlanningSession:
        result = await db.execute(
            select(PlanningSession).where(PlanningSession.task_id == task_id)
        )
        session = result.scalar_one_or_none()
        if session:
            return session
        session = PlanningSession(task_id=task_id, status="awaiting_user_approval")
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session

    async def update_session(
        self,
        db: AsyncSession,
        task_id: str,
        status: str,
        plan_json: Optional[dict[str, Any]],
    ) -> PlanningSession:
        result = await db.execute(
            select(PlanningSession).where(PlanningSession.task_id == task_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            session = PlanningSession(task_id=task_id)
            db.add(session)
        session.status = status
        session.latest_plan_json = plan_json
        session.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(session)
        return session

    async def add_message(
        self, db: AsyncSession, task_id: str, role: str, content: str
    ) -> PlannerMessage:
        message = PlannerMessage(task_id=task_id, role=role, content=content)
        db.add(message)
        await db.commit()
        await db.refresh(message)
        return message
