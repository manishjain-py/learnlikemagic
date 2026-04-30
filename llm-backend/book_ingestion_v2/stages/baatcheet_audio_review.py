"""Stage: baatcheet_audio_review — vets audio text on dialogue cards
before TTS. Sibling of `audio_review` for variant A explanations.

Stale when the review's `completed_at < dialogue.created_at`.
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
from book_ingestion_v2.services.stage_launchers import (
    launch_baatcheet_audio_review_job,
)


_JOB_TYPE = V2JobType.BAATCHEET_AUDIO_REVIEW.value


def _status(ctx: StatusContext) -> StageStatusOutput:
    from shared.repositories.dialogue_repository import DialogueRepository

    dialogue = DialogueRepository(ctx.db).get_by_guideline_id(ctx.guideline_id)
    job = latest_job_for_guideline(
        ctx.db, guideline_id=ctx.guideline_id, job_type=_JOB_TYPE,
    )

    if not dialogue or not dialogue.cards_json:
        return build_blocked(
            "baatcheet_audio_review", blocked_by="baatcheet_dialogue", job=job,
        )

    if job is None:
        return StageStatus(
            stage_id="baatcheet_audio_review",
            state="ready",
            summary="No dialogue audio review run yet",
        )

    is_stale = bool(
        dialogue.created_at
        and job.completed_at
        and job.completed_at < dialogue.created_at
    )

    warnings: list[str] = []
    if is_stale:
        warnings.append(
            "Dialogue audio review predates latest dialogue — rerun to refresh",
        )

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
        "baatcheet_audio_review", state, summary, warnings,
        job=job, is_stale=is_stale,
    )


STAGE = Stage(
    id="baatcheet_audio_review",
    scope=StageScope.TOPIC,
    label="Baatcheet Audio Review",
    depends_on=("baatcheet_dialogue",),
    launch=launch_baatcheet_audio_review_job,
    status_check=_status,
    description=(
        "Single-pass LLM review of each dialogue line's audio_text for "
        "TTS-friendliness. Applies surgical edits in place and clears "
        "audio_url on revised lines so synthesis regenerates only what "
        "changed."
    ),
)
