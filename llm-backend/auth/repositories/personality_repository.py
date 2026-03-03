"""Data access layer for kid personalities (LLM-derived)."""

import logging
from typing import Optional
from uuid import uuid4
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import desc
from shared.models.entities import KidPersonality

logger = logging.getLogger(__name__)


class PersonalityRepository:
    """CRUD operations for the kid_personalities table."""

    def __init__(self, db: DBSession):
        self.db = db

    def create(self, user_id: str, inputs_hash: str, generator_model: str) -> KidPersonality:
        """Create a new personality row with status='generating', auto-increment version."""
        latest = self.get_latest(user_id)
        next_version = (latest.version + 1) if latest else 1

        personality = KidPersonality(
            id=str(uuid4()),
            user_id=user_id,
            inputs_hash=inputs_hash,
            generator_model=generator_model,
            version=next_version,
            status="generating",
        )
        self.db.add(personality)
        self.db.commit()
        self.db.refresh(personality)
        return personality

    def get_latest(self, user_id: str) -> Optional[KidPersonality]:
        """Get the latest personality (any status) for a user."""
        return self.db.query(KidPersonality).filter(
            KidPersonality.user_id == user_id
        ).order_by(desc(KidPersonality.version)).first()

    def get_latest_ready(self, user_id: str) -> Optional[KidPersonality]:
        """Get the latest personality with status='ready'."""
        return self.db.query(KidPersonality).filter(
            KidPersonality.user_id == user_id,
            KidPersonality.status == "ready",
        ).order_by(desc(KidPersonality.version)).first()

    def update_status(self, personality_id: str, status: str,
                      personality_json: dict = None, tutor_brief: str = None):
        """Update a personality row after LLM call completes."""
        personality = self.db.query(KidPersonality).filter(
            KidPersonality.id == personality_id
        ).first()
        if not personality:
            logger.warning("update_status: personality row %s not found", personality_id)
            return
        personality.status = status
        if personality_json is not None:
            personality.personality_json = personality_json
        if tutor_brief is not None:
            personality.tutor_brief = tutor_brief
        self.db.commit()

    def get_latest_hash(self, user_id: str) -> Optional[str]:
        """Returns inputs_hash of latest personality (for skip check)."""
        latest = self.get_latest(user_id)
        return latest.inputs_hash if latest else None
