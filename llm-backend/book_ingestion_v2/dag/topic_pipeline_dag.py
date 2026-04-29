"""Single source of truth for the topic-pipeline DAG.

To add a stage:
1. Create `book_ingestion_v2/stages/{stage_id}.py` exporting `STAGE = Stage(...)`.
2. Import that module here and append `STAGE` to the `STAGES` list.

The order in `STAGES` is the tie-breaker for `topo_sort` — declaring stages
in the order they used to appear in the legacy `PIPELINE_LAYERS` keeps the
super-button's run order identical to Phase 0.
"""
from __future__ import annotations

from book_ingestion_v2.dag.types import Stage, TopicPipelineDAG
from book_ingestion_v2.stages import (
    audio_review,
    audio_synthesis,
    baatcheet_audio_review,
    baatcheet_audio_synthesis,
    baatcheet_dialogue,
    baatcheet_visuals,
    check_ins,
    explanations,
    practice_bank,
    visuals,
)


STAGES: list[Stage] = [
    explanations.STAGE,
    baatcheet_dialogue.STAGE,
    baatcheet_visuals.STAGE,
    baatcheet_audio_review.STAGE,
    baatcheet_audio_synthesis.STAGE,
    visuals.STAGE,
    check_ins.STAGE,
    practice_bank.STAGE,
    audio_review.STAGE,
    audio_synthesis.STAGE,
]


DAG = TopicPipelineDAG(STAGES)
DAG.validate_acyclic()  # raises at import if a cycle is introduced
