"""Repository for per-student simplification overlays (student_topic_cards table)."""
from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified
from shared.models.entities import StudentTopicCards


class StudentTopicCardsRepository:
    """CRUD operations for student_topic_cards table.

    Stores per-student simplification overlays keyed by card index.
    Written by session_service during tutoring; callers manage the transaction.
    """

    def __init__(self, db: DBSession):
        self.db = db

    def get(self, user_id: str, guideline_id: str, variant_key: str) -> Optional[StudentTopicCards]:
        """Fetch saved simplifications for a student+topic+variant."""
        return (
            self.db.query(StudentTopicCards)
            .filter(
                StudentTopicCards.user_id == user_id,
                StudentTopicCards.guideline_id == guideline_id,
                StudentTopicCards.variant_key == variant_key,
            )
            .first()
        )

    def get_most_recent(self, user_id: str, guideline_id: str) -> Optional[StudentTopicCards]:
        """Fetch the most recently used variant's record for a student+topic."""
        return (
            self.db.query(StudentTopicCards)
            .filter(
                StudentTopicCards.user_id == user_id,
                StudentTopicCards.guideline_id == guideline_id,
            )
            .order_by(StudentTopicCards.updated_at.desc())
            .first()
        )

    def upsert(
        self,
        user_id: str,
        guideline_id: str,
        variant_key: str,
        explanation_id: str,
        card_idx: int,
        simplification: dict,
    ):
        """Add a simplification to the student's saved overlay.

        Does NOT commit -- caller commits the transaction.
        """
        record = self.get(user_id, guideline_id, variant_key)

        if record:
            # Explanation was regenerated -- reset saved simplifications
            if record.explanation_id != explanation_id:
                record.simplifications = {}
                record.explanation_id = explanation_id

            key = str(card_idx)
            if key not in record.simplifications:
                record.simplifications[key] = []
            record.simplifications[key].append(simplification)

            record.updated_at = datetime.utcnow()
            flag_modified(record, "simplifications")
        else:
            record = StudentTopicCards(
                user_id=user_id,
                guideline_id=guideline_id,
                variant_key=variant_key,
                explanation_id=explanation_id,
                simplifications={str(card_idx): [simplification]},
            )
            self.db.add(record)

    def delete_stale(self, user_id: str, guideline_id: str, variant_key: str):
        """Delete a stale record (explanation was regenerated).

        Does NOT commit -- caller commits the transaction.
        """
        self.db.query(StudentTopicCards).filter(
            StudentTopicCards.user_id == user_id,
            StudentTopicCards.guideline_id == guideline_id,
            StudentTopicCards.variant_key == variant_key,
        ).delete()
