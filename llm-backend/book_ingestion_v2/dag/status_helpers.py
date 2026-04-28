"""Shared helpers used by every stage's `status_check`.

Extracted verbatim from the original `TopicPipelineStatusService` so the
per-stage modules under `book_ingestion_v2/stages/` can call them as free
functions. No behaviour change vs. Phase 0.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from book_ingestion_v2.models.database import ChapterProcessingJob
from book_ingestion_v2.models.schemas import StageId, StageState, StageStatus


def latest_job_for_guideline(
    db: Session,
    *,
    guideline_id: str,
    job_type: str,
) -> Optional[ChapterProcessingJob]:
    """Find the latest job for a topic.

    Primary path (post-migration): filter by native `guideline_id` column.
    Fallback (historical rows): pre-migration post-sync jobs stored the
    guideline UUID in `chapter_id` with `guideline_id IS NULL`. We OR those
    in so callers see the complete history regardless of migration state.
    """
    return (
        db.query(ChapterProcessingJob)
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


def derive_state(
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


def overlay_job_state(
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


def build_stage(
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


def build_blocked(
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


def job_failed(job: Optional[ChapterProcessingJob]) -> bool:
    return bool(job and job.status == "failed")


def fmt_ago(ts: Optional[datetime]) -> str:
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
