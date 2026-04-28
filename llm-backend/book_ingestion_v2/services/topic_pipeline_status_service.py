"""Compute per-topic pipeline status for the admin hub.

Coordinator over the topic-pipeline DAG: loads the shared per-topic context
once, then dispatches to each stage's `status_check` to populate the
response. The per-stage logic lives under `book_ingestion_v2/stages/`.

Staleness for downstream stages is anchored to
`max(topic_explanations.created_at)` for the guideline — stable across
in-place `cards_json` writes during visuals/check-ins/audio synthesis
(which advance `updated_at` but are not semantic invalidations).
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

        return TopicPipelineStatusResponse(
            topic_key=topic_key,
            topic_title=guideline.topic_title or guideline.topic,
            guideline_id=guideline.id,
            chapter_id=chapter_id,
            chapter_preflight_ok=True,
            pipeline_run_id=self._detect_pipeline_run_id(stages),
            stages=stages,
        )

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
