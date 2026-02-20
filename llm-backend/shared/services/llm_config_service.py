"""LLM config service — single source of truth for component→provider→model mapping."""
import logging
from typing import Optional
from sqlalchemy.orm import Session as DBSession

from shared.repositories.llm_config_repository import LLMConfigRepository

logger = logging.getLogger(__name__)


class LLMConfigNotFoundError(Exception):
    """Raised when LLM config is missing for a component."""
    pass


class LLMConfigService:
    """Reads/writes LLM config from the llm_config DB table. No fallbacks."""

    def __init__(self, db: DBSession):
        self.repo = LLMConfigRepository(db)

    def get_config(self, component_key: str) -> dict:
        """Return {provider, model_id} for a component. Raises if missing."""
        row = self.repo.get_by_key(component_key)
        if not row:
            raise LLMConfigNotFoundError(
                f"LLM config not found for component '{component_key}'. "
                f"Add it via /admin/llm-config or run 'python db.py --migrate' to seed defaults."
            )
        return {"provider": row.provider, "model_id": row.model_id}

    def get_all_configs(self) -> list[dict]:
        """Return all configs as dicts."""
        rows = self.repo.get_all()
        return [
            {
                "component_key": r.component_key,
                "provider": r.provider,
                "model_id": r.model_id,
                "description": r.description,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "updated_by": r.updated_by,
            }
            for r in rows
        ]

    def update_config(
        self,
        component_key: str,
        provider: str,
        model_id: str,
        updated_by: Optional[str] = None,
    ) -> dict:
        """Update provider+model for a component. Returns the updated config."""
        row = self.repo.upsert(component_key, provider, model_id, updated_by)
        return {
            "component_key": row.component_key,
            "provider": row.provider,
            "model_id": row.model_id,
            "description": row.description,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "updated_by": row.updated_by,
        }
