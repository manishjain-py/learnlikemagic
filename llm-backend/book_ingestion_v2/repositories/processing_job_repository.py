"""Repository for ChapterProcessingJob data access."""
from typing import List, Optional
from sqlalchemy.orm import Session

from book_ingestion_v2.models.database import ChapterProcessingJob


class ProcessingJobRepository:
    """Repository for ChapterProcessingJob database operations."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, job: ChapterProcessingJob) -> ChapterProcessingJob:
        """Create a new processing job."""
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get_by_id(self, job_id: str) -> Optional[ChapterProcessingJob]:
        """Get job by ID."""
        return self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.id == job_id
        ).first()

    def get_active_job(self, chapter_id: str) -> Optional[ChapterProcessingJob]:
        """Get the currently active (pending or running) job for a chapter."""
        return self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.chapter_id == chapter_id,
            ChapterProcessingJob.status.in_(["pending", "running"])
        ).first()

    def get_latest_job(
        self, chapter_id: str, job_type: Optional[str] = None
    ) -> Optional[ChapterProcessingJob]:
        """Get the most recent job for a chapter, optionally filtered by type."""
        query = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.chapter_id == chapter_id
        )
        if job_type:
            query = query.filter(ChapterProcessingJob.job_type == job_type)
        return query.order_by(ChapterProcessingJob.created_at.desc()).first()

    def get_by_chapter_id(self, chapter_id: str) -> List[ChapterProcessingJob]:
        """Get all jobs for a chapter, ordered by creation time."""
        return self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.chapter_id == chapter_id
        ).order_by(ChapterProcessingJob.created_at.desc()).all()

    def get_by_book_id(self, book_id: str) -> List[ChapterProcessingJob]:
        """Get all jobs for a book."""
        return self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.book_id == book_id
        ).order_by(ChapterProcessingJob.created_at.desc()).all()

    def update(self, job: ChapterProcessingJob) -> ChapterProcessingJob:
        """Update job instance."""
        self.db.commit()
        self.db.refresh(job)
        return job

    def delete_by_chapter_id(self, chapter_id: str) -> int:
        """Delete all jobs for a chapter. Returns count deleted."""
        count = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.chapter_id == chapter_id
        ).delete()
        self.db.commit()
        return count
