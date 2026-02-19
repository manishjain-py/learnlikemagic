"""Session data access layer."""
import json
import logging
from typing import Optional
from sqlalchemy.orm import Session as DBSession
from datetime import datetime

from shared.models import Session as SessionModel, TutorState

logger = logging.getLogger(__name__)


class SessionRepository:
    """Repository for session CRUD operations."""

    def __init__(self, db: DBSession):
        self.db = db

    def create(
        self,
        session_id: str,
        state: TutorState
    ) -> SessionModel:
        """
        Create a new session record.

        Args:
            session_id: Unique session identifier
            state: TutorState domain model

        Returns:
            Created SessionModel
        """
        session = SessionModel(
            id=session_id,
            student_json=state.student.model_dump_json(),
            goal_json=state.goal.model_dump_json(),
            state_json=state.model_dump_json(),
            mastery=state.mastery_score,  # Map domain model to database column
            step_idx=state.step_idx,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_by_id(self, session_id: str) -> Optional[SessionModel]:
        """
        Retrieve session by ID.

        Args:
            session_id: Session identifier

        Returns:
            SessionModel if found, None otherwise
        """
        return self.db.query(SessionModel).filter(SessionModel.id == session_id).first()

    def update(self, session_id: str, state: TutorState) -> None:
        """
        Update session state.

        Args:
            session_id: Session identifier
            state: Updated TutorState domain model
        """
        session = self.get_by_id(session_id)
        if session:
            session.state_json = state.model_dump_json()
            session.mastery = state.mastery_score  # Map domain model to database column
            session.step_idx = state.step_idx
            session.updated_at = datetime.utcnow()
            self.db.commit()

    def list_all(self) -> list[dict]:
        """Return lightweight session summaries for all sessions."""
        rows = (
            self.db.query(SessionModel)
            .order_by(SessionModel.created_at.desc())
            .all()
        )
        results = []
        for row in rows:
            try:
                state = json.loads(row.state_json)
            except Exception:
                state = {}

            # Extract topic name
            topic_name = None
            topic = state.get("topic")
            if topic:
                topic_name = topic.get("topic_name") or topic.get("name")

            # Message count: prefer full_conversation_log, fall back to conversation_history
            full_log = state.get("full_conversation_log", [])
            conv_history = state.get("conversation_history", [])
            message_count = len(full_log) if full_log else len(conv_history)

            results.append({
                "session_id": row.id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "topic_name": topic_name,
                "message_count": message_count,
                "mastery": row.mastery or 0.0,
            })
        return results

    def list_by_user(self, user_id: str, subject: Optional[str] = None,
                     offset: int = 0, limit: int = 20) -> list[dict]:
        """List sessions for a specific user, with optional subject filter."""
        query = self.db.query(SessionModel).filter(SessionModel.user_id == user_id)
        if subject:
            query = query.filter(SessionModel.subject == subject)
        rows = query.order_by(SessionModel.created_at.desc()).offset(offset).limit(limit).all()

        results = []
        for row in rows:
            try:
                state = json.loads(row.state_json)
            except Exception:
                state = {}

            topic_name = None
            topic = state.get("topic")
            if topic:
                topic_name = topic.get("topic_name") or topic.get("name")

            results.append({
                "session_id": row.id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "topic_name": topic_name,
                "subject": row.subject,
                "mastery": row.mastery or 0.0,
                "step_idx": row.step_idx or 0,
            })
        return results

    def count_by_user(self, user_id: str, subject: Optional[str] = None) -> int:
        """Count sessions for a specific user."""
        query = self.db.query(SessionModel).filter(SessionModel.user_id == user_id)
        if subject:
            query = query.filter(SessionModel.subject == subject)
        return query.count()

    def get_user_stats(self, user_id: str) -> dict:
        """Get aggregated learning stats for a user."""
        sessions = self.db.query(SessionModel).filter(SessionModel.user_id == user_id).all()
        if not sessions:
            return {
                "total_sessions": 0,
                "average_mastery": 0,
                "topics_covered": [],
                "total_steps": 0,
            }

        total = len(sessions)
        avg_mastery = sum(s.mastery or 0 for s in sessions) / total
        topics = set(s.subject for s in sessions if s.subject)
        total_steps = sum(s.step_idx or 0 for s in sessions)

        return {
            "total_sessions": total,
            "average_mastery": round(avg_mastery, 2),
            "topics_covered": sorted(list(topics)),
            "total_steps": total_steps,
        }

    def delete(self, session_id: str) -> bool:
        """
        Delete a session.

        Args:
            session_id: Session identifier

        Returns:
            True if deleted, False if not found
        """
        session = self.get_by_id(session_id)
        if session:
            self.db.delete(session)
            self.db.commit()
            return True
        return False
