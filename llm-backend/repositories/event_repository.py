"""Event logging data access layer."""
import json
from datetime import datetime
from sqlalchemy.orm import Session as DBSession
from typing import List, Dict, Any
from uuid import uuid4

from models import Event


class EventRepository:
    """Repository for event logging operations."""

    def __init__(self, db: DBSession):
        self.db = db

    def log(
        self,
        session_id: str,
        node: str,
        step_idx: int,
        payload: Dict[str, Any]
    ) -> Event:
        """
        Log a graph node execution event.

        Args:
            session_id: Session identifier
            node: Node name (e.g., 'present', 'check', 'advance')
            step_idx: Current step index
            payload: Event data as dictionary

        Returns:
            Created Event model
        """
        event = Event(
            id=str(uuid4()),
            session_id=session_id,
            node=node,
            step_idx=step_idx,
            payload_json=json.dumps(payload),
            created_at=datetime.utcnow()
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def get_for_session(self, session_id: str) -> List[Event]:
        """
        Get all events for a session.

        Args:
            session_id: Session identifier

        Returns:
            List of Event models ordered by step_idx
        """
        return (
            self.db.query(Event)
            .filter(Event.session_id == session_id)
            .order_by(Event.step_idx)
            .all()
        )

    def get_by_node(self, session_id: str, node: str) -> List[Event]:
        """
        Get events for a specific node in a session.

        Args:
            session_id: Session identifier
            node: Node name to filter by

        Returns:
            List of Event models for that node
        """
        return (
            self.db.query(Event)
            .filter(Event.session_id == session_id, Event.node == node)
            .order_by(Event.step_idx)
            .all()
        )
