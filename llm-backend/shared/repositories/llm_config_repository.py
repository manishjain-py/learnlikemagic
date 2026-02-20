"""LLM config data access layer."""
import logging
from typing import Optional
from sqlalchemy.orm import Session as DBSession
from datetime import datetime

from shared.models.entities import LLMConfig

logger = logging.getLogger(__name__)


class LLMConfigRepository:
    """Repository for llm_config CRUD operations."""

    def __init__(self, db: DBSession):
        self.db = db

    def get_all(self) -> list[LLMConfig]:
        """Return all LLM config rows."""
        return self.db.query(LLMConfig).order_by(LLMConfig.component_key).all()

    def get_by_key(self, component_key: str) -> Optional[LLMConfig]:
        """Return config for a specific component, or None."""
        return self.db.query(LLMConfig).filter(
            LLMConfig.component_key == component_key
        ).first()

    def upsert(
        self,
        component_key: str,
        provider: str,
        model_id: str,
        updated_by: Optional[str] = None,
    ) -> LLMConfig:
        """Insert or update a config row."""
        row = self.get_by_key(component_key)
        if row:
            row.provider = provider
            row.model_id = model_id
            row.updated_by = updated_by
            row.updated_at = datetime.utcnow()
        else:
            row = LLMConfig(
                component_key=component_key,
                provider=provider,
                model_id=model_id,
                updated_by=updated_by,
            )
            self.db.add(row)
        self.db.flush()
        return row
