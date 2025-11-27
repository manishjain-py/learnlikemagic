
import uuid
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from ..models.database import BookJob

class JobLockError(Exception):
    """Raised when a job lock cannot be acquired."""
    pass

class JobLockService:
    """
    Service to manage job locks for book operations.
    Prevents concurrent extraction/finalization jobs for the same book.
    """
    
    def __init__(self, db_session: Session):
        self.db = db_session

    def acquire_lock(self, book_id: str, job_type: str) -> str:
        """
        Acquire job lock for a book. Raises JobLockError if lock already held.
        Returns job_id.
        """
        # Check for existing running job
        existing = self.db.query(BookJob).filter(
            BookJob.book_id == book_id,
            BookJob.status == 'running'
        ).first()

        if existing:
            raise JobLockError(
                f"Job already running for book {book_id}: "
                f"{existing.job_type} (started {existing.started_at})"
            )

        # Create new job record
        job_id = str(uuid.uuid4())
        job = BookJob(
            id=job_id,
            book_id=book_id,
            job_type=job_type,
            status='running'
        )
        
        try:
            self.db.add(job)
            self.db.commit()
            return job_id
        except IntegrityError:
            self.db.rollback()
            # Race condition check
            raise JobLockError(f"Job lock race condition for book {book_id}")
        except Exception as e:
            self.db.rollback()
            raise e

    def release_lock(self, job_id: str, status: str = 'completed', error: str = None):
        """Release job lock."""
        try:
            job = self.db.query(BookJob).filter(BookJob.id == job_id).first()
            if job:
                job.status = status
                job.completed_at = datetime.utcnow()
                job.error_message = error
                self.db.commit()
        except Exception as e:
            self.db.rollback()
            # Log error but don't raise, as the main operation might have succeeded
            print(f"Failed to release lock {job_id}: {e}")
