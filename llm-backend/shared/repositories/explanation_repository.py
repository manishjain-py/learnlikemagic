"""Repository for pre-computed explanation variants (topic_explanations table)."""
from uuid import uuid4
from typing import Optional
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session as DBSession
from shared.models.entities import TopicExplanation


class ExplanationCard(BaseModel):
    """Validated schema for cards stored in cards_json."""
    card_idx: int
    card_type: str  # concept, example, visual, analogy, summary
    title: str
    content: str
    visual: Optional[str] = None


class ExplanationRepository:
    """CRUD operations for topic_explanations table.

    Written by the ingestion pipeline, read by the tutor session service.
    Lives in shared/ to avoid cross-module dependency (tutor → book_ingestion_v2).
    """

    def __init__(self, db: DBSession):
        self.db = db

    def get_by_guideline_id(self, guideline_id: str) -> list[TopicExplanation]:
        """Returns all variants for a guideline, ordered by variant_key."""
        return (
            self.db.query(TopicExplanation)
            .filter(TopicExplanation.guideline_id == guideline_id)
            .order_by(TopicExplanation.variant_key)
            .all()
        )

    def get_variant(self, guideline_id: str, variant_key: str) -> Optional[TopicExplanation]:
        """Returns a specific variant."""
        return (
            self.db.query(TopicExplanation)
            .filter(
                TopicExplanation.guideline_id == guideline_id,
                TopicExplanation.variant_key == variant_key,
            )
            .first()
        )

    def upsert(
        self,
        guideline_id: str,
        variant_key: str,
        variant_label: str,
        cards_json: list[dict],
        summary_json: Optional[dict],
        generator_model: str,
    ) -> TopicExplanation:
        """Insert or replace a variant (delete existing + insert).

        Uses delete+insert instead of UPDATE to avoid partial state from
        failed updates. The unique constraint ensures no duplicates.
        """
        # Delete existing variant if present
        self.db.query(TopicExplanation).filter(
            TopicExplanation.guideline_id == guideline_id,
            TopicExplanation.variant_key == variant_key,
        ).delete()

        explanation = TopicExplanation(
            id=str(uuid4()),
            guideline_id=guideline_id,
            variant_key=variant_key,
            variant_label=variant_label,
            cards_json=cards_json,
            summary_json=summary_json,
            generator_model=generator_model,
        )
        self.db.add(explanation)
        self.db.commit()
        self.db.refresh(explanation)
        return explanation

    def delete_by_guideline_id(self, guideline_id: str) -> int:
        """Delete all variants for a guideline. Returns count deleted."""
        count = (
            self.db.query(TopicExplanation)
            .filter(TopicExplanation.guideline_id == guideline_id)
            .delete()
        )
        self.db.commit()
        return count

    def has_explanations(self, guideline_id: str) -> bool:
        """Quick existence check — used by session service."""
        return (
            self.db.query(TopicExplanation.id)
            .filter(TopicExplanation.guideline_id == guideline_id)
            .first()
        ) is not None

    @staticmethod
    def parse_cards(cards_json: list[dict]) -> list[ExplanationCard]:
        """Validate and parse raw JSONB cards into ExplanationCard models.

        Ensures DB data matches the expected schema on read. Raises
        ValidationError if any card is malformed.
        """
        return [ExplanationCard(**card) for card in cards_json]
