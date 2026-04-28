"""Stage: baatcheet_dialogue — generates the conversational dialogue
between Mr. Verma and Meera for one topic, anchored on variant A.

Stale signal uses `source_content_hash` — variant A's `cards_json` is
mutated in-place by visuals/check-ins/audio stages, so timestamp comparison
would over-trigger. The hash captures semantic identity only.
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
from book_ingestion_v2.services.stage_launchers import launch_baatcheet_dialogue_job


_JOB_TYPE = V2JobType.BAATCHEET_DIALOGUE_GENERATION.value


def _status(ctx: StatusContext) -> StageStatusOutput:
    from shared.repositories.dialogue_repository import DialogueRepository

    # Stage 5b raises if specifically variant A is missing — match that
    # contract here instead of accepting any variant.
    variant_a_done = any(
        getattr(e, "variant_key", None) == "A" and bool(e.cards_json)
        for e in ctx.explanations
    )
    job = latest_job_for_guideline(
        ctx.db, guideline_id=ctx.guideline_id, job_type=_JOB_TYPE
    )
    if not variant_a_done:
        return build_blocked("baatcheet_dialogue", blocked_by="explanations", job=job)

    repo = DialogueRepository(ctx.db)
    dialogue = repo.get_by_guideline_id(ctx.guideline_id)
    artifact_present = bool(dialogue and dialogue.cards_json)
    is_stale = repo.is_stale(ctx.guideline_id) if artifact_present else False

    warnings: list[str] = []
    if is_stale:
        warnings.append(
            "Variant A has changed since dialogue was generated — regenerate to refresh"
        )

    if artifact_present:
        card_count = len(dialogue.cards_json)
        summary = f"{card_count} dialogue card(s)" + (" (stale)" if is_stale else "")
        state = "warning" if is_stale else "done"
    else:
        summary = "No dialogue yet"
        state = "ready"

    state, summary, warnings = overlay_job_state(
        state=state, summary=summary, warnings=warnings,
        job=job, artifact_present=artifact_present,
    )
    return build_stage(
        "baatcheet_dialogue", state, summary, warnings,
        job=job, is_stale=is_stale,
    )


STAGE = Stage(
    id="baatcheet_dialogue",
    scope=StageScope.TOPIC,
    label="Baatcheet Dialogue",
    depends_on=("explanations",),
    launch=launch_baatcheet_dialogue_job,
    status_check=_status,
)
