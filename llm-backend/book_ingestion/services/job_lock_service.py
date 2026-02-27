"""
Job lock service with state machine enforcement and stale detection.

State machine: pending → running → completed|failed
Stale detection: running jobs with expired heartbeat are auto-marked failed.

All job state transitions go through this service. No code outside this
service may directly update BookJob.status.
"""
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from ..models.database import BookJob

logger = logging.getLogger(__name__)

HEARTBEAT_STALE_THRESHOLD = timedelta(minutes=2)


class JobLockError(Exception):
    """Raised when a job lock cannot be acquired."""
    pass


class InvalidStateTransition(Exception):
    """Raised when an invalid job state transition is attempted."""
    pass


class JobLockService:
    """
    Service to manage job locks for book operations.

    Enforces the job state machine:
      pending → running → completed|failed
      running → stale (auto) → failed (auto)

    Concurrency guarantees:
      - Partial unique index: at most one pending/running job per book
      - SELECT ... FOR UPDATE: atomic state transitions
      - Heartbeat-based stale detection: backstop for leaked running jobs
    """

    def __init__(self, db_session: Session):
        self.db = db_session

    def acquire_lock(self, book_id: str, job_type: str, total_items: int = None) -> str:
        """
        Create a new job in 'pending' state. Returns job_id.
        Raises JobLockError if a pending/running job already exists for this book.
        """
        # Check for existing active jobs (pending OR running)
        existing = self.db.query(BookJob).filter(
            BookJob.book_id == book_id,
            BookJob.status.in_(['pending', 'running'])
        ).first()

        if existing:
            # Before raising, check if it's stale
            if existing.status == 'running' and self._is_stale(existing):
                self._mark_stale(existing)
            else:
                raise JobLockError(
                    f"Job already {existing.status} for book {book_id}: "
                    f"{existing.job_type} (started {existing.started_at})"
                )

        job = BookJob(
            id=str(uuid.uuid4()),
            book_id=book_id,
            job_type=job_type,
            status='pending',
            total_items=total_items,
        )

        try:
            self.db.add(job)
            self.db.commit()
            logger.info(f"Job {job.id} created: book={book_id} type={job_type} total_items={total_items}")
            return job.id
        except IntegrityError:
            self.db.rollback()
            raise JobLockError(f"Another job was just created for book {book_id}")

    def start_job(self, job_id: str):
        """
        Transition pending → running. Called by background thread as first action.
        Uses row-level lock to prevent stale-detection race.
        """
        job = self.db.query(BookJob).filter(
            BookJob.id == job_id
        ).with_for_update().first()

        if not job:
            raise InvalidStateTransition(f"Job {job_id} not found")
        if job.status != 'pending':
            raise InvalidStateTransition(f"Cannot start job in '{job.status}' state")

        old_status = job.status
        job.status = 'running'
        job.heartbeat_at = datetime.utcnow()
        self.db.commit()
        logger.info(f"Job {job_id} transitioned {old_status} → running")

    def update_progress(
        self,
        job_id: str,
        current_item: int,
        completed: int,
        failed: int = 0,
        last_completed_item: Optional[int] = None,
        detail: Optional[str] = None,
    ):
        """
        Update job progress + heartbeat. Called after each page.
        All fields use absolute values (not deltas) for idempotency.
        """
        job = self.db.query(BookJob).filter(BookJob.id == job_id).first()
        if not job or job.status != 'running':
            return  # Job was cancelled or marked stale externally

        job.current_item = current_item
        job.completed_items = completed
        job.failed_items = failed
        job.heartbeat_at = datetime.utcnow()

        if last_completed_item is not None:
            job.last_completed_item = last_completed_item
        if detail is not None:
            job.progress_detail = detail

        self.db.commit()

    def release_lock(self, job_id: str, status: str = 'completed', error: str = None):
        """
        Transition running → completed/failed. Terminal state.
        """
        job = self.db.query(BookJob).filter(
            BookJob.id == job_id
        ).with_for_update().first()

        if not job:
            logger.warning(f"Cannot release lock: job {job_id} not found")
            return
        if job.status not in ('running', 'pending'):
            logger.warning(f"Cannot release job {job_id} in '{job.status}' state")
            return

        old_status = job.status
        job.status = status
        job.completed_at = datetime.utcnow()
        job.error_message = error
        self.db.commit()
        logger.info(f"Job {job_id} transitioned {old_status} → {status}")

    def get_job(self, job_id: str) -> Optional[dict]:
        """Return job as dict with all progress fields."""
        job = self.db.query(BookJob).filter(BookJob.id == job_id).first()
        if not job:
            return None
        return self._job_to_dict(job)

    def get_latest_job(self, book_id: str, job_type: Optional[str] = None) -> Optional[dict]:
        """
        Get most recent job for a book.
        Automatically detects and marks stale jobs (server-side).
        """
        query = self.db.query(BookJob).filter(BookJob.book_id == book_id)
        if job_type:
            query = query.filter(BookJob.job_type == job_type)
        job = query.order_by(BookJob.started_at.desc()).first()

        if not job:
            return None

        # Server-side stale detection on every read
        if job.status == 'running' and self._is_stale(job):
            self._mark_stale(job)

        return self._job_to_dict(job)

    def _is_stale(self, job: BookJob) -> bool:
        """A running job is stale if heartbeat hasn't been updated recently."""
        if not job.heartbeat_at:
            return (datetime.utcnow() - job.started_at) > HEARTBEAT_STALE_THRESHOLD
        return (datetime.utcnow() - job.heartbeat_at) > HEARTBEAT_STALE_THRESHOLD

    def _mark_stale(self, job: BookJob):
        """
        Transition running → failed with stale error.
        Re-checks under row lock to prevent race with start_job.
        """
        job = self.db.query(BookJob).filter(
            BookJob.id == job.id
        ).with_for_update().first()

        if job.status != 'running':
            return  # Another thread already transitioned it
        if not self._is_stale(job):
            return  # Heartbeat was refreshed between our check and lock acquisition

        old_status = job.status
        job.status = 'failed'
        job.completed_at = datetime.utcnow()
        job.error_message = (
            f"Job interrupted (no heartbeat since "
            f"{job.heartbeat_at.isoformat() if job.heartbeat_at else 'never'}). "
            f"Container may have restarted. Resume from page {job.last_completed_item or 'start'}."
        )
        self.db.commit()
        logger.warning(
            f"Job {job.id} transitioned {old_status} → failed (stale: "
            f"no heartbeat since {job.heartbeat_at})"
        )

    def _job_to_dict(self, job: BookJob) -> dict:
        """Convert BookJob to dict with all fields."""
        return {
            "job_id": job.id,
            "book_id": job.book_id,
            "job_type": job.job_type,
            "status": job.status,
            "total_items": job.total_items,
            "completed_items": job.completed_items or 0,
            "failed_items": job.failed_items or 0,
            "current_item": job.current_item,
            "last_completed_item": job.last_completed_item,
            "progress_detail": job.progress_detail,
            "heartbeat_at": job.heartbeat_at.isoformat() if job.heartbeat_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "error_message": job.error_message,
        }
