"""Stage: baatcheet_audio_synthesis — generates pre-computed MP3s for
every clip in `topic_dialogues.cards_json`. Sibling of `audio_synthesis`
for variant A explanations.
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
from book_ingestion_v2.services.stage_launchers import (
    launch_baatcheet_audio_synthesis_job,
)


_JOB_TYPE = V2JobType.BAATCHEET_AUDIO_GENERATION.value


def _status(ctx: StatusContext) -> StageStatusOutput:
    from book_ingestion_v2.services.audio_generation_service import (
        AudioGenerationService,
    )
    from shared.repositories.dialogue_repository import DialogueRepository

    dialogue = DialogueRepository(ctx.db).get_by_guideline_id(ctx.guideline_id)
    job = latest_job_for_guideline(
        ctx.db, guideline_id=ctx.guideline_id, job_type=_JOB_TYPE,
    )

    if not dialogue or not dialogue.cards_json:
        return build_blocked(
            "baatcheet_audio_synthesis",
            blocked_by="baatcheet_dialogue", job=job,
        )

    total_clips, clips_with_audio = AudioGenerationService.count_dialogue_audio_items(
        dialogue.cards_json,
    )

    if total_clips == 0:
        summary = "No dialogue audio clips yet"
        artifact_present = False
    else:
        summary = (
            f"{clips_with_audio}/{total_clips} dialogue clips have pre-computed MP3"
        )
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
    return build_stage(
        "baatcheet_audio_synthesis", state, summary, warnings, job=job,
    )


STAGE = Stage(
    id="baatcheet_audio_synthesis",
    scope=StageScope.TOPIC,
    label="Baatcheet Audio Synthesis",
    depends_on=("baatcheet_audio_review",),
    launch=launch_baatcheet_audio_synthesis_job,
    status_check=_status,
    description=(
        "Synthesizes Google Cloud Chirp 3 HD audio per dialogue line and "
        "uploads MP3s to S3. Mr. Verma uses the Orus voice, Meera uses "
        "Leda. Idempotent — skips lines that already have audio_url."
    ),
)
