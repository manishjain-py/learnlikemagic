"""Practice lifecycle service — the source of truth between the REST API
(Step 8) and the persisted attempt state.

Responsibilities:
  - Set selection + snapshot at attempt creation (start_or_resume)
  - Per-answer save with ownership + status guards (save_answer)
  - Atomic submit with SELECT FOR UPDATE (submit) + background grading worker
  - Redaction of correctness fields before serving mid-set (redact_for_student)

State machine (per attempt):
    in_progress --submit--> grading --worker--> graded
                                              \\-> grading_failed

Concurrent-tab start race is handled in start_or_resume via IntegrityError
catch on the partial unique index — the losing caller re-reads the winner.

Silent grading-thread death is NOT mitigated in v1 per locked-decisions.
A 5-minute sweeper is post-v1 cleanup.
"""
import logging
import random
import threading
from datetime import datetime
from typing import Any, Optional, Union

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

from shared.models.entities import PracticeAttempt, PracticeQuestion
from shared.repositories.practice_attempt_repository import PracticeAttemptRepository
from shared.repositories.practice_question_repository import PracticeQuestionRepository
from tutor.models.practice import (
    Attempt,
    AttemptQuestion,
    AttemptResults,
    AttemptSummary,
    GradedQuestion,
    PracticeBankEmptyError,
    PracticeConflictError,
    PracticeNotFoundError,
    PracticePermissionError,
)

logger = logging.getLogger(__name__)

# Target set composition: 3 easy / 5 medium / 2 hard (FR-22)
SET_SIZE = 10
DIFFICULTY_TARGETS = {"easy": 3, "medium": 5, "hard": 2}

# Correctness fields stripped when serving mid-set (FR-26)
REDACT_TOP_LEVEL_KEYS = {
    "correct_index",
    "correct_answer_bool",
    "expected_answer",
    "grading_rubric",
    "explanation_why",
    "error_index",
    "odd_index",
    "reveal_text",  # predict_then_reveal's post-pick explanation
}


class PracticeService:
    """Runtime service for one student's practice attempts on one topic."""

    def __init__(self, db: DBSession):
        self.db = db
        self.attempt_repo = PracticeAttemptRepository(db)
        self.question_repo = PracticeQuestionRepository(db)

    # ─── Public API ───────────────────────────────────────────────────────

    def start_or_resume(self, user_id: str, guideline_id: str) -> Attempt:
        """Return the student's active attempt for this topic, creating one if
        needed. Idempotent per user+topic while an attempt is in_progress.
        """
        existing = self.attempt_repo.get_in_progress(user_id, guideline_id)
        if existing is not None:
            return self._to_attempt_dto(existing, redact=True)

        bank = self.question_repo.list_by_guideline(guideline_id)
        if len(bank) < SET_SIZE:
            raise PracticeBankEmptyError(
                f"Practice bank for topic {guideline_id} has only {len(bank)} "
                f"questions; need at least {SET_SIZE}"
            )

        picked = self._select_set(bank)
        snapshots = [self._snapshot_question(q) for q in picked]
        question_ids = [q.id for q in picked]

        try:
            attempt = self.attempt_repo.create(
                user_id=user_id,
                guideline_id=guideline_id,
                question_ids=question_ids,
                questions_snapshot_json=snapshots,
                total_possible=SET_SIZE,
            )
        except IntegrityError:
            # Concurrent-tab race: another request already inserted the row.
            self.db.rollback()
            winner = self.attempt_repo.get_in_progress(user_id, guideline_id)
            if winner is None:
                raise
            return self._to_attempt_dto(winner, redact=True)

        return self._to_attempt_dto(attempt, redact=True)

    def save_answer(
        self, attempt_id: str, q_idx: int, answer: Any, user_id: str
    ) -> None:
        """Merge one in-progress answer into answers_json. Raises
        PracticeConflictError if the attempt has already been submitted —
        frontend should cancel its debounced PATCH before calling submit.
        """
        attempt = self._get_owned(attempt_id, user_id)
        if attempt.status != "in_progress":
            raise PracticeConflictError(
                f"Cannot save answer: attempt status is {attempt.status!r}"
            )
        self.attempt_repo.save_answer(attempt_id, q_idx, answer)

    def submit(
        self, attempt_id: str, final_answers: Optional[dict], user_id: str
    ) -> Attempt:
        """Flip status in_progress→grading atomically, merge the client's
        final answer state (kills the debounce race), then spawn the
        background grading worker. Returns the flipped attempt.
        """
        try:
            attempt = (
                self.db.query(PracticeAttempt)
                .filter(PracticeAttempt.id == attempt_id)
                .with_for_update()
                .first()
            )
            if attempt is None:
                raise PracticeNotFoundError(f"Attempt {attempt_id} not found")
            if attempt.user_id != user_id:
                raise PracticePermissionError(
                    f"Attempt {attempt_id} not owned by user {user_id}"
                )
            if attempt.status != "in_progress":
                raise PracticeConflictError(
                    f"Cannot submit: attempt status is {attempt.status!r}"
                )

            merged = dict(attempt.answers_json or {})
            for k, v in (final_answers or {}).items():
                merged[str(k)] = v
            attempt.answers_json = merged
            flag_modified(attempt, "answers_json")
            attempt.status = "grading"
            attempt.submitted_at = datetime.utcnow()
            self.db.commit()
        except (PracticeNotFoundError, PracticePermissionError, PracticeConflictError):
            self.db.rollback()
            raise
        except Exception:
            self.db.rollback()
            raise

        self.db.refresh(attempt)
        self._spawn_grading_worker(attempt_id)
        return self._to_attempt_dto(attempt, redact=True)

    def retry_grading(self, attempt_id: str, user_id: str) -> None:
        """Re-trigger grading on an attempt whose earlier grading failed.
        Status must be `grading_failed`; flips to `grading` and respawns
        the worker.
        """
        attempt = self._get_owned(attempt_id, user_id)
        if attempt.status != "grading_failed":
            raise PracticeConflictError(
                f"Cannot retry: attempt status is {attempt.status!r}, "
                f"not 'grading_failed'"
            )
        self.attempt_repo.mark_grading(attempt_id)
        self._spawn_grading_worker(attempt_id)

    def get_attempt(
        self, attempt_id: str, user_id: str
    ) -> Union[Attempt, AttemptResults]:
        """Resolve to Attempt (redacted) or AttemptResults (unredacted)
        depending on status.
        """
        attempt = self._get_owned(attempt_id, user_id)
        if attempt.status in ("graded", "grading_failed"):
            return self._to_results_dto(attempt)
        return self._to_attempt_dto(attempt, redact=True)

    def list_attempts(self, user_id: str, guideline_id: str) -> list[AttemptSummary]:
        """History for one topic (FR-45)."""
        rows = self.attempt_repo.list_for_user_topic(user_id, guideline_id)
        return [
            AttemptSummary(
                id=r.id,
                status=r.status,
                total_score=r.total_score,
                total_possible=r.total_possible,
                submitted_at=r.submitted_at,
                graded_at=r.graded_at,
            )
            for r in rows
        ]

    def mark_viewed(self, attempt_id: str, user_id: str) -> None:
        """Stamp results_viewed_at — removes the attempt from the banner."""
        self._get_owned(attempt_id, user_id)
        self.attempt_repo.mark_viewed(attempt_id)

    def list_recent_unread(self, user_id: str) -> list[AttemptSummary]:
        """Drives the /recent poll from PracticeBanner."""
        rows = self.attempt_repo.list_recent_unread(user_id)
        return [
            AttemptSummary(
                id=r.id,
                status=r.status,
                total_score=r.total_score,
                total_possible=r.total_possible,
                submitted_at=r.submitted_at,
                graded_at=r.graded_at,
            )
            for r in rows
        ]

    # ─── Set selection ────────────────────────────────────────────────────

    def _select_set(self, bank: list[PracticeQuestion]) -> list[PracticeQuestion]:
        """Pick 10 questions: 3 easy + 5 medium + 2 hard, falling back to
        adjacent tiers if any bucket is short. Post-pick, reorder to avoid
        consecutive same-format questions. FF counts toward variety (Q2).
        """
        by_diff: dict[str, list[PracticeQuestion]] = {"easy": [], "medium": [], "hard": []}
        for q in bank:
            if q.difficulty in by_diff:
                by_diff[q.difficulty].append(q)

        picks: list[PracticeQuestion] = []
        leftovers: list[PracticeQuestion] = []

        for diff, target in DIFFICULTY_TARGETS.items():
            pool = by_diff[diff][:]
            random.shuffle(pool)
            picks.extend(pool[:target])
            leftovers.extend(pool[target:])

        # Backfill from leftovers if any tier was short.
        random.shuffle(leftovers)
        while len(picks) < SET_SIZE and leftovers:
            picks.append(leftovers.pop())

        if len(picks) < SET_SIZE:
            raise PracticeBankEmptyError(
                f"Could only assemble {len(picks)} questions; need {SET_SIZE}"
            )

        picks = picks[:SET_SIZE]
        variety = len({q.format for q in picks})
        if variety < 4:
            logger.warning(
                f"Selected set has only {variety} distinct formats "
                f"(spec suggests >= 4). Bank may be too narrow."
            )

        return self._enforce_no_consecutive_same_format(picks)

    def _enforce_no_consecutive_same_format(
        self, items: list[PracticeQuestion]
    ) -> list[PracticeQuestion]:
        """Greedy reordering: always pick from the candidates whose format
        differs from the previous pick when possible. Falls back to any
        remaining item if all share the last format.
        """
        remaining = items[:]
        random.shuffle(remaining)
        result: list[PracticeQuestion] = []
        last_fmt: Optional[str] = None
        while remaining:
            candidates = [i for i, q in enumerate(remaining) if q.format != last_fmt]
            if not candidates:
                candidates = list(range(len(remaining)))
            idx = random.choice(candidates)
            picked = remaining.pop(idx)
            result.append(picked)
            last_fmt = picked.format
        return result

    def _snapshot_question(self, q: PracticeQuestion) -> dict:
        """Copy question_json + inject `_id`, `_format`, `_difficulty`,
        `_concept_tag`, `_presentation_seed` for the frontend's deterministic
        shuffle (survives page reload).
        """
        payload = dict(q.question_json or {})
        payload["_id"] = q.id
        payload["_format"] = q.format
        payload["_difficulty"] = q.difficulty
        payload["_concept_tag"] = q.concept_tag
        payload["_presentation_seed"] = random.randint(0, 2**31 - 1)
        return payload

    # ─── Redaction ────────────────────────────────────────────────────────

    def _redact_questions(self, snapshot: list[dict]) -> list[dict]:
        """Strip correctness fields before serving during the set (FR-26).

        Keeps `_id`, `_format`, `_difficulty`, `_concept_tag`, `_presentation_seed`
        intact — only the correctness fields are removed.

        Format-specific redactions:
          - match_pairs: drops `pairs`, exposes `pair_lefts` and `pair_rights`
            as parallel arrays (frontend shuffles rights via seed)
          - sort_buckets / swipe_classify: strips `correct_bucket` per item
        """
        out: list[dict] = []
        for q in snapshot:
            clean = {k: v for k, v in q.items() if k not in REDACT_TOP_LEVEL_KEYS}
            fmt = clean.get("_format")

            if fmt == "match_pairs" and "pairs" in clean:
                pairs = clean.pop("pairs")
                clean["pair_lefts"] = [p.get("left") for p in pairs]
                clean["pair_rights"] = [p.get("right") for p in pairs]

            if fmt in ("sort_buckets", "swipe_classify") and "bucket_items" in clean:
                clean["bucket_items"] = [
                    {"text": bi.get("text")} for bi in clean["bucket_items"]
                ]

            out.append(clean)
        return out

    # ─── DTO conversion ───────────────────────────────────────────────────

    def _to_attempt_dto(
        self, attempt: PracticeAttempt, redact: bool = True
    ) -> Attempt:
        snapshot = attempt.questions_snapshot_json or []
        questions = self._redact_questions(snapshot) if redact else snapshot

        return Attempt(
            id=attempt.id,
            user_id=attempt.user_id,
            guideline_id=attempt.guideline_id,
            status=attempt.status,
            total_possible=attempt.total_possible,
            questions=[
                AttemptQuestion(
                    q_idx=i,
                    q_id=q.get("_id", ""),
                    format=q.get("_format", ""),
                    difficulty=q.get("_difficulty", ""),
                    concept_tag=q.get("_concept_tag", ""),
                    presentation_seed=q.get("_presentation_seed", 0),
                    question_json={k: v for k, v in q.items() if not k.startswith("_")},
                )
                for i, q in enumerate(questions)
            ],
            answers=dict(attempt.answers_json or {}),
            created_at=attempt.created_at,
            submitted_at=attempt.submitted_at,
        )

    def _to_results_dto(self, attempt: PracticeAttempt) -> AttemptResults:
        snapshot = attempt.questions_snapshot_json or []
        grading = attempt.grading_json or {}
        graded_qs = [
            GradedQuestion(
                q_idx=i,
                q_id=q.get("_id", ""),
                format=q.get("_format", ""),
                difficulty=q.get("_difficulty", ""),
                concept_tag=q.get("_concept_tag", ""),
                question_json={k: v for k, v in q.items() if not k.startswith("_")},
                student_answer=(grading.get(str(i), {}) or {}).get("student_answer"),
                correct=(grading.get(str(i), {}) or {}).get("correct", False),
                score=(grading.get(str(i), {}) or {}).get("score", 0.0),
                correct_answer_summary=(grading.get(str(i), {}) or {}).get("correct_answer_summary"),
                rationale=(grading.get(str(i), {}) or {}).get("rationale"),
                visual_explanation_code=(grading.get(str(i), {}) or {}).get("visual_explanation_code"),
            )
            for i, q in enumerate(snapshot)
        ]
        return AttemptResults(
            id=attempt.id,
            user_id=attempt.user_id,
            guideline_id=attempt.guideline_id,
            status=attempt.status,
            total_possible=attempt.total_possible,
            total_score=attempt.total_score,
            questions=graded_qs,
            grading_error=attempt.grading_error,
            submitted_at=attempt.submitted_at,
            graded_at=attempt.graded_at,
        )

    # ─── Internal helpers ─────────────────────────────────────────────────

    def _get_owned(self, attempt_id: str, user_id: str) -> PracticeAttempt:
        """Fetch attempt, raising 404 if missing and 403 if user mismatch."""
        attempt = self.attempt_repo.get(attempt_id)
        if attempt is None:
            raise PracticeNotFoundError(f"Attempt {attempt_id} not found")
        if attempt.user_id != user_id:
            raise PracticePermissionError(
                f"Attempt {attempt_id} not owned by user {user_id}"
            )
        return attempt

    def _spawn_grading_worker(self, attempt_id: str) -> None:
        """Spawn a daemon thread running PracticeGradingService.grade_attempt.

        Must use a fresh DB session — the current one belongs to the request.
        The grader's LLMService is built from the `practice_grader` config
        with `initial_retry_delay=10` to get the 10/20/40s backoff the plan
        mandates.
        """
        def _run():
            from database import get_db_manager
            from config import get_settings
            from shared.services.llm_config_service import LLMConfigService
            from shared.services.llm_service import LLMService
            from tutor.services.practice_grading_service import PracticeGradingService

            db = get_db_manager().get_session()
            try:
                settings = get_settings()
                config = LLMConfigService(db).get_config("practice_grader")
                llm = LLMService(
                    api_key=settings.openai_api_key,
                    provider=config["provider"],
                    model_id=config["model_id"],
                    gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
                    anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
                    initial_retry_delay=10,
                )
                PracticeGradingService(db, llm).grade_attempt(attempt_id)
            except Exception:
                logger.exception(f"Grading worker crashed for attempt {attempt_id}")
            finally:
                try:
                    db.close()
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True).start()
