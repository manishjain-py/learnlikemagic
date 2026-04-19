"""TopicPipelineOrchestrator — runs the 6-stage pipeline for one topic in DAG order.

Layers:
  ① → (② ∥ ③ ∥ ④) → ⑤ → ⑥

Within each layer, stages run in parallel. Layers run sequentially. Halts on
any stage failure (downstream stages stay in their "ready" state on the hub).

Design decisions:
- Polls by `job_id` returned from `launch_<stage>_job`, not `get_latest_job`.
  Using `get_latest_job` would race with a freshly-committed job row.
- One DB session per stage thread. Mirrors `run_in_background_v2` isolation.
- Holds no lock itself. Each sub-stage acquires its own per-stage lock via
  the launcher; a concurrent super-button press fails loudly at the sub-stage.
"""
from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from sqlalchemy.orm import Session

from book_ingestion_v2.models.schemas import QualityLevel, StageId
from book_ingestion_v2.services.chapter_job_service import (
    ChapterJobLockError,
    ChapterJobService,
)
from book_ingestion_v2.services.stage_launchers import LAUNCHER_BY_STAGE

logger = logging.getLogger(__name__)


# Mapping from Quality level to per-stage review_rounds.
QUALITY_ROUNDS: dict[QualityLevel, dict[StageId, int]] = {
    "fast": {
        "explanations": 0,
        "visuals": 0,
        "check_ins": 0,
        "practice_bank": 0,
    },
    "balanced": {
        "explanations": 2,
        "visuals": 1,
        "check_ins": 1,
        "practice_bank": 2,
    },
    "thorough": {
        "explanations": 3,
        "visuals": 2,
        "check_ins": 2,
        "practice_bank": 3,
    },
}

# DAG layers — each layer runs serially; items within a layer run in parallel.
PIPELINE_LAYERS: list[list[StageId]] = [
    ["explanations"],
    ["visuals", "check_ins", "practice_bank"],
    ["audio_review"],
    ["audio_synthesis"],
]

POLL_INTERVAL_SEC = 5
_TERMINAL_OK = {"completed", "completed_with_errors"}
_TERMINAL = _TERMINAL_OK | {"failed"}


@dataclass
class OrchestratorResult:
    pipeline_run_id: str
    stage_results: dict[StageId, str]
    halted_at_layer: Optional[list[StageId]] = None


class TopicPipelineOrchestrator:
    """Runs the 6-stage post-sync pipeline for a single topic."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        book_id: str,
        chapter_id: str,
        guideline_id: str,
        quality_level: QualityLevel,
        force: bool = False,
    ):
        if quality_level not in QUALITY_ROUNDS:
            raise ValueError(f"Unknown quality_level: {quality_level}")
        self._session_factory = session_factory
        self.book_id = book_id
        self.chapter_id = chapter_id
        self.guideline_id = guideline_id
        self.quality_level = quality_level
        self.force = force
        self.rounds = QUALITY_ROUNDS[quality_level]
        self.pipeline_run_id = str(uuid.uuid4())

    def run(self, stages_needed: Iterable[StageId]) -> OrchestratorResult:
        """Run the DAG, halting on any stage failure.

        Returns OrchestratorResult with per-stage terminal state and optional
        halt information.
        """
        needed = set(stages_needed)
        results: dict[StageId, str] = {}
        logger.info(
            f"Pipeline {self.pipeline_run_id} starting for "
            f"guideline={self.guideline_id} stages={sorted(needed)}"
        )

        for layer in PIPELINE_LAYERS:
            to_run: list[StageId] = [s for s in layer if s in needed]
            if not to_run:
                continue

            if len(to_run) == 1:
                stage = to_run[0]
                results[stage] = self._run_one_stage(stage)
            else:
                with ThreadPoolExecutor(max_workers=len(to_run)) as ex:
                    futs = {ex.submit(self._run_one_stage, s): s for s in to_run}
                    for fut in as_completed(futs):
                        stage = futs[fut]
                        try:
                            results[stage] = fut.result()
                        except Exception as e:
                            logger.error(
                                f"Pipeline {self.pipeline_run_id} stage {stage} crashed: {e}",
                                exc_info=True,
                            )
                            results[stage] = "failed"

            failed = [s for s in to_run if results.get(s) == "failed"]
            if failed:
                logger.warning(
                    f"Pipeline {self.pipeline_run_id} halted at layer {to_run}; "
                    f"failed={failed}"
                )
                return OrchestratorResult(
                    pipeline_run_id=self.pipeline_run_id,
                    stage_results=results,
                    halted_at_layer=to_run,
                )

        logger.info(f"Pipeline {self.pipeline_run_id} completed: {results}")
        return OrchestratorResult(
            pipeline_run_id=self.pipeline_run_id, stage_results=results,
        )

    def _run_one_stage(self, stage: StageId) -> str:
        """Launch one stage, poll its job until terminal, return terminal status."""
        db = self._session_factory()
        try:
            launcher = LAUNCHER_BY_STAGE[stage]
            try:
                job_id = launcher(db, **self._launcher_kwargs(stage))
            except ChapterJobLockError as e:
                logger.warning(
                    f"Pipeline {self.pipeline_run_id} could not acquire lock "
                    f"for {stage} on guideline={self.guideline_id}: {e}"
                )
                return "failed"
            return self._poll_to_terminal(db, job_id)
        finally:
            db.close()

    def _launcher_kwargs(self, stage: StageId) -> dict:
        kwargs: dict = {
            "book_id": self.book_id,
            "chapter_id": self.chapter_id,
            "guideline_id": self.guideline_id,
        }
        if stage in ("explanations", "visuals", "check_ins", "practice_bank"):
            kwargs["review_rounds"] = self.rounds[stage]
            if stage == "explanations":
                kwargs["force"] = self.force
                kwargs["mode"] = "generate"
            else:
                kwargs["force"] = self.force
        elif stage == "audio_review":
            kwargs["language"] = None
        # audio_synthesis has no extra args
        return kwargs

    def _poll_to_terminal(self, db: Session, job_id: str) -> str:
        job_service = ChapterJobService(db)
        while True:
            job = job_service.get_job(job_id)
            if job and job.status in _TERMINAL:
                logger.info(
                    f"Pipeline {self.pipeline_run_id} job {job_id} "
                    f"terminal={job.status}"
                )
                return job.status
            time.sleep(POLL_INTERVAL_SEC)


def run_topic_pipeline_sync(
    session_factory: Callable[[], Session],
    *,
    book_id: str,
    chapter_id: str,
    guideline_id: str,
    quality_level: QualityLevel,
    force: bool,
    stages_needed: Iterable[StageId],
) -> OrchestratorResult:
    """Synchronous entry point. Blocks until the pipeline settles.

    Callers that need async behavior should spawn a daemon thread around this.
    """
    orch = TopicPipelineOrchestrator(
        session_factory,
        book_id=book_id,
        chapter_id=chapter_id,
        guideline_id=guideline_id,
        quality_level=quality_level,
        force=force,
    )
    return orch.run(stages_needed)


def run_chapter_pipeline_all(
    session_factory: Callable[[], Session],
    *,
    book_id: str,
    chapter_id: str,
    quality_level: QualityLevel,
    force: bool,
    skip_done: bool = True,
    max_parallel: int = 4,
) -> dict:
    """Run the 6-stage pipeline for every APPROVED topic in a chapter.

    Bounded parallelism — at most `max_parallel` topics run concurrently.
    Topics that are fully done (per `TopicPipelineStatusService`) are skipped
    when `skip_done=True`. Per-topic failures do NOT halt the chapter runner;
    other topics continue.
    """
    from book_ingestion_v2.services.topic_pipeline_status_service import (
        TopicPipelineStatusService,
    )

    chapter_run_id = str(uuid.uuid4())

    session = session_factory()
    try:
        svc = TopicPipelineStatusService(session)
        summary = svc.get_chapter_summary(book_id, chapter_id)
    finally:
        session.close()

    topics_to_run: list[tuple[str, str, list[StageId]]] = []  # (guideline_id, topic_key, stages)
    skipped: list[str] = []
    for t in summary.topics:
        # Re-fetch full per-topic status so we can derive stages_to_run.
        inner = session_factory()
        try:
            inner_svc = TopicPipelineStatusService(inner)
            try:
                full = inner_svc.get_pipeline_status(
                    book_id, chapter_id, t.topic_key
                )
            except LookupError:
                continue
        finally:
            inner.close()
        stages = stages_to_run_from_status(full.stages, force=force)
        if not stages:
            skipped.append(t.topic_key)
            continue
        if skip_done and t.is_fully_done and not force:
            skipped.append(t.topic_key)
            continue
        topics_to_run.append((t.guideline_id, t.topic_key, stages))

    def _run_one_topic(gid: str, topic_key: str, stages: list[StageId]) -> dict:
        orch = TopicPipelineOrchestrator(
            session_factory,
            book_id=book_id,
            chapter_id=chapter_id,
            guideline_id=gid,
            quality_level=quality_level,
            force=force,
        )
        try:
            result = orch.run(stages)
            return {
                "guideline_id": gid,
                "topic_key": topic_key,
                "pipeline_run_id": result.pipeline_run_id,
                "stage_results": result.stage_results,
                "halted_at_layer": result.halted_at_layer,
            }
        except Exception as e:
            logger.error(
                f"Chapter-run {chapter_run_id} topic {topic_key} crashed: {e}",
                exc_info=True,
            )
            return {
                "guideline_id": gid,
                "topic_key": topic_key,
                "error": str(e),
            }

    if topics_to_run:
        with ThreadPoolExecutor(max_workers=max(1, min(max_parallel, len(topics_to_run)))) as ex:
            futs = [ex.submit(_run_one_topic, *t) for t in topics_to_run]
            for _ in as_completed(futs):
                pass

    return {
        "chapter_run_id": chapter_run_id,
        "topics_queued": len(topics_to_run),
        "skipped_topics": skipped,
    }


def stages_to_run_from_status(
    status_stages,
    *,
    force: bool,
) -> list[StageId]:
    """Given a list[StageStatus], decide which stages the orchestrator should run.

    - Skip `running` (another run is already on it).
    - Skip `done` unless force.
    - Include everything else (ready, warning, blocked-downstream, failed).
    """
    stages: list[StageId] = []
    for s in status_stages:
        if s.state == "running":
            continue
        if s.state == "done" and not force:
            continue
        stages.append(s.stage_id)
    return stages
