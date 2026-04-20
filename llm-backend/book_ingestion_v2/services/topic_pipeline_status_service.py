"""Compute per-topic pipeline status for the admin hub.

Consolidates status for all 6 post-sync stages (Explanations, Visuals,
Check-ins, Practice bank, Audio review, Audio synthesis) into a single
response. Staleness is anchored to `max(topic_explanations.created_at)`
for the guideline — this is stable across in-place `cards_json` writes
during visuals/check-ins/audio synthesis (which advance `updated_at` but
are not semantic invalidations).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.models.database import ChapterProcessingJob
from book_ingestion_v2.models.schemas import (
    ChapterPipelineSummaryResponse,
    ChapterPipelineTopicSummary,
    ChapterPipelineTotals,
    StageCountsByState,
    StageId,
    StageState,
    StageStatus,
    TopicPipelineStatusResponse,
)

logger = logging.getLogger(__name__)


# Post-sync job types — during Phase 1, historical rows for these have
# `chapter_id` overloaded to hold a guideline UUID. Post-Phase-2 migration,
# the native `guideline_id` column is authoritative.
_POST_SYNC_JOB_TYPES: frozenset[str] = frozenset(
    {
        V2JobType.EXPLANATION_GENERATION.value,
        V2JobType.VISUAL_ENRICHMENT.value,
        V2JobType.CHECK_IN_ENRICHMENT.value,
        V2JobType.PRACTICE_BANK_GENERATION.value,
        V2JobType.AUDIO_TEXT_REVIEW.value,
        V2JobType.AUDIO_GENERATION.value,
    }
)

_PRACTICE_DONE_THRESHOLD = 30

_STAGE_JOB_TYPE: dict[StageId, str] = {
    "explanations": V2JobType.EXPLANATION_GENERATION.value,
    "visuals": V2JobType.VISUAL_ENRICHMENT.value,
    "check_ins": V2JobType.CHECK_IN_ENRICHMENT.value,
    "practice_bank": V2JobType.PRACTICE_BANK_GENERATION.value,
    "audio_review": V2JobType.AUDIO_TEXT_REVIEW.value,
    "audio_synthesis": V2JobType.AUDIO_GENERATION.value,
}

_TERMINAL_OK_STATES = {"completed", "completed_with_errors"}


class TopicPipelineStatusService:
    """Read-only service — computes 6-stage pipeline status for one topic."""

    def __init__(self, db: Session):
        self.db = db

    # ───── Public API ─────

    def get_pipeline_status(
        self, book_id: str, chapter_id: str, topic_key: str
    ) -> TopicPipelineStatusResponse:
        """Return consolidated 6-stage status for a topic.

        Raises LookupError if the guideline cannot be found for the given
        book/chapter/topic_key triple.
        """
        guideline = self._load_guideline(book_id, chapter_id, topic_key)
        if not guideline:
            raise LookupError(
                f"No teaching_guideline for book={book_id} chapter={chapter_id} topic={topic_key}"
            )

        explanations = self._load_explanations(guideline.id)
        content_anchor = self._content_anchor(explanations)

        stages: list[StageStatus] = [
            self._stage_explanations(guideline.id, explanations),
            self._stage_visuals(guideline.id, explanations),
            self._stage_check_ins(guideline.id, explanations),
            self._stage_practice_bank(guideline.id, explanations, content_anchor),
            self._stage_audio_review(guideline.id, chapter_id, explanations, content_anchor),
            self._stage_audio_synthesis(guideline.id, explanations),
        ]

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

    # ───── Job lookup (handles historical chapter_id overload during Phase 1) ─────

    def _latest_job_for_guideline(
        self, chapter_id: str, guideline_id: str, job_type: str
    ) -> Optional[ChapterProcessingJob]:
        """Find the latest job for a topic.

        Primary path (post-migration): filter by native `guideline_id` column.
        Fallback (historical rows): pre-migration post-sync jobs stored the
        guideline UUID in `chapter_id` with `guideline_id IS NULL`. We OR those
        in so the status service sees the complete history regardless of
        migration state.
        """
        return (
            self.db.query(ChapterProcessingJob)
            .filter(
                ChapterProcessingJob.job_type == job_type,
                (ChapterProcessingJob.guideline_id == guideline_id)
                | (
                    (ChapterProcessingJob.guideline_id.is_(None))
                    & (ChapterProcessingJob.chapter_id == guideline_id)
                ),
            )
            .order_by(ChapterProcessingJob.created_at.desc())
            .first()
        )

    # ───── Stage computation ─────

    def _stage_explanations(self, guideline_id: str, explanations) -> StageStatus:
        job = self._latest_job_for_guideline(
            chapter_id="", guideline_id=guideline_id, job_type=_STAGE_JOB_TYPE["explanations"]
        )
        has_cards = any(bool(e.cards_json) for e in explanations)
        state, summary, warnings = self._derive_state(
            stage_id="explanations",
            artifact_present=has_cards,
            artifact_summary=(
                f"{len(explanations)} variant(s)" if explanations else "No variants"
            ),
            job=job,
            has_warnings=False,
            blocked_by=None,
        )
        return _build_stage("explanations", state, summary, warnings, job=job)

    def _stage_visuals(self, guideline_id: str, explanations) -> StageStatus:
        explanations_done = any(bool(e.cards_json) for e in explanations)
        job = self._latest_job_for_guideline(
            chapter_id="", guideline_id=guideline_id, job_type=_STAGE_JOB_TYPE["visuals"]
        )

        if not explanations_done:
            return _build_blocked("visuals", blocked_by="explanations", job=job)

        cards_with_visuals = 0
        layout_warnings = 0
        total_cards = 0
        for expl in explanations:
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
        state, summary, warnings = self._derive_state(
            stage_id="visuals",
            artifact_present=artifact_present,
            artifact_summary=summary,
            job=job,
            has_warnings=has_warning,
            blocked_by=None,
            warnings=warnings,
        )
        return _build_stage("visuals", state, summary, warnings, job=job)

    def _stage_check_ins(self, guideline_id: str, explanations) -> StageStatus:
        explanations_done = any(bool(e.cards_json) for e in explanations)
        job = self._latest_job_for_guideline(
            chapter_id="", guideline_id=guideline_id, job_type=_STAGE_JOB_TYPE["check_ins"]
        )

        if not explanations_done:
            return _build_blocked("check_ins", blocked_by="explanations", job=job)

        check_in_count = 0
        for expl in explanations:
            for card in expl.cards_json or []:
                if isinstance(card, dict) and card.get("card_type") == "check_in":
                    check_in_count += 1

        summary = f"{check_in_count} check-in card(s)"
        state, summary, warnings = self._derive_state(
            stage_id="check_ins",
            artifact_present=check_in_count > 0,
            artifact_summary=summary,
            job=job,
            has_warnings=False,
            blocked_by=None,
        )
        return _build_stage("check_ins", state, summary, warnings, job=job)

    def _stage_practice_bank(
        self, guideline_id: str, explanations, content_anchor: Optional[datetime]
    ) -> StageStatus:
        from shared.models.entities import PracticeQuestion

        explanations_done = any(bool(e.cards_json) for e in explanations)
        job = self._latest_job_for_guideline(
            chapter_id="",
            guideline_id=guideline_id,
            job_type=_STAGE_JOB_TYPE["practice_bank"],
        )

        if not explanations_done:
            return _build_blocked("practice_bank", blocked_by="explanations", job=job)

        rows = (
            self.db.query(PracticeQuestion)
            .filter(PracticeQuestion.guideline_id == guideline_id)
            .all()
        )
        count = len(rows)
        earliest = min((r.created_at for r in rows if r.created_at), default=None)

        is_stale = bool(
            content_anchor
            and earliest
            and earliest < content_anchor
        )

        warnings: list[str] = []
        if is_stale:
            warnings.append("Practice bank predates latest explanations — regenerate to refresh")

        if count == 0:
            state: StageState = "ready" if not _job_failed(job) else "failed"
            summary = "No practice questions yet"
        elif count >= _PRACTICE_DONE_THRESHOLD and not is_stale:
            state = "done"
            summary = f"{count} questions"
        else:
            state = "warning"
            summary = f"{count} questions" + (" (stale)" if is_stale else " (partial)")

        # Override with running/failed/ready derived from job status
        state, summary, warnings = self._overlay_job_state(
            state=state,
            summary=summary,
            warnings=warnings,
            job=job,
            artifact_present=count > 0,
        )
        return _build_stage(
            "practice_bank", state, summary, warnings, job=job, is_stale=is_stale
        )

    def _stage_audio_review(
        self,
        guideline_id: str,
        chapter_id: str,
        explanations,
        content_anchor: Optional[datetime],
    ) -> StageStatus:
        explanations_done = any(bool(e.cards_json) for e in explanations)
        job = self._latest_job_for_guideline(
            chapter_id=chapter_id,
            guideline_id=guideline_id,
            job_type=_STAGE_JOB_TYPE["audio_review"],
        )

        if not explanations_done:
            return _build_blocked("audio_review", blocked_by="explanations", job=job)

        if job is None:
            return StageStatus(
                stage_id="audio_review",
                state="ready",
                summary="No audio review run yet",
            )

        is_stale = bool(
            content_anchor
            and job.completed_at
            and job.completed_at < content_anchor
        )

        warnings: list[str] = []
        if is_stale:
            warnings.append("Audio review predates latest explanations — rerun to refresh")

        if job.status == "completed" and not is_stale:
            state: StageState = "done"
            summary = f"Reviewed {_fmt_ago(job.completed_at)}"
        elif job.status == "completed_with_errors" or is_stale:
            state = "warning"
            summary = (
                f"Completed with errors ({_fmt_ago(job.completed_at)})"
                if job.status == "completed_with_errors"
                else f"Completed {_fmt_ago(job.completed_at)} (stale)"
            )
        elif job.status == "failed":
            state = "failed"
            summary = f"Last run failed {_fmt_ago(job.completed_at)}"
        elif job.status in ("pending", "running"):
            state = "running"
            summary = "Running…"
        else:
            state = "ready"
            summary = job.status

        return _build_stage(
            "audio_review", state, summary, warnings, job=job, is_stale=is_stale
        )

    def _stage_audio_synthesis(self, guideline_id: str, explanations) -> StageStatus:
        explanations_done = any(bool(e.cards_json) for e in explanations)
        job = self._latest_job_for_guideline(
            chapter_id="",
            guideline_id=guideline_id,
            job_type=_STAGE_JOB_TYPE["audio_synthesis"],
        )

        if not explanations_done:
            return _build_blocked("audio_synthesis", blocked_by="explanations", job=job)

        from book_ingestion_v2.services.audio_generation_service import AudioGenerationService

        total_clips = 0
        clips_with_audio = 0
        for expl in explanations:
            t, w = AudioGenerationService.count_audio_items(expl.cards_json or [])
            total_clips += t
            clips_with_audio += w

        if total_clips == 0:
            summary = "No audio clips yet"
            artifact_present = False
        else:
            summary = f"{clips_with_audio}/{total_clips} audio clips have pre-computed MP3"
            artifact_present = clips_with_audio > 0

        if total_clips > 0 and clips_with_audio == total_clips:
            state: StageState = "done"
        elif 0 < clips_with_audio < total_clips:
            state = "warning"
        else:
            state = "ready"

        state, summary, warnings = self._overlay_job_state(
            state=state,
            summary=summary,
            warnings=[],
            job=job,
            artifact_present=artifact_present,
        )
        return _build_stage("audio_synthesis", state, summary, warnings, job=job)

    # ───── Shared helpers ─────

    def _derive_state(
        self,
        *,
        stage_id: StageId,
        artifact_present: bool,
        artifact_summary: str,
        job: Optional[ChapterProcessingJob],
        has_warnings: bool,
        blocked_by: Optional[StageId],
        warnings: Optional[list[str]] = None,
    ) -> tuple[StageState, str, list[str]]:
        warnings = list(warnings or [])
        if blocked_by:
            return "blocked", f"Blocked — run {blocked_by} first", warnings

        if job and job.status in ("pending", "running"):
            return "running", "Running…", warnings

        if artifact_present:
            if has_warnings:
                return "warning", artifact_summary, warnings
            return "done", artifact_summary, warnings

        # No artifact yet.
        if job and job.status == "failed":
            return "failed", job.error_message or "Last run failed", warnings
        return "ready", artifact_summary, warnings

    def _overlay_job_state(
        self,
        *,
        state: StageState,
        summary: str,
        warnings: list[str],
        job: Optional[ChapterProcessingJob],
        artifact_present: bool,
    ) -> tuple[StageState, str, list[str]]:
        if job and job.status in ("pending", "running"):
            return "running", "Running…", warnings
        if not artifact_present and job and job.status == "failed":
            return "failed", job.error_message or "Last run failed", warnings
        return state, summary, warnings

    def _detect_pipeline_run_id(self, stages: Iterable[StageStatus]) -> Optional[str]:
        # No persisted pipeline_run table in v1; the value is surfaced only while
        # a Phase 2+ orchestrated run is in-flight. For now, returning None is
        # correct — the orchestrator tags progress_detail but the status service
        # doesn't read it back in v1.
        return None


# ───── Module-level helpers ─────


def _build_stage(
    stage_id: StageId,
    state: StageState,
    summary: str,
    warnings: list[str],
    *,
    job: Optional[ChapterProcessingJob] = None,
    is_stale: bool = False,
) -> StageStatus:
    return StageStatus(
        stage_id=stage_id,
        state=state,
        summary=summary,
        warnings=warnings,
        is_stale=is_stale,
        last_job_id=(job.id if job else None),
        last_job_status=(job.status if job else None),
        last_job_error=(job.error_message if job and job.error_message else None),
        last_job_completed_at=(job.completed_at if job else None),
    )


def _build_blocked(
    stage_id: StageId,
    *,
    blocked_by: StageId,
    job: Optional[ChapterProcessingJob] = None,
) -> StageStatus:
    return StageStatus(
        stage_id=stage_id,
        state="blocked",
        summary=f"Blocked — run {blocked_by} first",
        blocked_by=blocked_by,
        last_job_id=(job.id if job else None),
        last_job_status=(job.status if job else None),
        last_job_error=(job.error_message if job and job.error_message else None),
        last_job_completed_at=(job.completed_at if job else None),
    )


def _job_failed(job: Optional[ChapterProcessingJob]) -> bool:
    return bool(job and job.status == "failed")


def _tally_stage_counts(stages: Iterable[StageStatus]) -> StageCountsByState:
    counts = StageCountsByState()
    for s in stages:
        setattr(counts, s.state, getattr(counts, s.state) + 1)
    return counts


def _fmt_ago(ts: Optional[datetime]) -> str:
    if not ts:
        return "just now"
    delta = datetime.utcnow() - ts
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"
