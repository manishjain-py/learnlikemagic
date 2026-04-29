"""TopicPipelineOrchestrator — runs the topic-scope pipeline for one topic.

Stages run serially in topological order (see `dag/topic_pipeline_dag.py`).
The DAG is the single source of truth for stage identity, dependencies, and
ordering — adding a stage means adding one file under
`book_ingestion_v2/stages/` and one entry in `STAGES`.

**Serialized within a topic.** The partial unique index
`idx_chapter_active_topic_job` enforces at most one active job per
`(chapter_id, guideline_id)`, so even sibling stages cannot actually run
concurrently — a second launch hits `ChapterJobLockError`. The lock is
load-bearing: visuals and check-ins both mutate the same
`topic_explanations.cards_json` row in-place; concurrent writes would race.
We rely on cross-topic parallelism (chapter runner spawns multiple
orchestrators) for throughput.

Design decisions:
- Polls by `job_id` returned from `Stage.launch`, not `get_latest_job`.
  Using `get_latest_job` would race with a freshly-committed job row.
- One DB session per stage call. Mirrors `run_in_background_v2` isolation.
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

from book_ingestion_v2.constants import HEARTBEAT_STALE_THRESHOLD
from book_ingestion_v2.dag.launcher_map import LAUNCHER_BY_STAGE
from book_ingestion_v2.dag.topic_pipeline_dag import DAG
from book_ingestion_v2.models.schemas import QualityLevel, StageId
from book_ingestion_v2.services.chapter_job_service import (
    ChapterJobLockError,
    ChapterJobService,
)

logger = logging.getLogger(__name__)


# Mapping from Quality level to per-stage review_rounds.
QUALITY_ROUNDS: dict[QualityLevel, dict[StageId, int]] = {
    "fast": {
        "explanations": 0,
        "visuals": 0,
        "check_ins": 0,
        "practice_bank": 0,
        "baatcheet_dialogue": 0,
    },
    "balanced": {
        "explanations": 2,
        "visuals": 1,
        "check_ins": 1,
        "practice_bank": 2,
        "baatcheet_dialogue": 1,
    },
    "thorough": {
        "explanations": 3,
        "visuals": 2,
        "check_ins": 2,
        "practice_bank": 3,
        "baatcheet_dialogue": 2,
    },
}

POLL_INTERVAL_SEC = 5
# Absolute upper bound on polling — pure safety net. Primary stale detection
# is heartbeat-based via `ChapterJobService.is_job_heartbeat_stale`, which
# catches a dead backing thread within `HEARTBEAT_STALE_THRESHOLD` (30 min).
# This cap exists only to stop the orchestrator if a stage keeps heartbeating
# forever. 4 hours is comfortably longer than any realistic real run.
MAX_POLL_WALL_TIME_SEC = 4 * 60 * 60  # 4 hours
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

        for stage in DAG.topo_sort():
            stage_id: StageId = stage.id  # type: ignore[assignment]
            if stage_id not in needed:
                continue

            results[stage_id] = self._run_one_stage(stage_id)

            if results[stage_id] == "failed":
                logger.warning(
                    f"Pipeline {self.pipeline_run_id} halted at stage {stage_id}"
                )
                return OrchestratorResult(
                    pipeline_run_id=self.pipeline_run_id,
                    stage_results=results,
                    halted_at_layer=[stage_id],
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
            # Tag observability BEFORE polling begins. `update_progress`
            # preserves this key on subsequent detail overwrites.
            try:
                ChapterJobService(db).record_pipeline_run_id(
                    job_id, self.pipeline_run_id
                )
            except Exception as e:
                logger.warning(
                    f"Could not tag pipeline_run_id on job {job_id}: {e}"
                )
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
        elif stage == "baatcheet_dialogue":
            kwargs["force"] = self.force
            kwargs["review_rounds"] = self.rounds["baatcheet_dialogue"]
        elif stage == "baatcheet_visuals":
            kwargs["force"] = self.force
        elif stage == "audio_review":
            kwargs["language"] = None
            kwargs["force"] = self.force
        elif stage == "audio_synthesis":
            kwargs["force"] = self.force
        elif stage == "baatcheet_audio_review":
            kwargs["language"] = None
            kwargs["force"] = self.force
        elif stage == "baatcheet_audio_synthesis":
            kwargs["force"] = self.force
        return kwargs

    def _poll_to_terminal(self, db: Session, job_id: str) -> str:
        """Poll the stage job's DB row until it reaches a terminal state.

        Two safety nets against orphaned jobs (backing thread died without
        calling `release_lock` — OOM kill, process crash, or a BaseException
        that escaped `run_in_background_v2`'s `except Exception`):

        1. **Heartbeat staleness (primary).** Every iteration asks the service
           whether the job's `heartbeat_at` is older than
           `HEARTBEAT_STALE_THRESHOLD` (30 min). This catches a dead thread
           within ~30 min regardless of how long the stage has been running.
        2. **Absolute wall-time cap (fallback).** `MAX_POLL_WALL_TIME_SEC`
           (4 hours) — stops truly runaway jobs that keep heartbeating forever.
        """
        job_service = ChapterJobService(db)
        start = time.monotonic()
        while True:
            job = job_service.get_job(job_id)
            if job and job.status in _TERMINAL:
                logger.info(
                    f"Pipeline {self.pipeline_run_id} job {job_id} "
                    f"terminal={job.status}"
                )
                return job.status

            if job_service.is_job_heartbeat_stale(job_id):
                logger.warning(
                    f"Pipeline {self.pipeline_run_id} job {job_id} "
                    f"heartbeat stale — marking failed"
                )
                try:
                    job_service.release_lock(
                        job_id,
                        status="failed",
                        error=(
                            "Heartbeat stale — backing thread likely died without "
                            "releasing the lock."
                        ),
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to release stale job {job_id}: {e}",
                        exc_info=True,
                    )
                return "failed"

            if time.monotonic() - start > MAX_POLL_WALL_TIME_SEC:
                logger.warning(
                    f"Pipeline {self.pipeline_run_id} job {job_id} "
                    f"hit absolute poll cap of {MAX_POLL_WALL_TIME_SEC}s — marking failed"
                )
                try:
                    job_service.release_lock(
                        job_id,
                        status="failed",
                        error=(
                            f"Orchestrator absolute poll cap ({MAX_POLL_WALL_TIME_SEC}s) reached."
                        ),
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to release capped job {job_id}: {e}",
                        exc_info=True,
                    )
                return "failed"
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

    # Single-read: load full per-topic statuses once, derive everything else
    # from the same snapshot. Previous revision made 2N reads per chapter.
    session = session_factory()
    try:
        svc = TopicPipelineStatusService(session)
        statuses = svc.get_chapter_topic_statuses(book_id, chapter_id)
    finally:
        session.close()

    topics_to_run: list[tuple[str, str, list[StageId]]] = []  # (guideline_id, topic_key, stages)
    skipped: list[str] = []
    for status in statuses:
        is_fully_done = all(s.state == "done" for s in status.stages)
        if skip_done and is_fully_done and not force:
            skipped.append(status.topic_key)
            continue
        stages = stages_to_run_from_status(status.stages, force=force)
        if not stages:
            skipped.append(status.topic_key)
            continue
        topics_to_run.append((status.guideline_id, status.topic_key, stages))

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
