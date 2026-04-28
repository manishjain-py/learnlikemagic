"""Derived `stage_id → launch_fn` map + `job_type → stage_id` lookup.

Lives here (not in `stage_launchers.py`) to break the natural cycle:
    topic_pipeline_dag → stages → stage_launchers → DAG.

Importing this module triggers the full DAG load. Adding a new stage
requires no edit to `LAUNCHER_BY_STAGE` — the dict is regenerated from
`DAG.stages` on import. `JOB_TYPE_TO_STAGE_ID` is a small explicit map
because the V2JobType ↔ stage_id correspondence isn't expressed on the
`Stage` dataclass — Phase 2 keeps it minimal-touch by hard-coding it
here. Phase 3+ may move it onto `Stage` itself.
"""
from __future__ import annotations

from typing import Callable

from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.dag.topic_pipeline_dag import DAG


LAUNCHER_BY_STAGE: dict[str, Callable[..., str]] = {
    s.id: s.launch for s in DAG.stages
}


# Reverse lookup used by the `run_in_background_v2` hook to map an in-flight
# `chapter_processing_jobs.job_type` value back to its DAG stage_id.
# `BAATCHEET_AUDIO_REVIEW` is intentionally omitted — that opt-in stage is
# launched manually and is not part of the Phase 1 topic DAG.
JOB_TYPE_TO_STAGE_ID: dict[str, str] = {
    V2JobType.EXPLANATION_GENERATION.value: "explanations",
    V2JobType.VISUAL_ENRICHMENT.value: "visuals",
    V2JobType.CHECK_IN_ENRICHMENT.value: "check_ins",
    V2JobType.PRACTICE_BANK_GENERATION.value: "practice_bank",
    V2JobType.AUDIO_TEXT_REVIEW.value: "audio_review",
    V2JobType.AUDIO_GENERATION.value: "audio_synthesis",
    V2JobType.BAATCHEET_DIALOGUE_GENERATION.value: "baatcheet_dialogue",
    V2JobType.BAATCHEET_VISUAL_ENRICHMENT.value: "baatcheet_visuals",
}

# Cross-check: every mapped stage_id must exist in the DAG.
for _job_type, _stage_id in JOB_TYPE_TO_STAGE_ID.items():
    if not DAG.has(_stage_id):
        raise RuntimeError(
            f"JOB_TYPE_TO_STAGE_ID maps {_job_type!r} → {_stage_id!r} "
            f"but {_stage_id!r} is not a stage in the topic DAG"
        )
