"""Repository for pre-computed Baatcheet dialogues (topic_dialogues table)."""
from uuid import uuid4
from typing import Literal, Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from shared.models.entities import TopicDialogue, TopicExplanation
from shared.repositories.explanation_repository import (
    CardVisualExplanation,
    CheckInActivity,
    ExplanationLine,
)
from shared.utils.dialogue_hash import compute_explanation_content_hash


DialogueCardType = Literal[
    "welcome", "tutor_turn", "peer_turn", "visual", "check_in", "summary",
]
SpeakerKey = Literal["tutor", "peer"]


class DialogueCard(BaseModel):
    """Validated schema for cards stored in topic_dialogues.cards_json.

    Reuses ExplanationLine, CardVisualExplanation, CheckInActivity from
    explanation_repository so the display+audio split and 11 check-in types
    don't drift between modes. Only Baatcheet-specific fields are added at
    the card level: speaker, speaker_name, includes_student_name, visual_intent.
    """
    card_id: Optional[str] = None
    card_idx: int
    card_type: DialogueCardType
    speaker: Optional[SpeakerKey] = None
    speaker_name: Optional[str] = None
    title: Optional[str] = None
    lines: list[ExplanationLine] = []
    audio_url: Optional[str] = None
    includes_student_name: bool = False
    visual: Optional[str] = None
    visual_intent: Optional[str] = None
    visual_explanation: Optional[CardVisualExplanation] = None
    check_in: Optional[CheckInActivity] = None


class DialogueRepository:
    """CRUD for topic_dialogues. Mirrors ExplanationRepository.

    Lives in shared/ so both ingestion (book_ingestion_v2) and tutor runtime
    can read it without cross-module imports.
    """

    def __init__(self, db: DBSession):
        self.db = db

    def get_by_guideline_id(self, guideline_id: str) -> Optional[TopicDialogue]:
        return (
            self.db.query(TopicDialogue)
            .filter(TopicDialogue.guideline_id == guideline_id)
            .first()
        )

    def upsert(
        self,
        guideline_id: str,
        cards_json: list[dict],
        generator_model: Optional[str],
        source_variant_key: str = "A",
        source_explanation_id: Optional[str] = None,
        source_content_hash: Optional[str] = None,
        plan_json: Optional[dict] = None,
    ) -> TopicDialogue:
        """Delete-then-insert. Same pattern as ExplanationRepository.upsert."""
        self.db.query(TopicDialogue).filter(
            TopicDialogue.guideline_id == guideline_id
        ).delete()
        d = TopicDialogue(
            id=str(uuid4()),
            guideline_id=guideline_id,
            cards_json=cards_json,
            plan_json=plan_json,
            generator_model=generator_model,
            source_variant_key=source_variant_key,
            source_explanation_id=source_explanation_id,
            source_content_hash=source_content_hash,
        )
        self.db.add(d)
        self.db.commit()
        self.db.refresh(d)
        return d

    def delete_by_guideline_id(self, guideline_id: str) -> int:
        count = (
            self.db.query(TopicDialogue)
            .filter(TopicDialogue.guideline_id == guideline_id)
            .delete()
        )
        self.db.commit()
        return count

    def has_dialogue(self, guideline_id: str) -> bool:
        return (
            self.db.query(TopicDialogue.id)
            .filter(TopicDialogue.guideline_id == guideline_id)
            .first()
        ) is not None

    def is_stale(self, guideline_id: str) -> bool:
        """True iff variant A's current semantic content hash differs from the
        hash stored at dialogue generation time.

        Returns False when no dialogue exists, no variant A exists, or the
        stored hash is missing — those states are surfaced separately by the
        pipeline status service so they don't masquerade as staleness.
        """
        dialogue = self.get_by_guideline_id(guideline_id)
        if not dialogue or not dialogue.source_content_hash:
            return False
        variant_a = (
            self.db.query(TopicExplanation)
            .filter(
                TopicExplanation.guideline_id == guideline_id,
                TopicExplanation.variant_key == "A",
            )
            .first()
        )
        if not variant_a:
            return False
        current = compute_explanation_content_hash(
            variant_a.cards_json, variant_a.summary_json,
        )
        return current != dialogue.source_content_hash

    @staticmethod
    def parse_cards(cards_json: list[dict]) -> list[DialogueCard]:
        return [DialogueCard(**c) for c in cards_json]
