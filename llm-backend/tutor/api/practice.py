"""Practice runtime REST API — thin HTTP wrapper around PracticeService.

All endpoints require an authenticated user. Ownership is enforced by the
service (attempt.user_id == current_user.id); we never trust a user_id
passed in the request body.

Route ordering note: `/attempts/recent` and `/attempts/for-topic/{gid}`
must be declared BEFORE `/attempts/{attempt_id}` — FastAPI matches by
declaration order and would otherwise treat "recent" as an attempt_id.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from auth.middleware.auth_middleware import get_current_user
from database import get_db
from shared.repositories.practice_question_repository import PracticeQuestionRepository
from tutor.models.practice import (
    Attempt,
    AttemptResults,
    AttemptSummary,
    PracticeBankEmptyError,
    PracticeConflictError,
    PracticeNotFoundError,
    PracticePermissionError,
)
from tutor.services.practice_service import PracticeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/practice", tags=["practice"])


# ─── Request bodies ───────────────────────────────────────────────────────

class StartRequest(BaseModel):
    guideline_id: str


class SaveAnswerRequest(BaseModel):
    q_idx: int
    answer: Any = None


class SubmitRequest(BaseModel):
    final_answers: Optional[Dict[str, Any]] = None


class AvailabilityResponse(BaseModel):
    available: bool
    question_count: int


class RecentAttemptsResponse(BaseModel):
    attempts: list[AttemptSummary]


# ─── Exception → HTTP mapping ─────────────────────────────────────────────

def _call(fn, *args, **kwargs):
    """Invoke a service method and map its custom exceptions to HTTPExceptions.

    Kept as one helper so each handler stays one-liner thin. Re-raises other
    exceptions untouched so FastAPI's default 500 path can log them.
    """
    try:
        return fn(*args, **kwargs)
    except PracticeNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PracticePermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except PracticeConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except PracticeBankEmptyError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


# ─── Start / resume ───────────────────────────────────────────────────────

@router.post("/start", response_model=Attempt)
def start_or_resume(
    body: StartRequest,
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Return the student's active attempt for this topic, creating one if
    needed. Idempotent per (user, topic) while an attempt is in_progress.
    """
    service = PracticeService(db)
    return _call(service.start_or_resume, current_user.id, body.guideline_id)


# ─── Availability (drives ModeSelectPage tile) ────────────────────────────

@router.get("/availability/{guideline_id}", response_model=AvailabilityResponse)
def get_availability(
    guideline_id: str,
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Is practice available for this topic? Backed by a bank-count query —
    doesn't touch the attempt table.
    """
    repo = PracticeQuestionRepository(db)
    count = repo.count_by_guideline(guideline_id)
    return AvailabilityResponse(
        available=count >= 10,
        question_count=count,
    )


# ─── Attempt queries ──────────────────────────────────────────────────────
# NOTE: /attempts/recent and /attempts/for-topic/{gid} MUST be declared
# before /attempts/{attempt_id} — FastAPI's first-match semantics.

@router.get("/attempts/recent", response_model=RecentAttemptsResponse)
def list_recent_unread(
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Banner poll source: graded or grading_failed attempts not yet viewed."""
    service = PracticeService(db)
    return RecentAttemptsResponse(
        attempts=service.list_recent_unread(current_user.id),
    )


@router.get("/attempts/for-topic/{guideline_id}", response_model=list[AttemptSummary])
def list_attempts_for_topic(
    guideline_id: str,
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Per-topic attempt history (FR-45) — newest first."""
    service = PracticeService(db)
    return service.list_attempts(current_user.id, guideline_id)


@router.get("/attempts/{attempt_id}")
def get_attempt(
    attempt_id: str,
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Resolves to a redacted `Attempt` if in_progress/grading, else an
    unredacted `AttemptResults`. Response model left untyped so FastAPI
    serializes whichever DTO the service returns.
    """
    service = PracticeService(db)
    return _call(service.get_attempt, attempt_id, current_user.id)


# ─── Mutations on an attempt ──────────────────────────────────────────────

@router.patch("/attempts/{attempt_id}/answer", status_code=status.HTTP_204_NO_CONTENT)
def save_answer(
    attempt_id: str,
    body: SaveAnswerRequest,
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Debounced per-answer save from the client. Returns 409 if the attempt
    has already been submitted — the client must cancel in-flight PATCHes
    with AbortController before calling /submit.
    """
    service = PracticeService(db)
    _call(service.save_answer, attempt_id, body.q_idx, body.answer, current_user.id)


@router.post("/attempts/{attempt_id}/submit", response_model=Attempt)
def submit_attempt(
    attempt_id: str,
    body: SubmitRequest,
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Atomic submit: merges final_answers, flips status → grading, and
    spawns the background grading worker. Returns immediately with the
    flipped attempt; the client polls GET /attempts/{id} to see graded.
    """
    service = PracticeService(db)
    return _call(service.submit, attempt_id, body.final_answers, current_user.id)


@router.post("/attempts/{attempt_id}/retry-grading", status_code=status.HTTP_204_NO_CONTENT)
def retry_grading(
    attempt_id: str,
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Re-trigger grading after a grading_failed state. Flips status back
    to `grading` and respawns the worker.
    """
    service = PracticeService(db)
    _call(service.retry_grading, attempt_id, current_user.id)


@router.post("/attempts/{attempt_id}/mark-viewed", status_code=status.HTTP_204_NO_CONTENT)
def mark_viewed(
    attempt_id: str,
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Stamp results_viewed_at — clears the attempt from the recent-unread
    banner poll.
    """
    service = PracticeService(db)
    _call(service.mark_viewed, attempt_id, current_user.id)
