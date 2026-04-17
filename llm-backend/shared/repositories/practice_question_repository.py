"""Repository for practice question bank (practice_questions table)."""
from typing import Optional
from uuid import uuid4
from sqlalchemy.orm import Session as DBSession
from shared.models.entities import PracticeQuestion


class PracticeQuestionRepository:
    """CRUD for the offline practice question bank.

    Written by the book_ingestion_v2 bank generator; read by the runtime
    practice service during set selection. Lives in shared/ so both modules
    can use it without a cross-module import.
    """

    def __init__(self, db: DBSession):
        self.db = db

    def list_by_guideline(self, guideline_id: str) -> list[PracticeQuestion]:
        """All questions in the bank for a topic, ordered by id (stable)."""
        return (
            self.db.query(PracticeQuestion)
            .filter(PracticeQuestion.guideline_id == guideline_id)
            .order_by(PracticeQuestion.id)
            .all()
        )

    def count_by_guideline(self, guideline_id: str) -> int:
        return (
            self.db.query(PracticeQuestion)
            .filter(PracticeQuestion.guideline_id == guideline_id)
            .count()
        )

    def bulk_insert(
        self,
        guideline_id: str,
        questions: list[dict],
        generator_model: Optional[str] = None,
    ) -> int:
        """Insert a full bank for a topic. Each dict must contain
        `format`, `difficulty`, `concept_tag`, and `question_json`.
        Commits. Returns the number of rows inserted.
        """
        rows = [
            PracticeQuestion(
                id=str(uuid4()),
                guideline_id=guideline_id,
                format=q["format"],
                difficulty=q["difficulty"],
                concept_tag=q["concept_tag"],
                question_json=q["question_json"],
                generator_model=generator_model,
            )
            for q in questions
        ]
        self.db.add_all(rows)
        self.db.commit()
        return len(rows)

    def delete_by_guideline(self, guideline_id: str) -> int:
        """Wipe the bank for a topic. Used by force-regenerate.
        CASCADE on the FK would also handle guideline deletion; this is for
        in-place bank refresh while keeping the guideline.
        """
        count = (
            self.db.query(PracticeQuestion)
            .filter(PracticeQuestion.guideline_id == guideline_id)
            .delete()
        )
        self.db.commit()
        return count
