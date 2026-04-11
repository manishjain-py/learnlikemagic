"""Repository for pre-computed explanation variants (topic_explanations table)."""
from uuid import uuid4
from typing import Optional
from pydantic import BaseModel, ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession
from shared.models.entities import TeachingGuideline, TopicExplanation


class CardVisualExplanation(BaseModel):
    """Pre-computed PixiJS visual for an explanation card."""
    output_type: str  # static_visual or animated_visual
    title: Optional[str] = None
    visual_summary: Optional[str] = None  # One-sentence description for tutor context
    visual_spec: Optional[str] = None  # Structured spec for debugging/retry
    pixi_code: Optional[str] = None  # Executable PixiJS v8 JavaScript code


class MatchPair(BaseModel):
    """A single left-right pair in a match activity."""
    left: str
    right: str


class BucketItem(BaseModel):
    """An item to sort into a bucket."""
    text: str
    correct_bucket: int  # 0 or 1 — index into bucket_names


class CheckInActivity(BaseModel):
    """Interactive check-in activity embedded in a check-in card.
    Supports 11 types: pick_one, true_false, fill_blank, match_pairs, sort_buckets,
    sequence, spot_the_error, odd_one_out, predict_then_reveal, swipe_classify,
    tap_to_eliminate.
    """
    activity_type: str = "match_pairs"
    instruction: str
    hint: str
    success_message: str
    audio_text: str

    # pick_one / fill_blank
    options: Optional[list[str]] = None
    correct_index: Optional[int] = None

    # true_false
    statement: Optional[str] = None
    correct_answer: Optional[bool] = None

    # match_pairs
    pairs: Optional[list[MatchPair]] = None

    # sort_buckets / swipe_classify
    bucket_names: Optional[list[str]] = None
    bucket_items: Optional[list[BucketItem]] = None

    # sequence
    sequence_items: Optional[list[str]] = None

    # spot_the_error
    error_steps: Optional[list[str]] = None
    error_index: Optional[int] = None

    # odd_one_out
    odd_items: Optional[list[str]] = None
    odd_index: Optional[int] = None

    # predict_then_reveal (uses options + correct_index for predictions)
    reveal_text: Optional[str] = None

    # tap_to_eliminate (uses options + correct_index, with 4-5 options)


class ExplanationLine(BaseModel):
    """A single display line within a card, paired with its TTS-friendly audio version."""
    display: str  # Markdown line shown on screen
    audio: str    # TTS-friendly spoken version (LLM-generated, no symbols/markdown)


class ExplanationCard(BaseModel):
    """Validated schema for cards stored in cards_json."""
    card_id: Optional[str] = None  # Stable UUID, assigned by enrichment pipelines
    card_idx: int
    card_type: str  # concept, example, visual, analogy, summary, welcome, check_in
    title: str
    lines: list[ExplanationLine] = []  # Per-line display+audio pairs
    content: str  # Derived from joining lines[].display
    visual: Optional[str] = None
    audio_text: Optional[str] = None  # Derived from joining lines[].audio
    visual_explanation: Optional[CardVisualExplanation] = None  # Pre-computed PixiJS visual
    check_in: Optional[CheckInActivity] = None  # Populated for card_type="check_in"


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

    def get_variant_counts_for_chapter(self, book_id: str, chapter_key: str) -> dict[str, int]:
        """Returns {guideline_id: variant_count} for all guidelines in a chapter."""
        rows = (
            self.db.query(
                TopicExplanation.guideline_id,
                func.count(TopicExplanation.id).label("cnt"),
            )
            .join(TeachingGuideline, TeachingGuideline.id == TopicExplanation.guideline_id)
            .filter(
                TeachingGuideline.book_id == book_id,
                TeachingGuideline.chapter_key == chapter_key,
            )
            .group_by(TopicExplanation.guideline_id)
            .all()
        )
        return {row.guideline_id: row.cnt for row in rows}

    def delete_by_chapter(self, book_id: str, chapter_key: str) -> int:
        """Delete all explanation variants for every guideline in a chapter."""
        guideline_ids = (
            self.db.query(TeachingGuideline.id)
            .filter(
                TeachingGuideline.book_id == book_id,
                TeachingGuideline.chapter_key == chapter_key,
            )
            .subquery()
        )
        count = (
            self.db.query(TopicExplanation)
            .filter(TopicExplanation.guideline_id.in_(guideline_ids))
            .delete(synchronize_session="fetch")
        )
        self.db.commit()
        return count

    @staticmethod
    def parse_cards(cards_json: list[dict]) -> list[ExplanationCard]:
        """Validate and parse raw JSONB cards into ExplanationCard models.

        Ensures DB data matches the expected schema on read. Raises
        ValidationError if any card is malformed.
        """
        return [ExplanationCard(**card) for card in cards_json]
