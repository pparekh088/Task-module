from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.db.models import PlannerMessage, PlanningSession


class PlanningRepository:
    def get_or_create_session(self, db: Session, task_id: str) -> PlanningSession:
        session = db.query(PlanningSession).filter(PlanningSession.task_id == task_id).first()
        if session:
            return session
        session = PlanningSession(task_id=task_id, status="awaiting_user_approval")
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def update_session(
        self,
        db: Session,
        task_id: str,
        status: str,
        plan_json: Optional[dict[str, Any]],
    ) -> PlanningSession:
        session = db.query(PlanningSession).filter(PlanningSession.task_id == task_id).first()
        if not session:
            session = PlanningSession(task_id=task_id)
            db.add(session)
        session.status = status
        session.latest_plan_json = plan_json
        session.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(session)
        return session

    def add_message(self, db: Session, task_id: str, role: str, content: str) -> PlannerMessage:
        message = PlannerMessage(task_id=task_id, role=role, content=content)
        db.add(message)
        db.commit()
        db.refresh(message)
        return message
