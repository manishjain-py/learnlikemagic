"""Compute per-topic pipeline status for the admin hub.

Coordinator over the topic-pipeline DAG: loads the shared per-topic context
once, then dispatches to each stage's `status_check` to populate the
response. The per-stage logic lives under `book_ingestion_v2/stages/`.

Staleness for downstream stages is anchored to
`max(topic_explanations.created_at)` for the guideline — stable across
in-place `cards_json` writes during visuals/check-ins/audio synthesis
(which advance `updated_at` but are not semantic invalidations).

Phase 2: every read-time pass also backfills `topic_stage_runs` rows for
terminal stages that pre-date the table. The backfill is a write-only side
effect — the response shape is unchanged. Phase 3+ will start preferring
those rows on read for cascade staleness.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from book_ingestion_v2.dag.topic_pipeline_dag import DAG
from book_ingestion_v2.dag.types import StatusContext
from book_ingestion_v2.models.schemas import (
    ChapterPipelineSummaryResponse,
    ChapterPipelineTopicSummary,
    ChapterPipelineTotals,
    StageCountsByState,
    StageStatus,
    TopicPipelineStatusResponse,
)
from book_ingestion_v2.repositories.topic_stage_run_repository import (
    TopicStageRunRepository,
)

logger = logging.getLogger(__name__)


class TopicPipelineStatusService:
    """Read-only service — computes pipeline status for one topic by
    delegating to each stage's `status_check`."""

    def __init__(self, db: Session):
        self.db = db

    # ───── Public API ─────

    def get_pipeline_status(
        self, book_id: str, chapter_id: str, topic_key: str
    ) -> TopicPipelineStatusResponse:
        """Return consolidated status for every DAG stage.

        Raises LookupError if the guideline cannot be found for the given
        book/chapter/topic_key triple.
        """
        guideline = self._load_guideline(book_id, chapter_id, topic_key)
        if not guideline:
            raise LookupError(
                f"No teaching_guideline for book={book_id} chapter={chapter_id} topic={topic_key}"
            )

        explanations = self._load_explanations(guideline.id)
        ctx = StatusContext(
            db=self.db,
            guideline_id=guideline.id,
            chapter_id=chapter_id,
            explanations=explanations,
            content_anchor=self._content_anchor(explanations),
        )

        stages: list[StageStatus] = [stage.status_check(ctx) for stage in DAG.stages]

        self._backfill_topic_stage_runs(guideline.id, stages)
        self._overlay_topic_stage_run_signals(guideline.id, stages)

        return TopicPipelineStatusResponse(
            topic_key=topic_key,
            topic_title=guideline.topic_title or guideline.topic,
            guideline_id=guideline.id,
            chapter_id=chapter_id,
            chapter_preflight_ok=True,
            pipeline_run_id=self._detect_pipeline_run_id(stages),
            stages=stages,
        )

    def run_backfill_for_guideline(
        self, guideline_id: str, chapter_id: str
    ) -> None:
        """Run the Phase 2 backfill side effect without topic_key resolution.

        The DAG endpoint reaches this with `guideline_id` already in
        hand. `get_pipeline_status` requires `(book_id, chapter_id,
        topic_key)` and `_load_guideline` filters on `topic_key`, which
        excludes legacy guidelines whose `topic_key` is NULL — those
        topics 404 from `/topics/{guideline_id}/dag` even though the id
        resolved fine. This entry point skips topic_key entirely: load
        explanations by id, run each stage's `status_check`, backfill
        `topic_stage_runs`. The DAG view reads `is_stale` directly off
        the rows, so we don't need the overlay step here.

        No-ops if the guideline can't be found — the endpoint already
        returned 404 via `_resolve_topic_keys` before calling this.
        """
        from shared.models.entities import TeachingGuideline

        guideline = (
            self.db.query(TeachingGuideline)
            .filter(TeachingGuideline.id == guideline_id)
            .first()
        )
        if not guideline:
            return

        explanations = self._load_explanations(guideline_id)
        ctx = StatusContext(
            db=self.db,
            guideline_id=guideline_id,
            chapter_id=chapter_id,
            explanations=explanations,
            content_anchor=self._content_anchor(explanations),
        )
        stages: list[StageStatus] = [
            stage.status_check(ctx) for stage in DAG.stages
        ]
        self._backfill_topic_stage_runs(guideline_id, stages)

    def get_chapter_topic_statuses(
        self, book_id: str, chapter_id: str
    ) -> list[TopicPipelineStatusResponse]:
        """Return full per-topic status for every APPROVED guideline in the chapter.

        Shared by `get_chapter_summary` (for the BookV2Detail chip) and the
        chapter-level orchestrator (to derive `stages_to_run`). Computing
        full per-topic status once and reusing it avoids a 2N per-chapter
        query pass.
        """
        guidelines = self._load_chapter_guidelines(book_id, chapter_id)
        statuses: list[TopicPipelineStatusResponse] = []
        for guideline in guidelines:
            topic_key = guideline.topic_key or guideline.topic
            try:
                statuses.append(
                    self.get_pipeline_status(book_id, chapter_id, topic_key)
                )
            except LookupError:
                continue
        return statuses

    def get_chapter_summary(
        self, book_id: str, chapter_id: str
    ) -> ChapterPipelineSummaryResponse:
        """Aggregate per-topic rollups for all approved guidelines in a chapter."""
        statuses = self.get_chapter_topic_statuses(book_id, chapter_id)

        topic_summaries: list[ChapterPipelineTopicSummary] = []
        fully_done = 0
        partial = 0
        not_started = 0

        for status in statuses:
            counts = _tally_stage_counts(status.stages)
            is_fully_done = all(s.state == "done" for s in status.stages)
            any_artifact = any(
                s.state not in ("ready", "blocked") for s in status.stages
            )

            if is_fully_done:
                fully_done += 1
            elif any_artifact:
                partial += 1
            else:
                not_started += 1

            topic_summaries.append(
                ChapterPipelineTopicSummary(
                    topic_key=status.topic_key,
                    topic_title=status.topic_title,
                    guideline_id=status.guideline_id,
                    stage_counts=counts,
                    is_fully_done=is_fully_done,
                )
            )

        return ChapterPipelineSummaryResponse(
            chapter_id=chapter_id,
            topics=topic_summaries,
            chapter_totals=ChapterPipelineTotals(
                topics_total=len(topic_summaries),
                topics_fully_done=fully_done,
                topics_partial=partial,
                topics_not_started=not_started,
            ),
        )

    # ───── Loaders ─────

    def _load_guideline(self, book_id: str, chapter_id: str, topic_key: str):
        from shared.models.entities import TeachingGuideline
        from book_ingestion_v2.repositories.chapter_repository import ChapterRepository

        chapter = ChapterRepository(self.db).get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            return None
        chapter_key = f"chapter-{chapter.chapter_number}"

        return (
            self.db.query(TeachingGuideline)
            .filter(
                TeachingGuideline.book_id == book_id,
                TeachingGuideline.chapter_key == chapter_key,
                TeachingGuideline.topic_key == topic_key,
            )
            .first()
        )

    def _load_chapter_guidelines(self, book_id: str, chapter_id: str):
        from shared.models.entities import TeachingGuideline
        from book_ingestion_v2.repositories.chapter_repository import ChapterRepository

        chapter = ChapterRepository(self.db).get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            return []
        chapter_key = f"chapter-{chapter.chapter_number}"

        return (
            self.db.query(TeachingGuideline)
            .filter(
                TeachingGuideline.book_id == book_id,
                TeachingGuideline.chapter_key == chapter_key,
                TeachingGuideline.review_status == "APPROVED",
            )
            .order_by(TeachingGuideline.topic_sequence)
            .all()
        )

    def _load_explanations(self, guideline_id: str):
        from shared.models.entities import TopicExplanation

        return (
            self.db.query(TopicExplanation)
            .filter(TopicExplanation.guideline_id == guideline_id)
            .all()
        )

    # ───── Phase 2 lazy backfill ─────

    def _backfill_topic_stage_runs(
        self, guideline_id: str, stages: list[StageStatus]
    ) -> None:
        """Reconcile + backfill `topic_stage_runs` rows.

        Two passes (both write-only side effects — the response shape is
        unchanged):

        1. **Reconcile stuck-running rows.** If a row says `running` but
           its `last_job_id` resolves to a terminal job
           (`completed`/`completed_with_errors`/`failed`), update the row
           to the matching terminal state with timing derived from the
           job. This catches the orphan case where the worker died after
           `upsert_running` but before the terminal-write hook (heartbeat
           reaping marks the job failed but does not touch
           `topic_stage_runs`).

        2. **Backfill missing rows.** For stages that reconstruction shows
           are `done`/`failed` and no row exists, write a derived row.

        The 4-state row vocabulary (`pending|running|done|failed`) is
        narrower than the read-side `StageStatus` (adds
        `warning`/`ready`/`blocked`); only `done`/`failed` get backfilled.

        Wrapped in a broad except so a backfill DB error never breaks the
        read response. The except rolls back so the caller's session
        stays usable.
        """
        try:
            repo = TopicStageRunRepository(self.db)
            rows = repo.list_for_topic(guideline_id)
            by_stage = {r.stage_id: r for r in rows}

            self._reconcile_stuck_running_rows(repo, by_stage)

            for s in stages:
                if s.stage_id in by_stage:
                    continue
                if s.state not in ("done", "failed"):
                    continue
                repo.upsert_backfill(
                    guideline_id=guideline_id,
                    stage_id=s.stage_id,
                    state=s.state,
                    completed_at=s.last_job_completed_at,
                    last_job_id=s.last_job_id,
                )
        except Exception as e:
            logger.warning(
                f"topic_stage_runs backfill failed for guideline={guideline_id}: {e}",
                exc_info=True,
            )
            # The backfill shares the caller's session — rollback so
            # downstream code (the status response is read-only, but the
            # request handler may still close the session cleanly) doesn't
            # hit a `PendingRollbackError` because a backfill commit died
            # mid-flight.
            try:
                self.db.rollback()
            except Exception:
                pass

    def _overlay_topic_stage_run_signals(
        self, guideline_id: str, stages: list[StageStatus]
    ) -> None:
        """Phase 3 — overlay row-only signals onto reconstruction results.

        Reconstruction (`status_check` per stage) is rich on
        `done`/`warning`/`ready`/`blocked`/`failed`/`running` because it
        reads artifacts + the latest job. But the cascade-marked
        `is_stale` flag lives only in `topic_stage_runs` rows; without
        this overlay the dashboard would never show "stage X is done
        but its inputs are now stale".

        Wrapped in a broad except — the response is still useful even
        if the overlay fails. Rolls back on failure for session
        hygiene.
        """
        try:
            rows = TopicStageRunRepository(self.db).list_for_topic(guideline_id)
            stale_set = {r.stage_id for r in rows if r.is_stale}
            for s in stages:
                if s.stage_id in stale_set:
                    s.is_stale = True
        except Exception as e:
            logger.warning(
                f"is_stale overlay failed for guideline={guideline_id}: {e}",
                exc_info=True,
            )
            try:
                self.db.rollback()
            except Exception:
                pass

    def _reconcile_stuck_running_rows(
        self, repo: TopicStageRunRepository, by_stage: dict
    ) -> None:
        """If a row says `running` but its job is terminal, fix the row.

        Heartbeat reaping (`ChapterJobService._mark_stale`) marks the
        chapter_processing_jobs row failed but doesn't touch
        topic_stage_runs — without this reconciliation, a dead worker
        leaves a stuck `running` row that Phase 3 cascade would read as
        live and never advance past.
        """
        from book_ingestion_v2.models.database import ChapterProcessingJob

        stuck = [
            r for r in by_stage.values()
            if r.state == "running" and r.last_job_id
        ]
        if not stuck:
            return

        job_ids = [r.last_job_id for r in stuck]
        jobs = (
            self.db.query(ChapterProcessingJob)
            .filter(ChapterProcessingJob.id.in_(job_ids))
            .all()
        )
        jobs_by_id = {j.id: j for j in jobs}

        for row in stuck:
            job = jobs_by_id.get(row.last_job_id)
            if job is None:
                continue
            if job.status in ("completed", "completed_with_errors"):
                terminal_state = "done"
            elif job.status == "failed":
                terminal_state = "failed"
            else:
                continue  # job still running — leave the row alone

            duration_ms = None
            if job.started_at and job.completed_at:
                duration_ms = int(
                    (job.completed_at - job.started_at).total_seconds() * 1000
                )
            summary = None
            if terminal_state == "failed" and job.error_message:
                summary = {"error": job.error_message[:500], "reconciled": True}
            elif terminal_state == "done":
                summary = {"reconciled": True}

            repo.upsert_terminal(
                guideline_id=row.guideline_id,
                stage_id=row.stage_id,
                state=terminal_state,
                completed_at=job.completed_at,
                duration_ms=duration_ms,
                started_at=job.started_at,
                summary=summary,
                last_job_id=job.id,
            )

            # Phase 3 — fire the cascade hook so an active cascade can
            # advance past a dead worker. The terminal-write hook in
            # `run_in_background_v2` covers the happy path; this covers
            # the orphan-recovery path. Wrapped so a cascade bug can't
            # break the reconciliation write above.
            try:
                from book_ingestion_v2.dag.cascade import (
                    get_cascade_orchestrator,
                )
                get_cascade_orchestrator().on_stage_complete(
                    guideline_id=row.guideline_id,
                    stage_id=row.stage_id,
                    terminal_state=terminal_state,
                )
            except Exception as e:
                logger.warning(
                    f"cascade on_stage_complete failed during reconciliation "
                    f"of stage={row.stage_id}: {e}",
                    exc_info=True,
                )

    # ───── Staleness anchor ─────

    @staticmethod
    def _content_anchor(explanations) -> Optional[datetime]:
        """Latest explanation row's `created_at` — stable across in-place writes."""
        return max((e.created_at for e in explanations if e.created_at), default=None)

    # ───── pipeline_run_id detection (Phase 2+) ─────

    def _detect_pipeline_run_id(self, stages: Iterable[StageStatus]) -> Optional[str]:
        # No persisted pipeline_run table in v1; the value is surfaced only while
        # a Phase 2+ orchestrated run is in-flight. For now, returning None is
        # correct — the orchestrator tags progress_detail but the status service
        # doesn't read it back in v1.
        return None


# ───── Module-level helpers ─────


def _tally_stage_counts(stages: Iterable[StageStatus]) -> StageCountsByState:
    counts = StageCountsByState()
    for s in stages:
        setattr(counts, s.state, getattr(counts, s.state) + 1)
    return counts
