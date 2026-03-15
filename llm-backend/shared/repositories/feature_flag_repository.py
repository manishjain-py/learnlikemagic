"""Feature flag data access layer."""
import logging
from typing import Optional
from sqlalchemy.orm import Session as DBSession
from datetime import datetime

from shared.models.entities import FeatureFlag

logger = logging.getLogger(__name__)


class FeatureFlagRepository:
    """Repository for feature_flags CRUD operations."""

    def __init__(self, db: DBSession):
        self.db = db

    def get_all(self) -> list[FeatureFlag]:
        """Return all feature flag rows."""
        return self.db.query(FeatureFlag).order_by(FeatureFlag.flag_name).all()

    def get_by_name(self, flag_name: str) -> Optional[FeatureFlag]:
        """Return a single flag, or None."""
        return self.db.query(FeatureFlag).filter(
            FeatureFlag.flag_name == flag_name
        ).first()

    def upsert(
        self,
        flag_name: str,
        enabled: bool,
        description: Optional[str] = None,
        updated_by: Optional[str] = None,
    ) -> FeatureFlag:
        """Insert or update a feature flag."""
        row = self.get_by_name(flag_name)
        if row:
            row.enabled = enabled
            if description is not None:
                row.description = description
            row.updated_by = updated_by
            row.updated_at = datetime.utcnow()
        else:
            row = FeatureFlag(
                flag_name=flag_name,
                enabled=enabled,
                description=description,
                updated_by=updated_by,
            )
            self.db.add(row)
        self.db.flush()
        return row
