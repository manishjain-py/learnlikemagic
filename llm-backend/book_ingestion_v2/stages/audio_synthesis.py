"""Stage: audio_synthesis — generates pre-computed MP3s for every audio
clip across variant A explanations and (when present) the dialogue.

Soft-joins on `baatcheet_dialogue`: if the dialogue exists, the synthesis
covers its MP3s too; if not, just variant A.
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
    from shared.repositories.dialogue_repository import DialogueRepository

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

    # Include Baatcheet dialogue clips so super-run doesn't mark the stage
    # `done` while dialogue MP3s are still missing.
    dialogue = DialogueRepository(ctx.db).get_by_guideline_id(ctx.guideline_id)
    if dialogue and dialogue.cards_json:
        dt, dw = AudioGenerationService.count_dialogue_audio_items(dialogue.cards_json)
        total_clips += dt
        clips_with_audio += dw

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
    # Hard dep on `audio_review` only. `baatcheet_dialogue` is a soft join
    # — if the dialogue exists, this stage synthesises its MP3s too; if
    # not, just variant A. Modelling it as a hard dep would break that
    # contract under Phase 3 cascade staleness (a dialogue regen would
    # mark synthesis fully stale even though variant-A MP3s are unchanged).
    # The legacy super-button still serialises both ahead of synthesis via
    # declaration order in `STAGES` + halt-on-failure, so Phase 1 runtime
    # is preserved without the dep edge.
    depends_on=("audio_review",),
    launch=launch_audio_synthesis_job,
    status_check=_status,
)
