"""Stage: explanations — generates the variant-A explanation deck.

This is the staleness anchor for every other topic-scope stage: the
`max(topic_explanations.created_at)` value flows into downstream
`StatusContext.content_anchor` and drives stale flags on practice_bank /
audio_review / etc.
"""
from __future__ import annotations

from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.dag.status_helpers import (
    build_stage,
    derive_state,
    latest_job_for_guideline,
)
from book_ingestion_v2.dag.types import (
    Stage,
    StageScope,
    StageStatusOutput,
    StatusContext,
)
from book_ingestion_v2.services.stage_launchers import launch_explanation_job


_JOB_TYPE = V2JobType.EXPLANATION_GENERATION.value


def _status(ctx: StatusContext) -> StageStatusOutput:
    job = latest_job_for_guideline(
        ctx.db, guideline_id=ctx.guideline_id, job_type=_JOB_TYPE
    )
    has_cards = any(bool(e.cards_json) for e in ctx.explanations)
    state, summary, warnings = derive_state(
        stage_id="explanations",
        artifact_present=has_cards,
        artifact_summary=(
            f"{len(ctx.explanations)} variant(s)" if ctx.explanations else "No variants"
        ),
        job=job,
        has_warnings=False,
        blocked_by=None,
    )
    return build_stage("explanations", state, summary, warnings, job=job)


STAGE = Stage(
    id="explanations",
    scope=StageScope.TOPIC,
    label="Explanations",
    depends_on=(),
    launch=launch_explanation_job,
    status_check=_status,
)
