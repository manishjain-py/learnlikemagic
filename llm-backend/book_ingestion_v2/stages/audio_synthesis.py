"""Stage: audio_synthesis — generates pre-computed MP3s for variant A
explanation clips. Baatcheet dialogue audio lives in the parallel
`baatcheet_audio_synthesis` stage.
"""
from __future__ import annotations

from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.dag.status_helpers import (
    build_blocked,
    build_stage,
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
from book_ingestion_v2.services.stage_launchers import launch_audio_synthesis_job


_JOB_TYPE = V2JobType.AUDIO_GENERATION.value


def _status(ctx: StatusContext) -> StageStatusOutput:
    from book_ingestion_v2.services.audio_generation_service import (
        AudioGenerationService,
    )

    explanations_done = any(bool(e.cards_json) for e in ctx.explanations)
    job = latest_job_for_guideline(
        ctx.db, guideline_id=ctx.guideline_id, job_type=_JOB_TYPE
    )

    if not explanations_done:
        return build_blocked("audio_synthesis", blocked_by="explanations", job=job)

    total_clips = 0
    clips_with_audio = 0
    for expl in ctx.explanations:
        t, w = AudioGenerationService.count_audio_items(expl.cards_json or [])
        total_clips += t
        clips_with_audio += w

    if total_clips == 0:
        summary = "No audio clips yet"
        artifact_present = False
    else:
        summary = f"{clips_with_audio}/{total_clips} audio clips have pre-computed MP3"
        artifact_present = clips_with_audio > 0

    if total_clips > 0 and clips_with_audio == total_clips:
        state: StageState = "done"
    elif 0 < clips_with_audio < total_clips:
        state = "warning"
    else:
        state = "ready"

    state, summary, warnings = overlay_job_state(
        state=state,
        summary=summary,
        warnings=[],
        job=job,
        artifact_present=artifact_present,
    )
    return build_stage("audio_synthesis", state, summary, warnings, job=job)


STAGE = Stage(
    id="audio_synthesis",
    scope=StageScope.TOPIC,
    label="Audio Synthesis",
    depends_on=("audio_review",),
    launch=launch_audio_synthesis_job,
    status_check=_status,
)
