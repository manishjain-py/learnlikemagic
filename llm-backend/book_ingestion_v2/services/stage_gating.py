"""Centralized stage gating for the book ingestion pipeline.

Each chapter-scoped stage can only be triggered when the chapter is in one of
a set of acceptable states. This module is the single source of truth for that
gating so it stays consistent across endpoints.

Post-sync stages (explanations, visuals, check-ins, practice bank) are NOT
gated here — they operate across chapters and filter at the guideline level
via `review_status == APPROVED`.
"""
from book_ingestion_v2.constants import ChapterStatus, V2JobType
from book_ingestion_v2.exceptions import StageGateRejected


# job_type -> allowed chapter statuses. The ":resume" suffix is used when the
# caller wants to re-enter a partially-done stage (e.g., resume a crashed
# topic extraction).
STAGE_PREREQUISITES: dict[str, set[str]] = {
    V2JobType.OCR.value: {
        ChapterStatus.UPLOAD_IN_PROGRESS.value,
        ChapterStatus.UPLOAD_COMPLETE.value,
    },
    V2JobType.TOPIC_EXTRACTION.value: {
        ChapterStatus.UPLOAD_COMPLETE.value,
    },
    f"{V2JobType.TOPIC_EXTRACTION.value}:resume": {
        ChapterStatus.UPLOAD_COMPLETE.value,
        ChapterStatus.TOPIC_EXTRACTION.value,
        ChapterStatus.FAILED.value,
        ChapterStatus.NEEDS_REVIEW.value,
    },
    V2JobType.REFINALIZATION.value: {
        ChapterStatus.CHAPTER_COMPLETED.value,
        ChapterStatus.FAILED.value,
        ChapterStatus.NEEDS_REVIEW.value,
    },
}


def require_stage_ready(chapter, job_type: str, *, resume: bool = False) -> None:
    """Raise 409 if chapter is not in a valid state for the given stage.

    Args:
        chapter: BookChapter (must expose .status).
        job_type: One of V2JobType.*.value.
        resume: If True, use the resume-mode prerequisites (broader set
            that accepts failed/partial states).

    Returns None if the stage is not chapter-gated (post-sync stages).
    """
    key = f"{job_type}:resume" if resume else job_type
    allowed = STAGE_PREREQUISITES.get(key) or STAGE_PREREQUISITES.get(job_type)
    if allowed is None:
        return  # Not a chapter-gated stage
    if chapter.status not in allowed:
        raise StageGateRejected(
            f"Cannot start {job_type} for chapter in state '{chapter.status}'. "
            f"Expected one of: {sorted(allowed)}"
        )
