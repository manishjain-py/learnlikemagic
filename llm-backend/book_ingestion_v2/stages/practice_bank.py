"""Stage: practice_bank — generates 30+ practice questions per topic.

Stale when `min(practice.created_at) < explanations.created_at`.
"""
from __future__ import annotations

from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.dag.status_helpers import (
    build_blocked,
    build_stage,
    job_failed,
    latest_job_for_guideline,
    overlay_job_state,
)
from book_ingestion_v2.dag.types import (
    Stage,
    StageScope,
    StageStatusOutput,
    StatusContext,
)
from book_ingestion_v2.models.schemas import StageState
from book_ingestion_v2.services.practice_bank_generator_service import (
    DEFAULT_REVIEW_ROUNDS,
)
from book_ingestion_v2.services.stage_launchers import launch_practice_bank_job


_JOB_TYPE = V2JobType.PRACTICE_BANK_GENERATION.value
_PRACTICE_DONE_THRESHOLD = 30


def _status(ctx: StatusContext) -> StageStatusOutput:
    from shared.models.entities import PracticeQuestion

    explanations_done = any(bool(e.cards_json) for e in ctx.explanations)
    job = latest_job_for_guideline(
        ctx.db, guideline_id=ctx.guideline_id, job_type=_JOB_TYPE
    )

    if not explanations_done:
        return build_blocked("practice_bank", blocked_by="explanations", job=job)

    rows = (
        ctx.db.query(PracticeQuestion)
        .filter(PracticeQuestion.guideline_id == ctx.guideline_id)
        .all()
    )
    count = len(rows)
    earliest = min((r.created_at for r in rows if r.created_at), default=None)

    is_stale = bool(
        ctx.content_anchor
        and earliest
        and earliest < ctx.content_anchor
    )

    warnings: list[str] = []
    if is_stale:
        warnings.append("Practice bank predates latest explanations — regenerate to refresh")

    if count == 0:
        state: StageState = "ready" if not job_failed(job) else "failed"
        summary = "No practice questions yet"
    elif count >= _PRACTICE_DONE_THRESHOLD and not is_stale:
        state = "done"
        summary = f"{count} questions"
    else:
        state = "warning"
        summary = f"{count} questions" + (" (stale)" if is_stale else " (partial)")

    state, summary, warnings = overlay_job_state(
        state=state,
        summary=summary,
        warnings=warnings,
        job=job,
        artifact_present=count > 0,
    )
    return build_stage(
        "practice_bank", state, summary, warnings, job=job, is_stale=is_stale,
    )


STAGE = Stage(
    id="practice_bank",
    scope=StageScope.TOPIC,
    label="Practice Bank",
    depends_on=("explanations",),
    launch=launch_practice_bank_job,
    status_check=_status,
    description=(
        "Generates the offline practice question bank (30–40 questions "
        "across 12 formats) for Let's Practice. "
        "Pipeline: generate → review-and-refine → validate (format counts, "
        "dedup) → bulk insert into practice_questions."
    ),
    review_rounds=DEFAULT_REVIEW_ROUNDS,
)
