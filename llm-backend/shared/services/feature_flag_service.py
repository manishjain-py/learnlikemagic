"""Feature flag service — read/write runtime feature toggles."""
import logging
from typing import Optional
from sqlalchemy.orm import Session as DBSession

from shared.repositories.feature_flag_repository import FeatureFlagRepository

logger = logging.getLogger(__name__)


class FeatureFlagService:
    """Reads/writes feature flags from the feature_flags DB table."""

    def __init__(self, db: DBSession):
        self.repo = FeatureFlagRepository(db)

    def flag_exists(self, flag_name: str) -> bool:
        """Return True if the flag exists in the DB."""
        return self.repo.get_by_name(flag_name) is not None

    def is_enabled(self, flag_name: str) -> bool:
        """Return True if the flag exists and is enabled, False otherwise."""
        row = self.repo.get_by_name(flag_name)
        return bool(row and row.enabled)

    def get_all_flags(self) -> list[dict]:
        """Return all flags as dicts."""
        rows = self.repo.get_all()
        return [
            {
                "flag_name": r.flag_name,
                "enabled": r.enabled,
                "description": r.description,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "updated_by": r.updated_by,
            }
            for r in rows
        ]

    def update_flag(
        self,
        flag_name: str,
        enabled: bool,
        updated_by: Optional[str] = None,
    ) -> dict:
        """Toggle a flag on/off. Returns the updated flag."""
        row = self.repo.upsert(flag_name, enabled, updated_by=updated_by)
        return {
            "flag_name": row.flag_name,
            "enabled": row.enabled,
            "description": row.description,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "updated_by": row.updated_by,
        }
