"""Repository for practice attempts (practice_attempts table)."""
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified
from shared.models.entities import PracticeAttempt


class PracticeAttemptRepository:
    """CRUD for practice attempts.

    Attempts are self-contained: questions_snapshot_json stores the full
    question payload at creation, so bank regeneration can't orphan history.
    The service layer is responsible for SELECT FOR UPDATE + atomic submit;
    this repo exposes primitive operations that commit individually.
    """

    def __init__(self, db: DBSession):
        self.db = db

    # ── Creation ───────────────────────────────────────────────────────────
    def create(
        self,
        user_id: str,
        guideline_id: str,
        question_ids: list[str],
        questions_snapshot_json: list[dict],
        total_possible: int = 10,
    ) -> PracticeAttempt:
        """Insert a new in-progress attempt. May raise IntegrityError if the
        partial unique index (one in_progress attempt per user+guideline) is
        already populated; callers catch that and re-read via get_in_progress.
        """
        attempt = PracticeAttempt(
            id=str(uuid4()),
            user_id=user_id,
            guideline_id=guideline_id,
            question_ids=question_ids,
            questions_snapshot_json=questions_snapshot_json,
            answers_json={},
            total_possible=total_possible,
            status="in_progress",
        )
        self.db.add(attempt)
        self.db.flush()
        self.db.commit()
        self.db.refresh(attempt)
        return attempt

    # ── Reads ──────────────────────────────────────────────────────────────
    def get(self, attempt_id: str) -> Optional[PracticeAttempt]:
        return (
            self.db.query(PracticeAttempt)
            .filter(PracticeAttempt.id == attempt_id)
            .first()
        )

    def get_in_progress(
        self, user_id: str, guideline_id: str
    ) -> Optional[PracticeAttempt]:
        return (
            self.db.query(PracticeAttempt)
            .filter(
                PracticeAttempt.user_id == user_id,
                PracticeAttempt.guideline_id == guideline_id,
                PracticeAttempt.status == "in_progress",
            )
            .first()
        )

    def list_for_user_topic(
        self, user_id: str, guideline_id: str
    ) -> list[PracticeAttempt]:
        """All attempts for one topic, newest first (FR-45).
        Includes both graded and in_progress so the landing page can show Resume
        and past evaluations from a single call if desired.
        """
        return (
            self.db.query(PracticeAttempt)
            .filter(
                PracticeAttempt.user_id == user_id,
                PracticeAttempt.guideline_id == guideline_id,
            )
            .order_by(PracticeAttempt.created_at.desc())
            .all()
        )

    def list_recent_unread(self, user_id: str) -> list[PracticeAttempt]:
        """Attempts the banner should surface: graded or grading_failed, and
        not yet viewed. Matches FR-35 (success) + FR-40 (failure) in one call.
        """
        return (
            self.db.query(PracticeAttempt)
            .filter(
                PracticeAttempt.user_id == user_id,
                PracticeAttempt.status.in_(("graded", "grading_failed")),
                PracticeAttempt.results_viewed_at.is_(None),
            )
            .order_by(PracticeAttempt.submitted_at.desc())
            .all()
        )

    def count_by_user_guideline(self, user_id: str, guideline_id: str) -> int:
        """Number of graded attempts for a topic — scorecard `(N attempts)`."""
        return (
            self.db.query(PracticeAttempt)
            .filter(
                PracticeAttempt.user_id == user_id,
                PracticeAttempt.guideline_id == guideline_id,
                PracticeAttempt.status == "graded",
            )
            .count()
        )

    def latest_graded(
        self, user_id: str, guideline_id: str
    ) -> Optional[PracticeAttempt]:
        """Most recent graded attempt for scorecard latest-score display."""
        return (
            self.db.query(PracticeAttempt)
            .filter(
                PracticeAttempt.user_id == user_id,
                PracticeAttempt.guideline_id == guideline_id,
                PracticeAttempt.status == "graded",
            )
            .order_by(PracticeAttempt.graded_at.desc())
            .first()
        )

    # ── Writes ─────────────────────────────────────────────────────────────
    def save_answer(self, attempt_id: str, q_idx: int, answer: Any) -> None:
        """Merge one answer into answers_json (JSONB requires string keys)."""
        attempt = self.get(attempt_id)
        if attempt is None:
            return
        current = dict(attempt.answers_json or {})
        current[str(q_idx)] = answer
        attempt.answers_json = current
        flag_modified(attempt, "answers_json")
        self.db.commit()

    def mark_submitted(
        self, attempt_id: str, final_answers: Optional[dict] = None
    ) -> Optional[PracticeAttempt]:
        """Flip status `in_progress` → `grading`, stamp submitted_at, and
        optionally merge final answers. The atomic SELECT FOR UPDATE + flip
        lives in the service layer; this is the simpler primitive form.
        """
        attempt = self.get(attempt_id)
        if attempt is None or attempt.status != "in_progress":
            return attempt
        if final_answers:
            merged = dict(attempt.answers_json or {})
            for k, v in final_answers.items():
                merged[str(k)] = v
            attempt.answers_json = merged
            flag_modified(attempt, "answers_json")
        attempt.status = "grading"
        attempt.submitted_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(attempt)
        return attempt

    def mark_grading(self, attempt_id: str) -> None:
        """Flip status → `grading` (used by retry-grading from grading_failed)."""
        attempt = self.get(attempt_id)
        if attempt is None:
            return
        attempt.status = "grading"
        attempt.grading_error = None
        self.db.commit()

    def save_grading(
        self,
        attempt_id: str,
        grading_json: dict,
        total_score: float,
    ) -> None:
        """Write grading results and flip status → `graded`."""
        attempt = self.get(attempt_id)
        if attempt is None:
            return
        attempt.grading_json = grading_json
        attempt.total_score = total_score
        attempt.status = "graded"
        attempt.graded_at = datetime.utcnow()
        attempt.grading_attempts = (attempt.grading_attempts or 0) + 1
        self.db.commit()

    def mark_grading_failed(self, attempt_id: str, error: str) -> None:
        """Flip status → `grading_failed` after retries exhausted."""
        attempt = self.get(attempt_id)
        if attempt is None:
            return
        attempt.status = "grading_failed"
        attempt.grading_error = error
        attempt.grading_attempts = (attempt.grading_attempts or 0) + 1
        self.db.commit()

    def mark_viewed(self, attempt_id: str) -> None:
        """Stamp results_viewed_at — clears this attempt from the banner."""
        attempt = self.get(attempt_id)
        if attempt is None:
            return
        attempt.results_viewed_at = datetime.utcnow()
        self.db.commit()
