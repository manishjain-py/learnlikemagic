"""Stage: audio_review — vets audio text on variant A cards before TTS.

Stale when the review's `completed_at < explanations.created_at`.
"""
from __future__ import annotations

from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.dag.status_helpers import (
    build_blocked,
    build_stage,
    fmt_ago,
    latest_job_for_guideline,
)
from book_ingestion_v2.dag.types import (
    Stage,
    StageScope,
    StageStatusOutput,
    StatusContext,
)
from book_ingestion_v2.models.schemas import StageState, StageStatus
from book_ingestion_v2.services.stage_launchers import launch_audio_review_job


_JOB_TYPE = V2JobType.AUDIO_TEXT_REVIEW.value


def _status(ctx: StatusContext) -> StageStatusOutput:
    explanations_done = any(bool(e.cards_json) for e in ctx.explanations)
    job = latest_job_for_guideline(
        ctx.db, guideline_id=ctx.guideline_id, job_type=_JOB_TYPE
    )

    if not explanations_done:
        return build_blocked("audio_review", blocked_by="explanations", job=job)

    if job is None:
        return StageStatus(
            stage_id="audio_review",
            state="ready",
            summary="No audio review run yet",
        )

    is_stale = bool(
        ctx.content_anchor
        and job.completed_at
        and job.completed_at < ctx.content_anchor
    )

    warnings: list[str] = []
    if is_stale:
        warnings.append("Audio review predates latest explanations — rerun to refresh")

    if job.status == "completed" and not is_stale:
        state: StageState = "done"
        summary = f"Reviewed {fmt_ago(job.completed_at)}"
    elif job.status == "completed_with_errors" or is_stale:
        state = "warning"
        summary = (
            f"Completed with errors ({fmt_ago(job.completed_at)})"
            if job.status == "completed_with_errors"
            else f"Completed {fmt_ago(job.completed_at)} (stale)"
        )
    elif job.status == "failed":
        state = "failed"
        summary = f"Last run failed {fmt_ago(job.completed_at)}"
    elif job.status in ("pending", "running"):
        state = "running"
        summary = "Running…"
    else:
        state = "ready"
        summary = job.status

    return build_stage(
        "audio_review", state, summary, warnings, job=job, is_stale=is_stale,
    )


STAGE = Stage(
    id="audio_review",
    scope=StageScope.TOPIC,
    label="Audio Review",
    depends_on=("explanations",),
    launch=launch_audio_review_job,
    status_check=_status,
    description=(
        "Single-pass LLM review of each explanation line's audio_text for "
        "TTS-friendliness (no markdown, no naked equals, no emoji). "
        "Applies surgical edits and clears audio_url on revised lines."
    ),
)
