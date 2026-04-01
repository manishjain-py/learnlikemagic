"""
Chapter job service — job lock + progress tracking per chapter.

Adapts V1 JobLockService pattern but scoped to chapters instead of books.

State machine: pending → running → completed|completed_with_errors|failed
Stale detection: running jobs with expired heartbeat are auto-marked failed.
"""
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from book_ingestion_v2.constants import HEARTBEAT_STALE_THRESHOLD, PENDING_STALE_THRESHOLD
from book_ingestion_v2.models.database import ChapterProcessingJob
from book_ingestion_v2.models.schemas import ProcessingJobResponse

logger = logging.getLogger(__name__)

_HEARTBEAT_THRESHOLD = timedelta(seconds=HEARTBEAT_STALE_THRESHOLD)
_PENDING_THRESHOLD = timedelta(seconds=PENDING_STALE_THRESHOLD)


class ChapterJobLockError(Exception):
    """Raised when a job lock cannot be acquired."""
    pass


class ChapterJobService:
    """
    Service to manage job locks for chapter operations.

    Enforces the job state machine:
      pending → running → completed|completed_with_errors|failed
    """

    def __init__(self, db: Session):
        self.db = db

    def acquire_lock(
        self, book_id: str, chapter_id: str, job_type: str, total_items: int = None
    ) -> str:
        """
        Create a new job in 'pending' state. Returns job_id.
        Raises ChapterJobLockError if a pending/running job already exists.
        """
        existing = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.chapter_id == chapter_id,
            ChapterProcessingJob.status.in_(["pending", "running"]),
        ).first()

        if existing:
            if existing.status == "running" and self._is_stale(existing):
                self._mark_stale(existing)
            elif existing.status == "pending" and self._is_pending_stale(existing):
                self._mark_pending_abandoned(existing)
            else:
                raise ChapterJobLockError(
                    f"Job already {existing.status} for chapter {chapter_id}: "
                    f"{existing.job_type} (started {existing.started_at})"
                )

        job = ChapterProcessingJob(
            id=str(uuid.uuid4()),
            book_id=book_id,
            chapter_id=chapter_id,
            job_type=job_type,
            status="pending",
            total_items=total_items,
        )

        try:
            self.db.add(job)
            self.db.commit()
            logger.info(
                f"Job {job.id} created: chapter={chapter_id} type={job_type} "
                f"total_items={total_items}"
            )
            return job.id
        except IntegrityError:
            self.db.rollback()
            raise ChapterJobLockError(
                f"Another job was just created for chapter {chapter_id}"
            )

    def start_job(self, job_id: str):
        """Transition pending → running. Uses row lock to prevent race."""
        job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.id == job_id
        ).with_for_update().first()

        if not job:
            raise ValueError(f"Job {job_id} not found")
        if job.status != "pending":
            raise ValueError(f"Cannot start job in '{job.status}' state")

        job.status = "running"
        job.heartbeat_at = datetime.utcnow()
        self.db.commit()
        logger.info(f"Job {job_id} transitioned pending → running")

    def update_progress(
        self,
        job_id: str,
        current_item: Optional[str] = None,
        completed: int = 0,
        failed: int = 0,
        last_completed_item: Optional[str] = None,
        detail: Optional[str] = None,
    ):
        """Update job progress + heartbeat. Uses absolute values for idempotency."""
        job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.id == job_id
        ).first()
        if not job or job.status != "running":
            return

        job.current_item = current_item
        job.completed_items = completed
        job.failed_items = failed
        job.heartbeat_at = datetime.utcnow()

        if last_completed_item is not None:
            job.last_completed_item = last_completed_item
        if detail is not None:
            job.progress_detail = detail

        self.db.commit()

    def release_lock(
        self, job_id: str, status: str = "completed", error: str = None
    ):
        """Transition running → completed/failed. Terminal state."""
        job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.id == job_id
        ).with_for_update().first()

        if not job:
            logger.warning(f"Cannot release lock: job {job_id} not found")
            return
        if job.status not in ("running", "pending"):
            logger.warning(f"Cannot release job {job_id} in '{job.status}' state")
            return

        old_status = job.status
        job.status = status
        job.completed_at = datetime.utcnow()
        job.error_message = error
        self.db.commit()
        logger.info(f"Job {job_id} transitioned {old_status} → {status}")

    def get_job(self, job_id: str) -> Optional[ProcessingJobResponse]:
        """Get job by ID as response schema."""
        job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.id == job_id
        ).first()
        if not job:
            return None
        return self._to_response(job)

    def get_latest_job(
        self, chapter_id: str, job_type: Optional[str] = None
    ) -> Optional[ProcessingJobResponse]:
        """Get most recent job for a chapter. Detects stale jobs."""
        query = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.chapter_id == chapter_id
        )
        if job_type:
            query = query.filter(ChapterProcessingJob.job_type == job_type)
        job = query.order_by(ChapterProcessingJob.created_at.desc()).first()

        if not job:
            return None

        # Server-side stale detection
        if job.status == "running" and self._is_stale(job):
            self._mark_stale(job)
        elif job.status == "pending" and self._is_pending_stale(job):
            self._mark_pending_abandoned(job)

        return self._to_response(job)

    def _is_stale(self, job: ChapterProcessingJob) -> bool:
        if not job.heartbeat_at:
            return (datetime.utcnow() - job.started_at) > _HEARTBEAT_THRESHOLD
        return (datetime.utcnow() - job.heartbeat_at) > _HEARTBEAT_THRESHOLD

    def _is_pending_stale(self, job: ChapterProcessingJob) -> bool:
        return (datetime.utcnow() - job.started_at) > _PENDING_THRESHOLD

    def _mark_stale(self, job: ChapterProcessingJob):
        job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.id == job.id
        ).with_for_update().first()

        if job.status != "running":
            return
        if not self._is_stale(job):
            return

        job.status = "failed"
        job.completed_at = datetime.utcnow()
        job.error_message = (
            f"Job interrupted (no heartbeat since "
            f"{job.heartbeat_at.isoformat() if job.heartbeat_at else 'never'}). "
            f"Resume from chunk {job.last_completed_item or 'start'}."
        )
        self.db.commit()
        logger.warning(f"Job {job.id} marked stale → failed")

    def _mark_pending_abandoned(self, job: ChapterProcessingJob):
        job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.id == job.id
        ).with_for_update().first()

        if job.status != "pending":
            return

        job.status = "failed"
        job.completed_at = datetime.utcnow()
        job.error_message = (
            f"Job abandoned (stuck in pending since {job.started_at.isoformat()})."
        )
        self.db.commit()
        logger.warning(f"Job {job.id} marked abandoned → failed")

    def append_stage_snapshots(self, job_id: str, snapshots: list[dict]):
        """Append stage snapshots to job's stage_snapshots_json."""
        import json
        job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.id == job_id,
        ).first()
        if not job:
            return
        existing = json.loads(job.stage_snapshots_json) if job.stage_snapshots_json else []
        existing.extend(snapshots)
        job.stage_snapshots_json = json.dumps(existing, default=str)
        job.heartbeat_at = datetime.utcnow()
        self.db.commit()

    def get_stage_snapshots(self, job_id: str, guideline_id: str | None = None) -> list[dict]:
        """Get stage snapshots for a job, optionally filtered by guideline_id."""
        import json
        job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.id == job_id,
        ).first()
        if not job or not job.stage_snapshots_json:
            return []
        snapshots = json.loads(job.stage_snapshots_json)
        if guideline_id:
            snapshots = [s for s in snapshots if s.get("guideline_id") == guideline_id]
        return snapshots

    def _to_response(self, job: ChapterProcessingJob) -> ProcessingJobResponse:
        import json
        progress = None
        if job.progress_detail:
            try:
                progress = json.loads(job.progress_detail)
            except (json.JSONDecodeError, TypeError):
                progress = {"raw": job.progress_detail}

        return ProcessingJobResponse(
            job_id=job.id,
            chapter_id=job.chapter_id,
            job_type=job.job_type,
            status=job.status,
            total_items=job.total_items,
            completed_items=job.completed_items or 0,
            failed_items=job.failed_items or 0,
            current_item=job.current_item,
            last_completed_item=job.last_completed_item,
            progress_detail=progress,
            model_provider=job.model_provider,
            model_id=job.model_id,
            started_at=job.started_at,
            completed_at=job.completed_at,
            error_message=job.error_message,
        )
