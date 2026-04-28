"""Stage: visuals — generates PixiJS visuals on variant A explanation cards."""
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
from book_ingestion_v2.services.stage_launchers import launch_visual_job


_JOB_TYPE = V2JobType.VISUAL_ENRICHMENT.value


def _status(ctx: StatusContext) -> StageStatusOutput:
    explanations_done = any(bool(e.cards_json) for e in ctx.explanations)
    job = latest_job_for_guideline(
        ctx.db, guideline_id=ctx.guideline_id, job_type=_JOB_TYPE
    )

    if not explanations_done:
        return build_blocked("visuals", blocked_by="explanations", job=job)

    cards_with_visuals = 0
    layout_warnings = 0
    total_cards = 0
    for expl in ctx.explanations:
        for card in expl.cards_json or []:
            total_cards += 1
            visual = card.get("visual_explanation") if isinstance(card, dict) else None
            if isinstance(visual, dict) and visual.get("pixi_code"):
                cards_with_visuals += 1
                if visual.get("layout_warning") is True:
                    layout_warnings += 1

    artifact_present = cards_with_visuals > 0
    has_warning = layout_warnings > 0
    summary = f"{cards_with_visuals}/{total_cards} cards have visuals"
    warnings = (
        [f"{layout_warnings} card(s) with layout warning"]
        if layout_warnings
        else []
    )
    state, summary, warnings = derive_state(
        stage_id="visuals",
        artifact_present=artifact_present,
        artifact_summary=summary,
        job=job,
        has_warnings=has_warning,
        blocked_by=None,
        warnings=warnings,
    )
    return build_stage("visuals", state, summary, warnings, job=job)


STAGE = Stage(
    id="visuals",
    scope=StageScope.TOPIC,
    label="Visuals",
    depends_on=("explanations",),
    launch=launch_visual_job,
    status_check=_status,
)
