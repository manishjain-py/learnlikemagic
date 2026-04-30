"""Stage: baatcheet_visuals — fills `visual_explanation` slots on Baatcheet
dialogue cards with PixiJS code.

V2 dialogues (have `plan_json`): the "must-have" set is plan slots whose
`visual_required` is True. The stage is `done` when every such slot's card
has `visual_explanation.pixi_code` populated. The selector also picks
default-generate cards (not visual_required); those don't gate `done` —
they become a "extras done" count surfaced for transparency.

V1 dialogues (no `plan_json`): legacy behaviour — count cards where
`card_type == "visual"` and check whether each has `visual_explanation.pixi_code`.

Cascade staleness handles the "upstream regenerated → downstream stale"
case via the cascade orchestrator (Phase 3); this stage doesn't carry
its own `staleness_check` because the rerun-from-stage flow already
covers it. Read-time content-hash invalidation is a future addition if
admins find the cascade signal insufficient.
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
from book_ingestion_v2.services.stage_launchers import launch_baatcheet_visual_job


_JOB_TYPE = V2JobType.BAATCHEET_VISUAL_ENRICHMENT.value


def _has_pixi(card: dict) -> bool:
    if not isinstance(card, dict):
        return False
    ve = card.get("visual_explanation")
    return isinstance(ve, dict) and bool(ve.get("pixi_code"))


def _required_card_idxs(plan_json) -> set[int]:
    """`card_idx`s the plan flagged as `visual_required: true`.

    Plan slots use the `slot` field which the dialogue exposes back as
    `card_idx` — the V2 generator copies one to the other 1:1.
    """
    if not isinstance(plan_json, dict):
        return set()
    card_plan = plan_json.get("card_plan")
    if not isinstance(card_plan, list):
        return set()
    required: set[int] = set()
    for slot in card_plan:
        if not isinstance(slot, dict):
            continue
        if slot.get("visual_required") is True:
            slot_idx = slot.get("slot")
            if isinstance(slot_idx, int):
                required.add(slot_idx)
    return required


def _status(ctx: StatusContext) -> StageStatusOutput:
    from shared.repositories.dialogue_repository import DialogueRepository

    repo = DialogueRepository(ctx.db)
    dialogue = repo.get_by_guideline_id(ctx.guideline_id)
    job = latest_job_for_guideline(
        ctx.db, guideline_id=ctx.guideline_id, job_type=_JOB_TYPE
    )
    if not dialogue or not dialogue.cards_json:
        return build_blocked(
            "baatcheet_visuals", blocked_by="baatcheet_dialogue", job=job,
        )

    cards = [c for c in dialogue.cards_json if isinstance(c, dict)]

    if dialogue.plan_json:
        required_idxs = _required_card_idxs(dialogue.plan_json)
        cards_by_idx = {c.get("card_idx"): c for c in cards}
        # Required cards: plan demands them; stage is done only when all
        # have PixiJS.
        required_present = sum(
            1 for idx in required_idxs
            if _has_pixi(cards_by_idx.get(idx))
        )
        # Extras: selector also picks default-generate cards on every run,
        # regardless of `visual_required` flags on the plan.
        extras_present = sum(
            1 for c in cards
            if _has_pixi(c) and c.get("card_idx") not in required_idxs
        )
        total_required = len(required_idxs)

        artifact_present = required_present > 0 or extras_present > 0

        if total_required > 0:
            if required_present == total_required:
                state = "done"
            elif required_present > 0:
                state = "warning"
            else:
                state = "ready"
            summary = (
                f"{required_present}/{total_required} required visuals · "
                f"{extras_present} extras"
            )
        else:
            # No `visual_required` flags in the plan — common when the
            # planner predates the field. The selector still picks 12-18
            # default cards on every run, so don't pre-declare `done`
            # before the stage has executed: that hides the work from the
            # admin and burns the dashboard's signal.
            job_completed = bool(
                job and job.status in ("completed", "completed_with_errors")
            )
            if extras_present > 0:
                state = "done"
                summary = f"No required slots in plan · {extras_present} default visuals enriched"
            elif job_completed:
                # Job ran but selector returned nothing — surface explicitly.
                state = "done"
                summary = "No required slots in plan · selector picked no cards"
            else:
                state = "ready"
                summary = "No required slots in plan · selector picks defaults; not yet run"

        state, summary, warnings = overlay_job_state(
            state=state, summary=summary, warnings=[],
            job=job, artifact_present=artifact_present,
        )
        return build_stage("baatcheet_visuals", state, summary, warnings, job=job)

    # ── V1 fallback ─────────────────────────────────────────────────────
    total_visual_cards = 0
    cards_with_visuals = 0
    for card in cards:
        if card.get("card_type") == "visual":
            total_visual_cards += 1
            if _has_pixi(card):
                cards_with_visuals += 1

    if total_visual_cards == 0:
        return build_stage(
            "baatcheet_visuals", "done",
            "No visual cards in this dialogue", [], job=job,
        )

    artifact_present = cards_with_visuals > 0
    if cards_with_visuals == total_visual_cards:
        state = "done"
    elif cards_with_visuals > 0:
        state = "warning"
    else:
        state = "ready"
    summary = f"{cards_with_visuals}/{total_visual_cards} visual cards have PixiJS"

    state, summary, warnings = overlay_job_state(
        state=state, summary=summary, warnings=[],
        job=job, artifact_present=artifact_present,
    )
    return build_stage("baatcheet_visuals", state, summary, warnings, job=job)


STAGE = Stage(
    id="baatcheet_visuals",
    scope=StageScope.TOPIC,
    label="Baatcheet Visuals",
    depends_on=("baatcheet_dialogue",),
    launch=launch_baatcheet_visual_job,
    status_check=_status,
    description=(
        "Fills `visual_explanation.pixi_code` on dialogue cards. "
        "An LLM selector picks cards from the plan (visual_required + "
        "default-generate rules); PixiCodeGenerator turns each intent into "
        "runnable PixiJS. Skips cards already enriched."
    ),
)
