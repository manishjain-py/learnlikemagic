"""Pydantic DTOs + exceptions for the practice lifecycle API.

Two distinct response shapes:
  - `Attempt` — redacted view served during the set (no correct answers).
  - `AttemptResults` — unredacted + grading served after submit for the
    review page. Both are built from a single `PracticeAttempt` ORM row.

Exceptions map to HTTP in the Step 8 API layer:
  PracticeNotFoundError  → 404
  PracticePermissionError → 403
  PracticeConflictError  → 409 (e.g. saving an answer after submit)
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# ─── DTOs ─────────────────────────────────────────────────────────────────

class AttemptQuestion(BaseModel):
    """One question as presented to the student — correctness fields stripped.

    `question_json` contains only the display data (question_text, options,
    pair_lefts / pair_rights, bucket_items w/o correct_bucket, etc.).
    `presentation_seed` is consumed by the frontend capture components to
    produce a deterministic shuffle that survives a page reload.
    """
    q_idx: int
    q_id: str
    format: str
    difficulty: str
    concept_tag: str
    presentation_seed: int
    question_json: Dict[str, Any]


class GradedQuestion(BaseModel):
    """One question in the review view — question_json is UNREDACTED, plus
    the student's answer, correctness verdict, fractional score, per-pick
    rationale (if wrong), and FR-43 Pixi-code slot (nullable).
    """
    q_idx: int
    q_id: str
    format: str
    difficulty: str
    concept_tag: str
    question_json: Dict[str, Any]
    student_answer: Any = None
    correct: bool = False
    score: float = 0.0
    correct_answer_summary: Any = None
    rationale: Optional[str] = None
    visual_explanation_code: Optional[str] = None


class Attempt(BaseModel):
    """In-progress or grading-in-progress attempt.
    Served during the set — no correct answers or grading included.
    """
    id: str
    user_id: str
    guideline_id: str
    status: str  # 'in_progress' | 'grading'
    total_possible: int
    questions: List[AttemptQuestion]
    answers: Dict[str, Any]
    created_at: datetime
    submitted_at: Optional[datetime] = None


class AttemptResults(BaseModel):
    """Graded or grading_failed attempt. Served to the review page — fully
    unredacted. If grading failed, `questions` may be empty and
    `grading_error` is set.
    """
    id: str
    user_id: str
    guideline_id: str
    status: str  # 'graded' | 'grading_failed'
    total_possible: int
    total_score: Optional[float] = None
    questions: List[GradedQuestion]
    grading_error: Optional[str] = None
    submitted_at: Optional[datetime] = None
    graded_at: Optional[datetime] = None


class AttemptSummary(BaseModel):
    """Compact list item for history views (FR-45)."""
    id: str
    status: str
    total_score: Optional[float] = None
    total_possible: int
    submitted_at: Optional[datetime] = None
    graded_at: Optional[datetime] = None


# ─── Exceptions ───────────────────────────────────────────────────────────

class PracticeNotFoundError(Exception):
    """Attempt or bank does not exist. → HTTP 404."""


class PracticePermissionError(Exception):
    """Attempt belongs to a different user. → HTTP 403."""


class PracticeConflictError(Exception):
    """State transition not allowed (e.g. save_answer after submit). → HTTP 409."""


class PracticeBankEmptyError(Exception):
    """Topic has no generated bank, or bank is too small for a 10-q set. → HTTP 409."""
