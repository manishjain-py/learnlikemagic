"""Business logic for kid enrichment profiles."""

import hashlib
import json
import logging
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from auth.repositories.enrichment_repository import EnrichmentRepository
from auth.repositories.user_repository import UserRepository
from auth.models.enrichment_schemas import (
    EnrichmentProfileRequest,
    EnrichmentProfileResponse,
    EnrichmentUpdateResponse,
)
from shared.models.entities import KidEnrichmentProfile

logger = logging.getLogger(__name__)

# DB columns for the 4 enrichment sections shown in the UI
_SECTION_CHECKS = [
    # Section 1: Interests & Hobbies
    lambda p: bool(p.interests),
    # Section 2: How They Learn
    lambda p: bool(p.learning_styles),
    # Section 3: What Motivates
    lambda p: bool(p.motivations),
    # Section 4: Challenges
    lambda p: bool(p.growth_areas),
]


class EnrichmentService:
    """Manages enrichment profile CRUD and personality trigger logic."""

    def __init__(self, db: DBSession):
        self.db = db
        self.enrichment_repo = EnrichmentRepository(db)
        self.user_repo = UserRepository(db)

    def get_profile(self, user_id: str) -> EnrichmentProfileResponse:
        """Fetch enrichment profile + personality status."""
        profile = self.enrichment_repo.get_by_user_id(user_id)
        user = self.user_repo.get_by_id(user_id)

        # Check if user has about_me but no parent_notes (for migration prompt)
        has_about_me = False
        if user and user.about_me:
            if not profile or not profile.parent_notes:
                has_about_me = True

        if not profile:
            return EnrichmentProfileResponse(
                sections_filled=0,
                personality_status="none",
                has_about_me=has_about_me,
            )

        # Get personality status
        personality_status = self._get_personality_status(user_id)

        return EnrichmentProfileResponse(
            interests=profile.interests,
            learning_styles=profile.learning_styles,
            motivations=profile.motivations,
            growth_areas=profile.growth_areas,
            parent_notes=profile.parent_notes,
            attention_span=profile.attention_span,
            pace_preference=profile.pace_preference,
            personality_status=personality_status,
            sections_filled=self._count_sections_filled(profile),
            has_about_me=has_about_me,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    def update_profile(self, user_id: str, request: EnrichmentProfileRequest) -> EnrichmentUpdateResponse:
        """Upsert enrichment fields, compute hash, return status."""
        # Build fields dict from request (only non-None fields)
        fields = {}
        for field_name, value in request.model_dump(exclude_unset=True).items():
            if value is not None:
                fields[field_name] = value

        if not fields:
            profile = self.enrichment_repo.get_by_user_id(user_id)
            return EnrichmentUpdateResponse(
                personality_status="unchanged",
                sections_filled=self._count_sections_filled(profile) if profile else 0,
            )

        profile = self.enrichment_repo.upsert(user_id, **fields)

        # Compute inputs hash for personality derivation
        new_hash = self.compute_inputs_hash(user_id)
        should_regen = self.should_regenerate(user_id, new_hash)
        has_data = self.has_meaningful_data(profile)

        if should_regen and has_data:
            personality_status = "generating"
        elif not has_data:
            personality_status = "none"
        else:
            personality_status = "unchanged"

        sections_filled = self._count_sections_filled(profile)

        return EnrichmentUpdateResponse(
            personality_status=personality_status,
            sections_filled=sections_filled,
            inputs_hash=new_hash,
        )

    def compute_inputs_hash(self, user_id: str) -> str:
        """Build canonical JSON from enrichment + basic profile fields, return SHA256."""
        enrichment_dict = self.enrichment_repo.get_all_fields_as_dict(user_id)
        user = self.user_repo.get_by_id(user_id)

        hash_input = {
            "enrichment": enrichment_dict,
            "name": user.name if user else None,
            "preferred_name": user.preferred_name if user else None,
            "age": user.age if user else None,
            "grade": user.grade if user else None,
            "board": user.board if user else None,
            "about_me": user.about_me if user else None,
        }

        canonical = json.dumps(hash_input, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def should_regenerate(self, user_id: str, new_hash: str) -> bool:
        """Compare new hash with latest personality's inputs_hash."""
        # Import here to avoid circular imports (personality_repository added in Phase 2)
        try:
            from auth.repositories.personality_repository import PersonalityRepository
            personality_repo = PersonalityRepository(self.db)
            latest_hash = personality_repo.get_latest_hash(user_id)
            return latest_hash != new_hash
        except ImportError:
            # Phase 2 not yet implemented
            return True

    def has_meaningful_data(self, profile: KidEnrichmentProfile) -> bool:
        """Returns True if any enrichment data exists (sections, open textbox, or session preferences)."""
        if not profile:
            return False
        # Any of the 4 sections, open textbox, or session preferences counts
        if any(check(profile) for check in _SECTION_CHECKS):
            return True
        return bool(profile.parent_notes) or bool(profile.attention_span) or bool(profile.pace_preference)

    def has_meaningful_enrichment_data(self, user_id: str) -> bool:
        """True if user has an enrichment profile with enough data to derive personality."""
        profile = self.enrichment_repo.get_by_user_id(user_id)
        return self.has_meaningful_data(profile)

    def get_latest_personality(self, user_id: str):
        """Return the latest personality row (any status), or None if none exists.

        Read-only path — does not instantiate the LLM stack. Mirrors the pattern
        already used by `_get_personality_status`.
        """
        from auth.repositories.personality_repository import PersonalityRepository
        return PersonalityRepository(self.db).get_latest(user_id)

    def get_pending_regeneration_hash(self, user_id: str) -> Optional[str]:
        """Return new inputs_hash if personality regeneration should be scheduled, else None.

        Triggers when an enrichment profile exists AND the computed hash differs from the
        latest personality's hash. The debounced worker re-checks `has_meaningful_data`
        before calling the LLM, so this does not need to.
        """
        if not self.enrichment_repo.get_by_user_id(user_id):
            return None
        new_hash = self.compute_inputs_hash(user_id)
        if not self.should_regenerate(user_id, new_hash):
            return None
        return new_hash

    def _count_sections_filled(self, profile: KidEnrichmentProfile) -> int:
        """Count how many of the 4 sections have data."""
        if not profile:
            return 0
        return sum(1 for check in _SECTION_CHECKS if check(profile))

    def _get_personality_status(self, user_id: str) -> str:
        """Get the status of the latest personality."""
        try:
            from auth.repositories.personality_repository import PersonalityRepository
            personality_repo = PersonalityRepository(self.db)
            latest = personality_repo.get_latest(user_id)
            return latest.status if latest else "none"
        except ImportError:
            return "none"
