"""Data access layer for kid enrichment profiles."""

from datetime import datetime
from typing import Optional
from uuid import uuid4
from sqlalchemy.orm import Session as DBSession
from shared.models.entities import KidEnrichmentProfile


# All enrichment fields including session preferences (used for hash computation)
ENRICHMENT_FIELDS = [
    "interests", "learning_styles", "motivations",
    "growth_areas", "parent_notes", "attention_span", "pace_preference",
]


class EnrichmentRepository:
    """CRUD operations for the kid_enrichment_profiles table."""

    def __init__(self, db: DBSession):
        self.db = db

    def get_by_user_id(self, user_id: str) -> Optional[KidEnrichmentProfile]:
        return self.db.query(KidEnrichmentProfile).filter(
            KidEnrichmentProfile.user_id == user_id
        ).first()

    def upsert(self, user_id: str, **fields) -> KidEnrichmentProfile:
        """Create or update enrichment profile. Only provided fields are updated."""
        profile = self.get_by_user_id(user_id)
        if not profile:
            profile = KidEnrichmentProfile(
                id=str(uuid4()),
                user_id=user_id,
                created_at=datetime.utcnow(),
            )
            self.db.add(profile)

        for key, value in fields.items():
            if hasattr(profile, key) and value is not None:
                setattr(profile, key, value)

        profile.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(profile)
        return profile

    def get_all_fields_as_dict(self, user_id: str) -> dict:
        """Returns all enrichment fields as a dict (for hash computation)."""
        profile = self.get_by_user_id(user_id)
        if not profile:
            return {}

        result = {}
        for field in ENRICHMENT_FIELDS:
            val = getattr(profile, field, None)
            if val is not None:
                result[field] = val
        return result
