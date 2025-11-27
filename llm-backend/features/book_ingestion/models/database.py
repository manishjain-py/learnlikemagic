"""SQLAlchemy ORM models for book ingestion feature."""
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, Index, text
from models.database import Base  # Import the shared Base from existing models


class Book(Base):
    """
    Book table - stores metadata for uploaded textbooks.

    Status flow:
    draft → uploading_pages → pages_complete → generating_guidelines →
    guidelines_pending_review → approved
    """
    __tablename__ = "books"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    author = Column(String, nullable=True)
    edition = Column(String, nullable=True)
    edition_year = Column(Integer, nullable=True)
    country = Column(String, nullable=False)
    board = Column(String, nullable=False)  # e.g., "CBSE"
    grade = Column(Integer, nullable=False)
    subject = Column(String, nullable=False)  # e.g., "Mathematics"

    # S3 storage
    cover_image_s3_key = Column(String, nullable=True)
    s3_prefix = Column(String, nullable=False)  # books/{book_id}/
    metadata_s3_key = Column(String, nullable=True)  # books/{book_id}/metadata.json

    # Status tracking
    status = Column(String, nullable=False)  # draft, uploading_pages, pages_complete, etc.

    # Audit fields
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(String, default="admin")

    __table_args__ = (
        Index("idx_books_curriculum", "country", "board", "grade", "subject"),
        Index("idx_books_status", "status"),
    )


class BookGuideline(Base):
    """
    Book guidelines table - stores AI-generated guidelines for review.

    One book can have multiple guideline versions (regenerations).
    """
    __tablename__ = "book_guidelines"

    id = Column(String, primary_key=True)
    book_id = Column(String, ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    guideline_s3_key = Column(String, nullable=False)  # books/{book_id}/guideline.json

    # Review status
    status = Column(String, nullable=False)  # draft, pending_review, approved, rejected
    review_status = Column(String, default='TO_BE_REVIEWED')  # TO_BE_REVIEWED, APPROVED
    generated_at = Column(DateTime, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String, nullable=True)
    version = Column(Integer, default=1)

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_book_guidelines_book", "book_id"),
    )


class BookJob(Base):
    """
    Track active jobs per book to prevent concurrent operations.
    
    Job types: extraction, finalization, sync
    """
    __tablename__ = "book_jobs"

    id = Column(String, primary_key=True)
    book_id = Column(String, ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    job_type = Column(String, nullable=False)  # extraction, finalization, sync
    status = Column(String, default='running')  # running, completed, failed
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        # Ensure only one running job per book
        Index('idx_book_running_job', 'book_id', 'status',
              postgresql_where=text("status = 'running'")),
    )
