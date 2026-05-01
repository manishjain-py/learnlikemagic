"""LLM config service — single source of truth for component→provider→model mapping."""
import logging
from typing import Optional
from sqlalchemy.orm import Session as DBSession

from shared.repositories.llm_config_repository import LLMConfigRepository

logger = logging.getLogger(__name__)


# Component keys that share the `llm_config` table but are managed by a
# different admin surface and use a non-LLM provider vocabulary. Hidden
# from `/admin/llm-config` (and refused on writes there) so the LLM page
# only sees rows whose providers match its dropdown options.
_NON_LLM_COMPONENT_KEYS = frozenset({"tts"})


class LLMConfigNotFoundError(Exception):
    """Raised when LLM config is missing for a component."""
    pass


class LLMConfigService:
    """Reads/writes LLM config from the llm_config DB table. No fallbacks."""

    def __init__(self, db: DBSession):
        self.repo = LLMConfigRepository(db)

    def get_config(self, component_key: str) -> dict:
        """Return {provider, model_id, reasoning_effort} for a component. Raises if missing."""
        if component_key in _NON_LLM_COMPONENT_KEYS:
            raise LLMConfigNotFoundError(
                f"Component '{component_key}' is not an LLM component — "
                f"use the dedicated admin surface for it."
            )
        row = self.repo.get_by_key(component_key)
        if not row:
            raise LLMConfigNotFoundError(
                f"LLM config not found for component '{component_key}'. "
                f"Add it via /admin/llm-config or run 'python db.py --migrate' to seed defaults."
            )
        return {
            "provider": row.provider,
            "model_id": row.model_id,
            "reasoning_effort": row.reasoning_effort or "max",
        }

    def get_all_configs(self) -> list[dict]:
        """Return all LLM-component configs as dicts.

        Hides rows for non-LLM components (e.g. `tts`) that share the
        table but are managed via a separate admin page — their providers
        wouldn't match the LLM provider dropdown anyway, and an admin who
        edited the row here would silently break those features.
        """
        rows = self.repo.get_all()
        return [
            {
                "component_key": r.component_key,
                "provider": r.provider,
                "model_id": r.model_id,
                "reasoning_effort": r.reasoning_effort or "max",
                "description": r.description,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "updated_by": r.updated_by,
            }
            for r in rows
            if r.component_key not in _NON_LLM_COMPONENT_KEYS
        ]

    def update_config(
        self,
        component_key: str,
        provider: str,
        model_id: str,
        reasoning_effort: str = "max",
        updated_by: Optional[str] = None,
    ) -> dict:
        """Update provider+model+reasoning_effort for a component."""
        if component_key in _NON_LLM_COMPONENT_KEYS:
            raise LLMConfigNotFoundError(
                f"Component '{component_key}' is not editable from the LLM "
                f"config endpoint — use its dedicated admin surface."
            )
        row = self.repo.upsert(
            component_key, provider, model_id,
            reasoning_effort=reasoning_effort, updated_by=updated_by,
        )
        return {
            "component_key": row.component_key,
            "provider": row.provider,
            "model_id": row.model_id,
            "reasoning_effort": row.reasoning_effort or "max",
            "description": row.description,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "updated_by": row.updated_by,
        }
