"""Repository for ChapterChunk data access."""
from typing import List, Optional
from sqlalchemy.orm import Session

from book_ingestion_v2.models.database import ChapterChunk


class ChunkRepository:
    """Repository for ChapterChunk database operations."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, chunk: ChapterChunk) -> ChapterChunk:
        """Create a new chunk record."""
        self.db.add(chunk)
        self.db.commit()
        self.db.refresh(chunk)
        return chunk

    def get_by_id(self, chunk_id: str) -> Optional[ChapterChunk]:
        """Get chunk by ID."""
        return self.db.query(ChapterChunk).filter(
            ChapterChunk.id == chunk_id
        ).first()

    def get_by_job_id(self, job_id: str) -> List[ChapterChunk]:
        """Get all chunks for a processing job, ordered by chunk index."""
        return self.db.query(ChapterChunk).filter(
            ChapterChunk.processing_job_id == job_id
        ).order_by(ChapterChunk.chunk_index).all()

    def get_by_chapter_id(self, chapter_id: str) -> List[ChapterChunk]:
        """Get all chunks for a chapter, ordered by chunk index."""
        return self.db.query(ChapterChunk).filter(
            ChapterChunk.chapter_id == chapter_id
        ).order_by(ChapterChunk.chunk_index).all()

    def get_failed_chunks(self, job_id: str) -> List[ChapterChunk]:
        """Get failed chunks for a job."""
        return self.db.query(ChapterChunk).filter(
            ChapterChunk.processing_job_id == job_id,
            ChapterChunk.status == "failed"
        ).order_by(ChapterChunk.chunk_index).all()

    def get_last_completed_chunk(self, job_id: str) -> Optional[ChapterChunk]:
        """Get the last completed chunk for a job (for resume support)."""
        return self.db.query(ChapterChunk).filter(
            ChapterChunk.processing_job_id == job_id,
            ChapterChunk.status == "completed"
        ).order_by(ChapterChunk.chunk_index.desc()).first()

    def update(self, chunk: ChapterChunk) -> ChapterChunk:
        """Update chunk instance."""
        self.db.commit()
        self.db.refresh(chunk)
        return chunk

    def delete_by_job_id(self, job_id: str) -> int:
        """Delete all chunks for a job. Returns count deleted."""
        count = self.db.query(ChapterChunk).filter(
            ChapterChunk.processing_job_id == job_id
        ).delete()
        self.db.commit()
        return count

    def delete_by_chapter_id(self, chapter_id: str) -> int:
        """Delete all chunks for a chapter. Returns count deleted."""
        count = self.db.query(ChapterChunk).filter(
            ChapterChunk.chapter_id == chapter_id
        ).delete()
        self.db.commit()
        return count
