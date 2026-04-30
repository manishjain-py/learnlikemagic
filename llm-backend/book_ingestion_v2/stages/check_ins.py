"""Stage: check_ins — inserts check-in cards into the variant A deck."""
from __future__ import annotations

from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.dag.status_helpers import (
    build_blocked,
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
from book_ingestion_v2.services.check_in_enrichment_service import (
    DEFAULT_REVIEW_ROUNDS,
)
from book_ingestion_v2.services.stage_launchers import launch_check_in_job


_JOB_TYPE = V2JobType.CHECK_IN_ENRICHMENT.value


def _status(ctx: StatusContext) -> StageStatusOutput:
    explanations_done = any(bool(e.cards_json) for e in ctx.explanations)
    job = latest_job_for_guideline(
        ctx.db, guideline_id=ctx.guideline_id, job_type=_JOB_TYPE
    )

    if not explanations_done:
        return build_blocked("check_ins", blocked_by="explanations", job=job)

    check_in_count = 0
    for expl in ctx.explanations:
        for card in expl.cards_json or []:
            if isinstance(card, dict) and card.get("card_type") == "check_in":
                check_in_count += 1

    summary = f"{check_in_count} check-in card(s)"
    state, summary, warnings = derive_state(
        stage_id="check_ins",
        artifact_present=check_in_count > 0,
        artifact_summary=summary,
        job=job,
        has_warnings=False,
        blocked_by=None,
    )
    return build_stage("check_ins", state, summary, warnings, job=job)


STAGE = Stage(
    id="check_ins",
    scope=StageScope.TOPIC,
    label="Check-ins",
    depends_on=("explanations",),
    launch=launch_check_in_job,
    status_check=_status,
    description=(
        "Generates check-in activity cards (11 activity types) and inserts "
        "them at boundaries chosen by the LLM. "
        "Pipeline: analyze cards → generate → review-and-refine → "
        "validate → insert into variant-A cards_json."
    ),
    review_rounds=DEFAULT_REVIEW_ROUNDS,
)
