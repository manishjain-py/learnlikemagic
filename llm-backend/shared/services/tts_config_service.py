"""TTS provider configuration — admin DB override + env fallback.

Provider is stored in the `llm_config` table under `component_key='tts'`,
mirroring the LLM provider toggle pattern. Resolution order:
  1. `llm_config` row (admin override; takes effect immediately)
  2. `Settings.tts_provider` env var (bootstrap default)
  3. Hard default `'elevenlabs'` (post-cutover; was `'google_tts'` before PR #7)

The schema reuses `LLMConfig.provider` for the provider value
('google_tts' | 'elevenlabs'). `model_id` is set to a placeholder model
identifier so the row satisfies the table's NOT NULL constraints; it has
no downstream effect today.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from config import get_settings
from shared.repositories.llm_config_repository import LLMConfigRepository

logger = logging.getLogger(__name__)

# Single component_key row holding the TTS provider toggle.
TTS_COMPONENT_KEY = "tts"

# Valid provider strings. Kept in sync with `audio_generation_service`
# and `tutor/api/tts.py` dispatch branches.
VALID_TTS_PROVIDERS = {"google_tts", "elevenlabs"}

# Placeholder model_id stored alongside the provider — `LLMConfig.model_id`
# is NOT NULL but unused for TTS routing. Picked per provider so the row
# stays self-describing for an operator scanning the table.
_PLACEHOLDER_MODEL = {
    "google_tts": "chirp_3_hd",
    "elevenlabs": "eleven_v3",
}


class TTSConfigService:
    """Resolve and update the active TTS provider."""

    def __init__(self, db: DBSession):
        self.db = db
        self.repo = LLMConfigRepository(db)

    def get_provider(self) -> str:
        """Return the active TTS provider, resolving admin row → env → default."""
        row = self.repo.get_by_key(TTS_COMPONENT_KEY)
        if row and row.provider:
            provider = row.provider.strip().lower()
            if provider in VALID_TTS_PROVIDERS:
                return provider
            logger.warning(
                f"Invalid tts provider {row.provider!r} in llm_config — "
                f"falling back to env"
            )
        env_provider = (get_settings().tts_provider or "").strip().lower()
        if env_provider in VALID_TTS_PROVIDERS:
            return env_provider
        return "elevenlabs"

    def update_provider(
        self,
        provider: str,
        updated_by: Optional[str] = None,
    ) -> dict:
        """Persist an admin override. Raises ValueError on unknown provider."""
        provider = (provider or "").strip().lower()
        if provider not in VALID_TTS_PROVIDERS:
            raise ValueError(
                f"Unknown TTS provider {provider!r}; "
                f"expected one of {sorted(VALID_TTS_PROVIDERS)}"
            )
        row = self.repo.upsert(
            component_key=TTS_COMPONENT_KEY,
            provider=provider,
            model_id=_PLACEHOLDER_MODEL[provider],
            reasoning_effort="max",  # column is NOT NULL; unused for TTS
            updated_by=updated_by,
        )
        self.db.commit()
        return {
            "provider": row.provider,
            "model_id": row.model_id,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "updated_by": row.updated_by,
        }


def resolve_tts_provider(db: Optional[DBSession]) -> str:
    """Convenience wrapper for callers that may or may not have a DB session.

    With a DB session: full resolution (admin row → env → default).
    Without: env → default only.
    """
    if db is not None:
        return TTSConfigService(db).get_provider()
    env_provider = (get_settings().tts_provider or "").strip().lower()
    if env_provider in VALID_TTS_PROVIDERS:
        return env_provider
    return "elevenlabs"
