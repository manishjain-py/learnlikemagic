"""LLM-based personality derivation from kid enrichment profiles."""

import json
import logging
from sqlalchemy.orm import Session as DBSession

from config import get_settings
from shared.services.llm_service import LLMService, LLMServiceError
from shared.services.llm_config_service import LLMConfigService
from auth.repositories.enrichment_repository import EnrichmentRepository
from auth.repositories.personality_repository import PersonalityRepository
from auth.repositories.user_repository import UserRepository
from auth.services.enrichment_service import EnrichmentService
from auth.prompts.personality_prompts import (
    PERSONALITY_DERIVATION_PROMPT,
    PERSONALITY_JSON_SCHEMA,
    build_enrichment_data_section,
)

logger = logging.getLogger(__name__)


class PersonalityService:
    """Derives kid personality from enrichment profile using LLM."""

    def __init__(self, db: DBSession):
        self.db = db
        self.enrichment_repo = EnrichmentRepository(db)
        self.personality_repo = PersonalityRepository(db)
        self.user_repo = UserRepository(db)

        # Load LLM config
        config = LLMConfigService(db).get_config("personality_derivation")
        settings = get_settings()
        self.llm = LLMService(
            api_key=settings.openai_api_key,
            provider=config["provider"],
            model_id=config["model_id"],
            reasoning_effort=config["reasoning_effort"],
            gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
            anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
        )
        self.model_id = config["model_id"]

    def generate_personality(self, user_id: str):
        """Core generation method: build prompt, call LLM, store result."""
        # Load data
        user = self.user_repo.get_by_id(user_id)
        if not user:
            logger.error(f"User {user_id} not found for personality generation")
            return

        enrichment_dict = self.enrichment_repo.get_all_fields_as_dict(user_id)

        # Compute current hash
        enrichment_service = EnrichmentService(self.db)
        current_hash = enrichment_service.compute_inputs_hash(user_id)

        # Check if regeneration is still needed (debounce re-check)
        latest_hash = self.personality_repo.get_latest_hash(user_id)
        if latest_hash == current_hash:
            logger.info(f"Personality for user {user_id}: hash unchanged, skipping")
            return

        # Create a new row with status=generating
        personality_row = self.personality_repo.create(
            user_id=user_id,
            inputs_hash=current_hash,
            generator_model=self.model_id,
        )

        try:
            # Build prompt
            enrichment_data_section = build_enrichment_data_section(enrichment_dict)
            about_me = user.about_me or "(none)"
            if enrichment_dict.get("parent_notes"):
                about_me = "(see parent_notes in enrichment)"

            prompt = PERSONALITY_DERIVATION_PROMPT.format(
                name=user.name or "(unknown)",
                preferred_name=user.preferred_name or user.name or "(unknown)",
                age=user.age or "(unknown)",
                grade=user.grade or "(unknown)",
                board=user.board or "(unknown)",
                enrichment_data=enrichment_data_section,
                about_me=about_me,
            )

            # Call LLM
            result = self.llm.call(
                prompt=prompt,
                json_mode=True,
                json_schema=PERSONALITY_JSON_SCHEMA,
                schema_name="kid_personality",
            )

            # Parse output
            output_text = result.get("output_text", "")
            if isinstance(output_text, str):
                parsed = json.loads(output_text)
            else:
                parsed = output_text

            # Extract tutor_brief and personality_json
            tutor_brief = parsed.pop("tutor_brief", "")
            personality_json = parsed

            # Update row with result
            self.personality_repo.update_status(
                personality_id=personality_row.id,
                status="ready",
                personality_json=personality_json,
                tutor_brief=tutor_brief,
            )

            logger.info(f"Personality generated for user {user_id} (version {personality_row.version})")

        except (LLMServiceError, json.JSONDecodeError, Exception) as e:
            logger.error(f"Personality generation failed for user {user_id}: {e}")
            self.personality_repo.update_status(
                personality_id=personality_row.id,
                status="failed",
            )

    def get_latest_personality(self, user_id: str):
        """Get the latest personality (any status)."""
        return self.personality_repo.get_latest(user_id)

    def force_regenerate(self, user_id: str):
        """Force regeneration bypassing hash check."""
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return

        enrichment_dict = self.enrichment_repo.get_all_fields_as_dict(user_id)
        if not enrichment_dict:
            return

        enrichment_service = EnrichmentService(self.db)
        current_hash = enrichment_service.compute_inputs_hash(user_id)

        personality_row = self.personality_repo.create(
            user_id=user_id,
            inputs_hash=current_hash,
            generator_model=self.model_id,
        )

        try:
            enrichment_data_section = build_enrichment_data_section(enrichment_dict)
            about_me = user.about_me or "(none)"
            if enrichment_dict.get("parent_notes"):
                about_me = "(see parent_notes in enrichment)"

            prompt = PERSONALITY_DERIVATION_PROMPT.format(
                name=user.name or "(unknown)",
                preferred_name=user.preferred_name or user.name or "(unknown)",
                age=user.age or "(unknown)",
                grade=user.grade or "(unknown)",
                board=user.board or "(unknown)",
                enrichment_data=enrichment_data_section,
                about_me=about_me,
            )

            result = self.llm.call(
                prompt=prompt,
                json_mode=True,
                json_schema=PERSONALITY_JSON_SCHEMA,
                schema_name="kid_personality",
            )

            output_text = result.get("output_text", "")
            parsed = json.loads(output_text) if isinstance(output_text, str) else output_text
            tutor_brief = parsed.pop("tutor_brief", "")

            self.personality_repo.update_status(
                personality_id=personality_row.id,
                status="ready",
                personality_json=parsed,
                tutor_brief=tutor_brief,
            )
        except Exception as e:
            logger.error(f"Force personality regeneration failed for user {user_id}: {e}")
            self.personality_repo.update_status(
                personality_id=personality_row.id,
                status="failed",
            )
